import logging
import os
import asyncpg
from fastapi import FastAPI
from contextlib import asynccontextmanager
import asyncio

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


app = FastAPI(title="Inventory Service", lifespan=lifespan)


@app.get("/products/{product_id}/stock")
async def get_stock(product_id: str):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, name, stock FROM products WHERE id = $1", product_id
        )
    if row is None:
        return {"error": "not found"}
    return {"product_id": row["id"], "name": row["name"], "stock": row["stock"]}


@app.get("/health")
async def health():
    return {"status": "ok"}
