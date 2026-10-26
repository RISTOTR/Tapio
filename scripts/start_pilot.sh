#!/usr/bin/env bash
# Start the local dependency before serving the human-supervised pilot.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if ! colima status >/dev/null 2>&1; then
  colima start
fi
docker-compose up -d --wait postgres
export TAPIO_PILOT_MODE=true
.venv/bin/python -m tapio.pilot.health
exec .venv/bin/uvicorn tapio.pilot.api:app --host 127.0.0.1 --port 8011
