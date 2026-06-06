#!/usr/bin/env bash
# Comprehensive visual + functional harness for the Sparky bet site.
#
# Drives the real UI in a Dockerized Chromium (Playwright) on the host network,
# so it reaches the running app — no local Node/Chromium needed. Covers:
#   kiosk   sizing (iPad Pro 12.9") + inline place-bet/edit + auto/manual logout + carousel
#   mobile  the same flows in vertical iPhone portrait
#   states  admin lock/unlock + reveal/hide, and the kiosk's view of each state
#
# kiosk/mobile run against the LIVE app (localhost:9999) using a throwaway guest
# ("Harness Tester") created and deleted around the run. `states` toggles GLOBAL
# config (lock/reveal), so it spins up an ISOLATED instance on :9998 with a fresh
# DB and tears it down — it never touches the live game.
#
# Usage:
#   ./run.sh                    # kiosk + mobile + desktop + states
#   ./run.sh kiosk|mobile|desktop|states
#   SAFARI_TOOLBAR=60 ./run.sh  # model a taller iPad address bar
#
# Screenshots land in ./shots/. Exits non-zero if any harness fails.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$DIR/shots"

WHICH="${1:-all}"
BASE_URL="${BASE_URL:-http://localhost:9999}"
APP_CONTAINER="${APP_CONTAINER:-sparky-dog-bet-web-1}"
TEST_IMAGE="${TEST_IMAGE:-sparky-dog-bet-web}"
TEST_CONTAINER="sparky-harness-isolated"
TEST_PORT=9998
PW_IMAGE="${PW_IMAGE:-mcr.microsoft.com/playwright:v1.48.0-jammy}"
NAME="Harness Tester"
PHONE="9999"

cleanup() {
  docker exec "$APP_CONTAINER" python -c "
from app import db
for g in db.get_all_guests():
    if g['name'] == '$NAME': db.delete_guest(g['id'])
" >/dev/null 2>&1 || true
  docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

setup_guest() {
  docker exec "$APP_CONTAINER" python -c "
from app import db
for g in db.get_all_guests():
    if g['name'] == '$NAME': db.delete_guest(g['id'])
db.add_guest('$NAME', '$PHONE')
"
}
bet_of() { docker exec "$APP_CONTAINER" python -c "from app import db; print(db.get_bet('$NAME'))"; }

# Run a Playwright entry script in the Docker Chromium against $1 (base url).
run_harness() {
  local base="$1" entry="$2"
  docker run --rm --network host \
    -e BASE_URL="$base" \
    -e SAFARI_TOOLBAR="${SAFARI_TOOLBAR:-90}" \
    -e OUT_DIR=/work/shots -e ADMIN_PW=sparky \
    -e GUEST_NAME="$NAME" -e GUEST_PHONE="$PHONE" \
    -e PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    -e PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    -v "$DIR":/work -w /work \
    "$PW_IMAGE" \
    bash -lc 'npm install --no-save playwright@1.48.0 >/tmp/npm.log 2>&1 && node '"$entry"
}

# Stand up an isolated instance (fresh DB) and seed guests + bets + results.
start_isolated() {
  docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
  docker run -d --name "$TEST_CONTAINER" -p "${TEST_PORT}:8000" \
    -e SECRET_KEY=harness "$TEST_IMAGE" >/dev/null
  for _ in $(seq 1 20); do
    curl -fsS -o /dev/null "http://localhost:${TEST_PORT}/" 2>/dev/null && break; sleep 1
  done
  docker exec -i "$TEST_CONTAINER" python - <<'PY'
from app import db
seed = [('Test Alice', '1111', [{'breed': 'Boxer', 'percentage': 60}, {'breed': 'Labrador Retriever', 'percentage': 40}]),
        ('Test Bob',   '2222', [{'breed': 'Boxer', 'percentage': 30}, {'breed': 'Labrador Retriever', 'percentage': 70}])]
for n, p, bet in seed:
    db.add_guest(n, p); db.submit_bet(n, p, bet)
db.add_guest('Test Carol', '3333')
for breed, pct in [('Boxer', 55), ('Labrador Retriever', 30), ('German Shepherd Dog', 15)]:
    db.upsert_actual_result(breed, pct)
PY
}

rc=0
if [ "$WHICH" = "kiosk" ] || [ "$WHICH" = "all" ]; then
  echo "=== KIOSK ==="; setup_guest
  run_harness "$BASE_URL" kiosk.mjs || rc=1
  echo "  final stored bet: $(bet_of)   (expect Boxer 70 / Labrador Retriever 30)"
fi
if [ "$WHICH" = "mobile" ] || [ "$WHICH" = "all" ]; then
  echo "=== MOBILE ==="; setup_guest
  run_harness "$BASE_URL" mobile.mjs || rc=1
  echo "  final stored bet: $(bet_of)   (expect Boxer 80 / Labrador Retriever 20)"
fi
if [ "$WHICH" = "desktop" ] || [ "$WHICH" = "all" ]; then
  echo "=== DESKTOP (non-kiosk, two-column) ==="; setup_guest
  run_harness "$BASE_URL" desktop.mjs || rc=1
  echo "  final stored bet: $(bet_of)   (expect Boxer 75 / Labrador Retriever 25)"
fi
if [ "$WHICH" = "states" ] || [ "$WHICH" = "all" ]; then
  echo "=== STATES (isolated instance :$TEST_PORT) ==="; start_isolated
  run_harness "http://localhost:${TEST_PORT}" states.mjs || rc=1
  docker rm -f "$TEST_CONTAINER" >/dev/null 2>&1 || true
fi

exit $rc
