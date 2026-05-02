"""
Notification consumer — AP service.

Listens on payment.processed.  Uses Redis SETNX with a TTL as a best-effort
dedup key: if the same order_id was notified recently, skip it.

AP design rationale from the README:
  - A duplicate email is annoying, not catastrophic.
  - A missed notification (Redis unavailable) is acceptable.
  - Eliminating CP complexity here keeps the service simple and available.

Redis failure mode: if Redis is unreachable, the dedup check is skipped and
the notification is sent anyway.  The service never blocks on Redis health.
"""

import asyncio
import json
import logging
import os

import redis.asyncio as aioredis
from confluent_kafka import Consumer, KafkaError

log = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
DEDUP_TTL_SECONDS = 3600


def _make_consumer() -> Consumer:
    return Consumer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "group.id": "notification-service",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,   # AP: auto-commit, no manual ack
    })


async def run_consumer(redis_client: aioredis.Redis) -> None:
    consumer = _make_consumer()
    consumer.subscribe(["payment.processed"])
    log.info("Notification consumer started")

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

            await _handle(redis_client, msg)
    finally:
        consumer.close()


async def _handle(redis_client: aioredis.Redis, msg) -> None:
    event = json.loads(msg.value())
    order_id = event["order_id"]
    dedup_key = f"notif:sent:{order_id}"

    try:
        already_sent = await redis_client.set(dedup_key, "1", nx=True, ex=DEDUP_TTL_SECONDS)
        if already_sent is None:
            log.info("Notification already sent for order %s — skipping", order_id)
            return
    except Exception:
        # Redis unavailable — AP choice: proceed without dedup rather than block.
        log.warning("Redis unavailable, sending notification without dedup for order %s", order_id)

    amount_euros = event.get("amount_cents", 0) / 100
    log.info(
        "[EMAIL] Order %s confirmed. Payment of €%.2f received. Thank you!",
        order_id, amount_euros,
    )
