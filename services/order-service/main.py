import asyncio
import os
import uuid

import asyncpg
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from models import OrderRequest, OrderResponse
from outbox_relay import run_relay

DATABASE_URL = os.environ["DATABASE_URL"]

pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    relay_task = asyncio.create_task(run_relay(pool))
    yield
    relay_task.cancel()
    await pool.close()


app = FastAPI(title="Order Service", lifespan=lifespan)


@app.post("/orders", response_model=OrderResponse, status_code=201)
async def create_order(req: OrderRequest):
    order_id = uuid.uuid4()
    payload = {
        "order_id": str(order_id),
        "product_id": req.product_id,
        "quantity": req.quantity,
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO orders (id, product_id, quantity) VALUES ($1, $2, $3)",
                order_id, req.product_id, req.quantity,
            )
            # Write the outbox event in the SAME transaction — atomic with the order insert.
            # The relay picks this up and publishes to Kafka independently.
            await conn.execute(
                "INSERT INTO outbox (topic, key, payload) VALUES ($1, $2, $3::jsonb)",
                "order.placed", str(order_id), str(payload).replace("'", '"'),
            )

    return OrderResponse(
        order_id=order_id,
        product_id=req.product_id,
        quantity=req.quantity,
        status="pending",
    )


@app.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: uuid.UUID):
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, product_id, quantity, status FROM orders WHERE id = $1",
            order_id,
        )
    if row is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return OrderResponse(
        order_id=row["id"],
        product_id=row["product_id"],
        quantity=row["quantity"],
        status=row["status"],
    )


@app.get("/health")
async def health():
    return {"status": "ok"}
