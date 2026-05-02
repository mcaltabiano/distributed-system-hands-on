"""
Payment consumer — CP service with idempotency key.

Listens on inventory.reserved.  Uses order_id as idempotency key: if the same
message is delivered twice (Kafka at-least-once), the second INSERT hits the
UNIQUE constraint and is silently ignored.  The client is never charged twice.

Publishes payment.processed or payment.failed.
"""

import asyncio
import json
import logging
import os
import uuid

import asyncpg
from confluent_kafka import Consumer, Producer, KafkaError
from asyncpg import UniqueViolationError

log = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": "payment-service",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
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
    consumer.subscribe(["inventory.reserved"])
    log.info("Payment consumer started")

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
    quantity = int(event["quantity"])
    # Dummy pricing: 10.00 EUR per unit
    amount_cents = quantity * 1000

    try:
        async with pool.acquire() as conn:
            # The UNIQUE constraint on order_id is the idempotency key.
            # A second delivery of this message raises UniqueViolationError,
            # which we catch and ignore — no double charge.
            await conn.execute(
                "INSERT INTO payments (order_id, amount_cents) VALUES ($1, $2)",
                order_id, amount_cents,
            )
        topic = "payment.processed"
        payload = {"order_id": str(order_id), "amount_cents": amount_cents}
        log.info("Payment processed for order %s (%d cents)", order_id, amount_cents)

    except UniqueViolationError:
        # Idempotent no-op: this order was already paid.
        log.warning("Duplicate payment attempt for order %s — ignoring", order_id)
        return

    except Exception as exc:
        log.error("Payment failed for order %s: %s", order_id, exc)
        topic = "payment.failed"
        payload = {"order_id": str(order_id), "reason": str(exc)}

    producer.produce(
        topic=topic,
        key=str(order_id).encode(),
        value=json.dumps(payload).encode(),
    )
    producer.flush()
