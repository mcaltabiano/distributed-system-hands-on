#!/usr/bin/env bash
# cleanup.sh — reset all stateful data to a clean starting point
#
# Truncates every application table across the three PostgreSQL databases,
# restores inventory stock to seed values, and flushes Redis notification keys.
# Kafka topic offsets are intentionally left intact — they are append-only and
# the consumer group offsets reset naturally on service restart.
#
# Usage:
#   ./scripts/cleanup.sh

set -euo pipefail

psql_orders()    { docker exec postgres-orders    psql -U app -d orders    -c "$1" -q; }
psql_inventory() { docker exec postgres-inventory psql -U app -d inventory -c "$1" -q; }
psql_payments()  { docker exec postgres-payments  psql -U app -d payments  -c "$1" -q; }

echo "=== Cleaning orders DB ==="
psql_orders "TRUNCATE TABLE outbox, orders RESTART IDENTITY CASCADE;"

echo "=== Cleaning inventory DB ==="
psql_inventory "TRUNCATE TABLE reservations RESTART IDENTITY CASCADE;"
psql_inventory "UPDATE products SET stock = 50  WHERE id = 'abc';"
psql_inventory "UPDATE products SET stock = 200 WHERE id = 'xyz';"

echo "=== Cleaning payments DB ==="
psql_payments "TRUNCATE TABLE payments RESTART IDENTITY CASCADE;"

echo "=== Flushing Redis notification keys ==="
docker exec redis redis-cli --scan --pattern 'notif:sent:*' \
  | xargs -r docker exec -i redis redis-cli DEL > /dev/null

echo "=== Done. All tables cleared, stock restored to seed values. ==="
