import asyncio
import logging
import os

import redis.asyncio as aioredis
from fastapi import FastAPI
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

from consumer import run_consumer

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    consumer_task = asyncio.create_task(run_consumer(redis_client))
    yield
    consumer_task.cancel()
    await redis_client.aclose()


app = FastAPI(title="Notification Service", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
