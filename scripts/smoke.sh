#!/usr/bin/env bash
# Start the process, wait for /healthz, then exit.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "${ROOT}"

if command -v civic-alert-relay >/dev/null 2>&1; then
  RUN=(civic-alert-relay)
elif [[ -x "${ROOT}/.venv/bin/civic-alert-relay" ]]; then
  RUN=("${ROOT}/.venv/bin/civic-alert-relay")
else
  RUN=(python3 -m civic_alert_relay)
fi

WORKDIR="$(mktemp -d)"
trap 'if [[ -n "${PID:-}" ]]; then kill "${PID}" 2>/dev/null || true; wait "${PID}" 2>/dev/null || true; fi; rm -rf "${WORKDIR}"' EXIT

PORT="${CAR_SMOKE_PORT:-18080}"
export CAR_HOST="127.0.0.1"
export CAR_PORT="${PORT}"
export CAR_LOG_LEVEL="info"
export CAR_SEEN_IDS_PATH="${WORKDIR}/seen.json"

"${RUN[@]}" >"${WORKDIR}/relay.log" 2>&1 &
PID=$!

for _ in $(seq 1 50); do
  if curl -fsS "http://127.0.0.1:${PORT}/healthz" -o "${WORKDIR}/health.json"; then
    if grep -q '"status":"ok"' "${WORKDIR}/health.json"; then
      echo "smoke: /healthz ok"
      cat "${WORKDIR}/health.json"
      echo
      exit 0
    fi
    echo "smoke: unexpected body:" >&2
    cat "${WORKDIR}/health.json" >&2
    exit 1
  fi
  if ! kill -0 "${PID}" 2>/dev/null; then
    echo "smoke: process exited early" >&2
    cat "${WORKDIR}/relay.log" >&2
    exit 1
  fi
  sleep 0.1
done

echo "smoke: timed out waiting for /healthz" >&2
cat "${WORKDIR}/relay.log" >&2
exit 1
