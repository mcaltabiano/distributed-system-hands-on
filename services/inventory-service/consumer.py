"""
Inventory consumer — CP service.

Listens on order.placed, reserves stock using SELECT FOR UPDATE (pessimistic
lock), and publishes inventory.reserved or inventory.failed.

SELECT FOR UPDATE means two concurrent orders for the same product are
serialized at the DB level: the second waits until the first commits.  This
is linearizability in practice — no oversell is possible.
"""

import asyncio
import json
import logging
import os
import uuid

import asyncpg
from confluent_kafka import Consumer, Producer, KafkaError

log = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": "inventory-service",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,   # manual commit after DB write succeeds
    })


def _make_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "acks": "all",
        "enable.idempotence": True,
    })


async def run_consumer(pool: asyncpg.Pool) -> None:
    consumer = _make_consumer()
    producer = _make_producer()
    consumer.subscribe(["order.placed"])
    log.info("Inventory consumer started")

    loop = asyncio.get_event_loop()
    try:
        while True:
            msg = await loop.run_in_executor(None, lambda: consumer.poll(1.0))
            if msg is None:
                continue
            if msg.error():
                if msg.error().code() != KafkaError._PARTITION_EOF:
                    log.error("Consumer error: %s", msg.error())
                continue

            await _handle(pool, producer, msg)
            consumer.commit(asynchronous=False)
    finally:
        consumer.close()


async def _handle(pool: asyncpg.Pool, producer: Producer, msg) -> None:
    event = json.loads(msg.value())
    order_id = uuid.UUID(event["order_id"])
    product_id = event["product_id"]
    quantity = int(event["quantity"])

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Pessimistic lock — only one transaction holds this row at a time.
            row = await conn.fetchrow(
                "SELECT stock FROM products WHERE id = $1 FOR UPDATE",
                product_id,
            )

            if row is None or row["stock"] < quantity:
                topic = "inventory.failed"
                payload = {
                    "order_id": str(order_id),
                    "product_id": product_id,
                    "reason": "insufficient_stock",
                    "available": row["stock"] if row else 0,
                }
            else:
                await conn.execute(
                    "UPDATE products SET stock = stock - $1 WHERE id = $2",
                    quantity, product_id,
                )
                await conn.execute(
                    "INSERT INTO reservations (order_id, product_id, quantity) VALUES ($1, $2, $3)",
                    order_id, product_id, quantity,
                )
                topic = "inventory.reserved"
                payload = {
                    "order_id": str(order_id),
                    "product_id": product_id,
                    "quantity": quantity,
                }

    producer.produce(
        topic=topic,
        key=str(order_id).encode(),
        value=json.dumps(payload).encode(),
    )
    producer.flush()
    log.info("Published %s for order %s", topic, order_id)


async def _release_stock(pool: asyncpg.Pool, order_id: uuid.UUID) -> None:
    """Compensation: called when payment.failed arrives (imported by a saga listener if added)."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT product_id, quantity FROM reservations WHERE order_id = $1",
                order_id,
            )
            if row is None:
                return
            await conn.execute(
                "UPDATE products SET stock = stock + $1 WHERE id = $2",
                row["quantity"], row["product_id"],
            )
            await conn.execute(
                "DELETE FROM reservations WHERE order_id = $1", order_id
            )
    log.info("Released stock for order %s", order_id)
