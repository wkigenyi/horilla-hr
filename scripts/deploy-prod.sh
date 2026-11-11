#!/usr/bin/env bash
# Production deploy on a VM that already has a git clone + .env.
# Intended for GitHub Actions SSH (and manual: DEPLOY_SHA=<sha> ./scripts/deploy-prod.sh).
#
# Expects to run from the repository root (or set DEPLOY_PATH).
# Does not touch .env or docker-compose.override.yml.

set -euo pipefail

ROOT="${DEPLOY_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

log() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ -f .env ]] || die "Missing .env in $ROOT — copy .env.dist and set production secrets first."
command -v docker >/dev/null || die "docker not found"
command -v make >/dev/null || die "make not found"
docker compose version >/dev/null 2>&1 || die "docker compose (V2) not found"

if [[ -n "${DEPLOY_SHA:-}" ]]; then
  log "Syncing git to $DEPLOY_SHA"
  git fetch --prune origin
  # Detached or branch tip both fine; CI passes the exact push SHA.
  git reset --hard "$DEPLOY_SHA"
elif [[ -n "${DEPLOY_BRANCH:-}" ]]; then
  log "Syncing git to origin/${DEPLOY_BRANCH}"
  git fetch --prune origin
  git checkout -B "$DEPLOY_BRANCH" "origin/${DEPLOY_BRANCH}"
  git reset --hard "origin/${DEPLOY_BRANCH}"
fi

log "HEAD=$(git rev-parse HEAD) ($(git rev-parse --short HEAD))"

log "Building and starting production stack (make prod)"
make prod

compose=(docker compose -f docker-compose.yml -f docker-compose.prod.yml)
if [[ -f docker-compose.override.yml ]]; then
  compose+=(-f docker-compose.override.yml)
fi

web_id="$("${compose[@]}" ps -q web)"
[[ -n "$web_id" ]] || die "web container not found after make prod"

log "Waiting for web to become healthy (up to 10 minutes)"
deadline=$((SECONDS + 600))
while true; do
  status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$web_id" 2>/dev/null || true)"
  case "$status" in
    healthy)
      log "web is healthy"
      break
      ;;
    unhealthy)
      die "web reported unhealthy — check: ${compose[*]} logs web"
      ;;
  esac
  if (( SECONDS >= deadline )); then
    die "timed out waiting for web health (last status=${status:-unknown})"
  fi
  sleep 5
  # Recreate id if compose replaced the container during start_period
  web_id="$("${compose[@]}" ps -q web)"
  [[ -n "$web_id" ]] || die "web container disappeared while waiting"
done

"${compose[@]}" ps
log "Deploy finished successfully"
