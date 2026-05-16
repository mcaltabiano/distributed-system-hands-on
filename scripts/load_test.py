#!/usr/bin/env python3
"""
load_test.py — fire concurrent orders and report results.

Usage:
    python scripts/load_test.py --orders 100 --product-id abc --quantity 1
    python scripts/load_test.py --orders 100 --product-id abc --quantity 1 --concurrency 20

What to observe:
  - With stock=50 and orders=100, exactly 50 should succeed (CP guarantee).
  - Any oversell (>50 reservations) indicates a bug in the inventory lock.
  - Run while inventory-service is partitioned to observe AP vs CP divergence.
  - Check final stock via: curl http://localhost:8002/products/abc/stock
"""

import argparse
import asyncio
import json
import sys
import time

try:
    import aiohttp
except ImportError:
    print("pip install aiohttp")
    sys.exit(1)

ORDER_SERVICE_URL = "http://localhost:8001/orders"
INVENTORY_URL = "http://localhost:8002/products/{product_id}/stock"


async def place_order(session: aiohttp.ClientSession, product_id: str, quantity: int) -> dict:
    try:
        async with session.post(
            ORDER_SERVICE_URL,
            json={"product_id": product_id, "quantity": quantity},
            timeout=aiohttp.ClientTimeout(total=5),
        ) as resp:
            body = await resp.json()
            return {"status": resp.status, "body": body}
    except Exception as exc:
        return {"status": 0, "error": str(exc)}


async def main():
    parser = argparse.ArgumentParser(description="Load test: concurrent orders")
    parser.add_argument("--orders",     type=int,   default=50,    help="Number of concurrent orders")
    parser.add_argument("--product-id", type=str,   default="abc", help="Product ID to order")
    parser.add_argument("--quantity",   type=int,   default=1,     help="Units per order")
    parser.add_argument("--concurrency",type=int,   default=20,    help="Max concurrent HTTP requests")
    args = parser.parse_args()

    print(f"Firing {args.orders} orders (product={args.product_id}, qty={args.quantity}, concurrency={args.concurrency})")
    print(f"Order service: {ORDER_SERVICE_URL}")
    print()

    sem = asyncio.Semaphore(args.concurrency)

    async def bounded(session, product_id, quantity):
        async with sem:
            return await place_order(session, product_id, quantity)

    start = time.monotonic()
    async with aiohttp.ClientSession() as session:
        tasks = [bounded(session, args.product_id, args.quantity) for _ in range(args.orders)]
        results = await asyncio.gather(*tasks)

    elapsed = time.monotonic() - start

    statuses = {}
    for r in results:
        code = r.get("status", 0)
        statuses[code] = statuses.get(code, 0) + 1

    print("=== Results ===")
    for code, count in sorted(statuses.items()):
        print(f"  HTTP {code}: {count}")
    print(f"  Total: {args.orders}  |  Elapsed: {elapsed:.2f}s  |  RPS: {args.orders/elapsed:.1f}")
    print()

    # Check stock after test
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(INVENTORY_URL.format(product_id=args.product_id)) as resp:
                stock = await resp.json()
        print(f"=== Post-test stock: {json.dumps(stock, indent=2)}")
    except Exception as exc:
        print(f"Could not fetch stock: {exc}")


if __name__ == "__main__":
    asyncio.run(main())
