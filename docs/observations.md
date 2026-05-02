# Experiment Diary — Phase 4

Use this file to record what you observe during each experiment.
Each section has the expected outcome and space for your notes.

---

## Setup

```bash
docker compose up --build -d
docker compose logs -f          # tail all services
```

Verify all services healthy:
```bash
curl http://localhost:8001/health   # order-service
curl http://localhost:8002/health   # inventory-service
curl http://localhost:8003/health   # payment-service
curl http://localhost:8004/health   # notification-service
```

---

## Experiment 1 — Happy path

**Goal:** confirm the full Saga runs end-to-end for a single order.

```bash
curl -s -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": "abc", "quantity": 2}' | jq .
```

Follow the event chain in logs:
```
order-service     → INSERT order + outbox row (same transaction)
outbox relay      → publishes order.placed
inventory-service → SELECT FOR UPDATE → UPDATE stock → publishes inventory.reserved
payment-service   → INSERT payment (idempotency key) → publishes payment.processed
notification-service → Redis SETNX → [EMAIL] log line
```

**Expected final state:**
- Stock for `abc` decremented by 2
- Payment row present with `amount_cents = 2000`
- Notification log: `[EMAIL] Order ... confirmed`

**Your observations:**

---

## Experiment 2 — CP guarantee: no oversell

**Goal:** with stock=50 and 100 concurrent orders, exactly 50 succeed.

```bash
# Reset stock if needed
docker exec postgres-inventory psql -U app -d inventory \
  -c "UPDATE products SET stock = 50 WHERE id = 'abc';"

python scripts/load_test.py --orders 100 --product-id abc --quantity 1

# Check final stock
curl http://localhost:8002/products/abc/stock
```

**Expected:**
- HTTP 201: ~50 orders accepted
- Final stock: 0
- Zero oversell (stock never goes negative)

**What enforces this:** `SELECT FOR UPDATE` in inventory-service serializes concurrent reservations.
If you remove the `FOR UPDATE` and rerun, you may observe oversell.

**Your observations:**

---

## Experiment 3 — Idempotency key

**Goal:** demonstrate that duplicate Kafka delivery does not double-charge.

```bash
# Place one order and note its order_id
ORDER_ID=$(curl -s -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": "abc", "quantity": 1}' | jq -r .order_id)

echo "Order: $ORDER_ID"

# Wait for payment to process, then check
sleep 3
curl http://localhost:8003/payments/$ORDER_ID
```

To simulate a duplicate delivery, use the Kafka console producer to re-send
the `inventory.reserved` event for the same order_id and watch payment-service
logs for `Duplicate payment attempt`.

**Expected:**
- Second delivery: `WARNING Duplicate payment attempt for order ... — ignoring`
- DB has exactly one payment row for the order

**Your observations:**

---

## Experiment 4 — Network partition on inventory-service

**Goal:** observe what happens to in-flight orders when inventory is isolated.

```bash
# Start a background load
python scripts/load_test.py --orders 200 --product-id abc --quantity 1 &

# After ~0.5s, partition inventory
sleep 0.5
./scripts/simulate_partition.sh disconnect inventory-service

# Watch Kafka lag build up
./scripts/simulate_partition.sh status

# Reconnect after 5 seconds
sleep 5
./scripts/simulate_partition.sh connect inventory-service

# Wait for consumer to catch up
sleep 3
./scripts/simulate_partition.sh status
```

**Expected:**
- Order-service continues accepting HTTP requests (orders go into outbox → Kafka)
- Inventory consumer lag increases while partitioned
- On reconnect, consumer drains the lag — all orders eventually processed
- No messages lost (Kafka durability)
- Final stock consistent with total accepted orders

**Your observations:**

---

## Experiment 5 — Kafka broker restart (leader election)

**Goal:** observe Kafka self-healing after broker loss.

```bash
# Start sending orders continuously
python scripts/load_test.py --orders 500 --product-id abc --quantity 1 --concurrency 5 &

# Kill Kafka mid-stream
docker stop kafka

# Observe: order-service outbox relay retries, logs errors
# After a few seconds, restart Kafka
docker start kafka

# Wait for relay to reconnect and flush pending outbox rows
sleep 5
./scripts/simulate_partition.sh status
```

**Expected:**
- While Kafka is down: outbox relay logs `Relay iteration failed, retrying`
- Orders still accepted (DB write succeeds, relay queues up)
- After restart: relay drains the outbox, Kafka lag drains
- No orders permanently lost

**Your observations:**

---

## Experiment 6 — Saga compensation (payment failure)

**Goal:** observe stock release when payment fails.

This requires temporarily breaking payment-service (e.g. stopping postgres-payments):

```bash
docker stop postgres-payments

# Place an order
curl -s -X POST http://localhost:8001/orders \
  -H "Content-Type: application/json" \
  -d '{"product_id": "abc", "quantity": 5}' | jq .

sleep 2

# payment-service logs: payment.failed published
# inventory-service should consume payment.failed and release stock
# (requires wiring the saga compensation listener in inventory consumer)

docker start postgres-payments
```

**Expected:**
- `payment.failed` event published
- Stock for `abc` restored (+5) after compensation
- Order status remains `pending` (no saga coordinator in this implementation)

**Note:** the compensation listener (`_release_stock` in inventory/consumer.py)
is implemented but not yet wired to a Kafka subscription.
This is intentional — wiring it is a suggested extension exercise.

**Your observations:**

---

## Key metrics to record

| Experiment | Metric | Value |
|---|---|---|
| 2 | Orders accepted / rejected | |
| 2 | Final stock | |
| 2 | Any oversell? | |
| 4 | Kafka lag peak | |
| 4 | Catchup time (s) | |
| 5 | Downtime window (s) | |
| 5 | Messages lost | |
