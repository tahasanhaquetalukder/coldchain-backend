#!/usr/bin/env bash
# Host tests for the fridge node's logic. Needs g++ and python, nothing else - no Arduino IDE,
# no ESP32 core, no board.
#
#   bash firmware/tests/run_tests.sh
#
# Point it at a running API to also prove that a body signed by the node's own signer is accepted:
#
#   API_BASE=http://127.0.0.1:8000 bash firmware/tests/run_tests.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python}
CXX=${CXX:-g++}

"$PY" gen_vectors.py vectors.txt
mkdir -p build
"$CXX" -std=c++11 -Wall -Wextra -I../coldchain_node -o build/test_core test_core.cpp
./build/test_core vectors.txt

if [ -n "${API_BASE:-}" ]; then
  KEY="${HMAC_SECRET_KEY:-super-secret-hackathon-key}"
  NONCE=$("$PY" -c "import uuid;print(uuid.uuid4().hex)")
  TS=$("$PY" -c "import time;print(int(time.time()))")
  BODY=$(./build/test_core --payload "$KEY" "${DEVICE_ID:-fridge-1}" "$NONCE" 5.4 "$TS" 97 0 1 0 0)
  CODE=$(curl -sS -o node_reply.json -w '%{http_code}' -X POST "$API_BASE/api/sensor" \
         -H 'Content-Type: application/json' -d "$BODY")
  echo "live ingest -> HTTP $CODE $(cat node_reply.json)"
  if [ "$CODE" != "201" ]; then
    echo "FAIL: the API rejected a body signed by the node's own signer"
    exit 1
  fi
fi
