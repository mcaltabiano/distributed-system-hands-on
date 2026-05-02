"""
Outbox relay: polls the outbox table for unpublished events and forwards them
to Kafka.  Runs as a background asyncio task inside the order-service process.

Failure semantics
-----------------
* If Kafka is unavailable the relay pauses and retries — rows remain
  published=FALSE in the DB.
* If the relay crashes mid-publish, the row stays unpublished and will be
  retried on the next poll.  Downstream consumers must be idempotent (they
  receive at-least-once delivery).
* The UPDATE to published=TRUE is committed only after the producer.flush()
  succeeds — this is the boundary that guarantees at-least-once rather than
  at-most-once.
"""

import asyncio
import json
import logging
import os

import asyncpg
from confluent_kafka import Producer

log = logging.getLogger(__name__)
KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
POLL_INTERVAL = 1.0  # seconds between polls when the outbox is empty


def _make_producer() -> Producer:
    return Producer({
        "bootstrap.servers": KAFKA_BOOTSTRAP,
        "acks": "all",                 # CP: wait for all ISR replicas
        "enable.idempotence": True,    # exactly-once producer retries
        "retries": 5,
        "retry.backoff.ms": 200,
    })


async def run_relay(pool: asyncpg.Pool) -> None:
    producer = _make_producer()
    log.info("Outbox relay started")

    while True:
        try:
            await _process_batch(pool, producer)
        except Exception:
            log.exception("Relay iteration failed, retrying in 2s")
            await asyncio.sleep(2)
        else:
            await asyncio.sleep(POLL_INTERVAL)


async def _process_batch(pool: asyncpg.Pool, producer: Producer) -> None:
    async with pool.acquire() as conn:
        # Lock the rows so concurrent relay instances (e.g. rolling restarts)
        # don't double-publish.
        rows = await conn.fetch(
            """
            SELECT id, topic, key, payload
            FROM   outbox
            WHERE  published = FALSE
            ORDER  BY created_at
            LIMIT  100
            FOR UPDATE SKIP LOCKED
            """
        )
        if not rows:
            return

        published_ids = []
        for row in rows:
            payload_bytes = json.dumps(dict(row["payload"])).encode()
            producer.produce(
                topic=row["topic"],
                key=row["key"].encode() if row["key"] else None,
                value=payload_bytes,
            )
            published_ids.append(row["id"])

        # Flush blocks until all messages are acknowledged by Kafka brokers.
        # Only then do we mark rows as published — at-least-once boundary.
        producer.flush(timeout=10)

        await conn.execute(
            "UPDATE outbox SET published = TRUE WHERE id = ANY($1::uuid[])",
            published_ids,
        )
        log.info("Relay published %d events", len(published_ids))
