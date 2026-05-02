#!/usr/bin/env bash
# simulate_partition.sh — disconnect / reconnect a container from ecommerce-net
#
# Usage:
#   ./scripts/simulate_partition.sh disconnect inventory-service
#   ./scripts/simulate_partition.sh connect    inventory-service
#
# What to watch while disconnected:
#   - order-service continues accepting orders (AP for HTTP writes)
#   - inventory-service stops consuming from Kafka (no stock deduction)
#   - Kafka retains unconsumed messages — nothing is lost
#   - On reconnect, inventory-service drains its lag and catches up

set -euo pipefail

ACTION=${1:-}
CONTAINER=${2:-}
NETWORK="ecommerce-net"

usage() {
  echo "Usage: $0 <disconnect|connect|status> [container]"
  echo
  echo "Containers: order-service, inventory-service, payment-service, notification-service, kafka"
  exit 1
}

[[ -z "$ACTION" ]] && usage

case "$ACTION" in
  disconnect)
    [[ -z "$CONTAINER" ]] && usage
    echo ">>> Disconnecting $CONTAINER from $NETWORK"
    docker network disconnect "$NETWORK" "$CONTAINER"
    echo ">>> Done. $CONTAINER is now partitioned."
    echo "    Monitor Kafka lag: docker exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --describe --all-groups"
    ;;
  connect)
    [[ -z "$CONTAINER" ]] && usage
    echo ">>> Reconnecting $CONTAINER to $NETWORK"
    docker network connect "$NETWORK" "$CONTAINER"
    echo ">>> Done. $CONTAINER rejoined the network."
    ;;
  status)
    echo "=== Network members ==="
    docker network inspect "$NETWORK" --format '{{range .Containers}}{{.Name}} {{end}}' | tr ' ' '\n' | grep -v '^$' | sort
    echo
    echo "=== Kafka consumer lag ==="
    docker exec kafka kafka-consumer-groups \
      --bootstrap-server localhost:9092 \
      --describe --all-groups 2>/dev/null || echo "(Kafka not reachable)"
    ;;
  *)
    usage
    ;;
esac
