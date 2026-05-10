import asyncio
import logging
import os

import asyncpg
from fastapi import FastAPI
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from consumer import run_consumer

DATABASE_URL = os.environ["DATABASE_URL"]

pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    consumer_task = asyncio.create_task(run_consumer(pool))
    yield
    consumer_task.cancel()
    await pool.close()


app = FastAPI(title="Payment Service", lifespan=lifespan)


@app.get("/payments/{order_id}")
async def get_payment(order_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT order_id, amount_cents, status, created_at FROM payments WHERE order_id = $1",
            order_id,
        )
    if row is None:
        return {"error": "not found"}
    return dict(row)


@app.get("/health")
async def health():
    return {"status": "ok"}
