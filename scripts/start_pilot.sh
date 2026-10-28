#!/usr/bin/env bash
# Start the local dependency before serving the human-supervised pilot.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
# Retain the explicitly activated local profile across application restarts.
# The adapter still requires its matching frozen-batch/implementation seal.
if [[ -f .private/confirmation_profile ]] && [[ "$(< .private/confirmation_profile)" == "GENERAL_V1" ]]; then
  export TAPIO_CONFIRMATION_BATCH="${TAPIO_CONFIRMATION_BATCH:-GENERAL_V1}"
  export TAPIO_CONFIRMATION_WRITES="${TAPIO_CONFIRMATION_WRITES:-true}"
fi
if ! colima status >/dev/null 2>&1; then
  colima start
fi
docker-compose up -d --wait postgres
export TAPIO_PILOT_MODE=true
.venv/bin/python -m tapio.pilot.health
exec .venv/bin/uvicorn tapio.pilot.api:app --host 127.0.0.1 --port 8011
