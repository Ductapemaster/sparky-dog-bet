#!/usr/bin/env bash
#
# Canonical dev loop for this app. Single server (dev == prod): app code is baked
# into the Docker image at build time, so every change must be rebuilt to go live.
# This script makes "rebuild → verify healthy → test" one command so it can't be
# forgotten.
#
#   ./dev.sh check     build + deploy + smoke + full e2e suite   ← run before "done"
#   ./dev.sh up        build + deploy + wait until healthy
#   ./dev.sh lint      fast syntax gate (no deploy)
#   ./dev.sh smoke     HTTP 200 check on key routes
#   ./dev.sh test ...  run the e2e harness (pass-through args, e.g. `test kiosk`)
#   ./dev.sh logs      follow container logs
#
# Typical feature flow:
#   git switch -c feature/x   →   edit   →   ./dev.sh check   →   repeat   →   commit
#
# Porting to a new app: edit the CONFIG block below. The harness in TEST_CMD is
# app-specific; everything else here is generic.
set -euo pipefail
cd "$(dirname "$0")"

# ── CONFIG (edit per app) ─────────────────────────────────────────────
PORT=9999                                   # host port the app is published on
HEALTH_PATH="/"                             # path that should return 200 when up
SMOKE_PATHS=("/" "/about" "/bet" "/leaderboard")
LINT_PY=(app/*.py wsgi.py)                  # python files to syntax-check
LINT_JS=(app/static/*.js)                   # js files to syntax-check
TEST_CMD="tests/kiosk-visual/run.sh"        # e2e harness (empty = skip e2e)
# ──────────────────────────────────────────────────────────────────────

BASE="http://localhost:${PORT}"
say() { printf '\n\033[1m── %s ──\033[0m\n' "$1"; }

lint() {
  say "lint"
  if command -v python3 >/dev/null; then
    python3 -m py_compile "${LINT_PY[@]}" && echo "  ✓ python parses"
  fi
  if command -v node >/dev/null; then
    for f in "${LINT_JS[@]}"; do [ -e "$f" ] && node --check "$f" && echo "  ✓ $f"; done
  fi
}

build() { say "build + deploy"; docker compose up -d --build; }

wait_healthy() {
  say "health"
  for _ in $(seq 1 30); do
    if curl -fsS -o /dev/null "${BASE}${HEALTH_PATH}" 2>/dev/null; then echo "  ✓ ${BASE}${HEALTH_PATH}"; return 0; fi
    sleep 1
  done
  echo "  ✗ app did not become healthy" >&2
  docker compose logs --tail 30
  return 1
}

smoke() {
  say "smoke"
  local fail=0
  for p in "${SMOKE_PATHS[@]}"; do
    local code; code=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}${p}")
    if [ "$code" = "200" ]; then echo "  ✓ $p"; else echo "  ✗ $p ($code)"; fail=1; fi
  done
  return $fail
}

e2e() {
  say "e2e"
  if [ -z "$TEST_CMD" ]; then echo "  (no TEST_CMD; skipping)"; return 0; fi
  "./$TEST_CMD" "$@"
}

case "${1:-check}" in
  lint)  lint ;;
  up)    build; wait_healthy ;;
  smoke) smoke ;;
  test)  shift; e2e "$@" ;;
  logs)  docker compose logs -f --tail 50 ;;
  check) lint; build; wait_healthy; smoke; e2e; printf '\n\033[1;32m✓ check passed\033[0m\n' ;;
  *) echo "usage: ./dev.sh {check|up|lint|smoke|test|logs}"; exit 2 ;;
esac
