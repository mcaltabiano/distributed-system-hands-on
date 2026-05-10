"""
Saga consumer — listens for Saga terminal events and updates order status.

Topics consumed:
  payment.processed  → status = 'confirmed'
  payment.failed     → status = 'failed'
  inventory.failed   → status = 'failed'
"""

import asyncio
import json
import logging
import os
import uuid

import asyncpg
from confluent_kafka import Consumer, KafkaError

log = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")

TOPIC_STATUS = {
    "payment.processed": "confirmed",
    "payment.failed":    "failed",
    "inventory.failed":  "failed",
}


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id":          "order-service-saga",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": False,
    })


async def run_saga_consumer(pool: asyncpg.Pool) -> None:
    consumer = _make_consumer()
    consumer.subscribe(list(TOPIC_STATUS.keys()))
    log.info("Saga consumer started")

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

            event    = json.loads(msg.value())
            order_id = uuid.UUID(event["order_id"])
            status   = TOPIC_STATUS[msg.topic()]

            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE orders SET status = $1 WHERE id = $2",
                    status, order_id,
                )

            log.info("Order %s → %s (via %s)", order_id, status, msg.topic())
            consumer.commit(asynchronous=False)
    finally:
        consumer.close()
