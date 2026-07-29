#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEPLOY_USER="${DEPLOY_USER:-root}"
DEPLOY_PORT="${DEPLOY_PORT:-22}"
DEPLOY_PATH="${DEPLOY_PATH:-/home/${DEPLOY_USER}/jingdu}"
SSH_KEY="${SSH_KEY:-}"
DB_SNAPSHOT="${DB_SNAPSHOT:-}"
KNOWN_HOSTS_FILE="${KNOWN_HOSTS_FILE:-${PROJECT_ROOT}/.deploy-keys/known_hosts}"

if [[ -z "${DEPLOY_HOST:-}" ]]; then
  echo "DEPLOY_HOST is required"
  exit 1
fi

if [[ ! -f "${PROJECT_ROOT}/.env.production" ]]; then
  echo "Missing ${PROJECT_ROOT}/.env.production"
  echo "Create it from .env.production.example before deploying."
  exit 1
fi

SSH_TARGET="${DEPLOY_USER}@${DEPLOY_HOST}"
SSH_ARGS=(
  -p "${DEPLOY_PORT}"
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${KNOWN_HOSTS_FILE}"
)
SCP_ARGS=(
  -P "${DEPLOY_PORT}"
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${KNOWN_HOSTS_FILE}"
)
RSYNC_SSH="ssh -p ${DEPLOY_PORT} -o StrictHostKeyChecking=yes -o UserKnownHostsFile=${KNOWN_HOSTS_FILE}"

if [[ -n "${SSH_KEY}" ]]; then
  SSH_ARGS+=(-i "${SSH_KEY}")
  SCP_ARGS+=(-i "${SSH_KEY}")
  RSYNC_SSH+=" -i ${SSH_KEY}"
fi

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" "mkdir -p '${DEPLOY_PATH}/backend/data' '${DEPLOY_PATH}/backend/downloads'"

rsync -az --delete \
  -e "${RSYNC_SSH}" \
  --exclude '.git/' \
  --exclude '.deploy-keys/' \
  --exclude '.env.production' \
  --exclude 'backend/.env' \
  --exclude 'backend/.venv/' \
  --exclude 'backend/__pycache__/' \
  --exclude 'backend/data/' \
  --exclude 'backend/downloads/' \
  --exclude 'frontend/node_modules/' \
  --exclude 'frontend/dist/' \
  --exclude 'llm_repair/' \
  --exclude 'scraped_codefather_docs/' \
  --exclude 'tmp/' \
  "${PROJECT_ROOT}/" "${SSH_TARGET}:${DEPLOY_PATH}/"

scp "${SCP_ARGS[@]}" \
  "${PROJECT_ROOT}/.env.production" \
  "${SSH_TARGET}:${DEPLOY_PATH}/.env.production"

if [[ -n "${DB_SNAPSHOT}" ]]; then
  scp "${SCP_ARGS[@]}" \
    "${DB_SNAPSHOT}" \
    "${SSH_TARGET}:${DEPLOY_PATH}/backend/data/app.db"
  ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
    "chmod 600 '${DEPLOY_PATH}/backend/data/app.db'"
fi

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
  "chmod 600 '${DEPLOY_PATH}/.env.production'"

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
  "sudo docker compose --project-directory '${DEPLOY_PATH}' --env-file '${DEPLOY_PATH}/.env.production' up -d --build --remove-orphans"

ssh "${SSH_ARGS[@]}" "${SSH_TARGET}" \
  "sudo docker compose --project-directory '${DEPLOY_PATH}' --env-file '${DEPLOY_PATH}/.env.production' ps"
