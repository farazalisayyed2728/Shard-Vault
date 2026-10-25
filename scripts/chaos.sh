#!/usr/bin/env bash
set -euo pipefail

compose_file="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/docker-compose.yml"

echo "Initiating chaos: stopping node2..."
docker compose -f "$compose_file" stop node2
echo "Node 2 is offline. Check the dashboard for its status."
echo "Waiting 30 seconds for the health check task..."
sleep 30
echo "Restoring node2..."
docker compose -f "$compose_file" start node2
echo "Node 2 is back online. Celery will update its status."
