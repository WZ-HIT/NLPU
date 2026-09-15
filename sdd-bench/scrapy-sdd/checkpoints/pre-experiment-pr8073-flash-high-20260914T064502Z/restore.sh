#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly CHECKPOINT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BENCH_ROOT="$(cd -- "${CHECKPOINT_DIR}/../.." && pwd -P)"
readonly TASK_DIR="${BENCH_ROOT}/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
readonly BASELINE_PARENT="${BENCH_ROOT}/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline"
readonly PAYLOAD_DIR="${CHECKPOINT_DIR}/payloads"
readonly PROJECT_NAME="scrapy-sdd-8073-600152fbc76dd5ba-agent"
readonly AGENT_IMAGE="scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate"
readonly AGENT_IMAGE_ID="sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9"
readonly PROXY_IMAGE_ID="sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
readonly LOCK_FILE="/tmp/${PROJECT_NAME}.run.lock"
readonly DEFAULT_SECRET_FILE="/home/wangzuohit/.config/sdd-bench/deepseek-api-key"
readonly -a VARIANTS=(openspec speckit cc-sdd)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'Usage: %s --yes\n' "$0" >&2
  printf 'Default secret: %s\n' "$DEFAULT_SECRET_FILE" >&2
  printf 'Override: DEEPSEEK_API_KEY_FILE=/absolute/secret/path %s --yes\n' "$0" >&2
}

validate_secret_file() {
  local supplied="${DEEPSEEK_API_KEY_FILE:-$DEFAULT_SECRET_FILE}"
  local canonical owner mode

  [[ "$supplied" == /* ]] || die "DEEPSEEK_API_KEY_FILE must be an absolute path"
  [[ ! -L "$supplied" ]] || die "DEEPSEEK_API_KEY_FILE must not be a symbolic link"
  canonical="$(realpath -e -- "$supplied")" || die "secret file does not exist"
  [[ -f "$canonical" && -r "$canonical" && -s "$canonical" ]] || \
    die "secret file must be a readable, non-empty regular file"
  case "$canonical" in
    "$BENCH_ROOT"|"$BENCH_ROOT"/*) die "secret file must be outside the benchmark Git tree" ;;
  esac
  owner="$(stat -c '%u' -- "$canonical")"
  [[ "$owner" == "$(id -u)" ]] || die "secret file must be owned by the invoking user"
  mode="$(stat -c '%a' -- "$canonical")"
  (( (8#$mode & 8#077) == 0 )) || die "secret file must not grant group or other permissions"
  SECRET_FILE="$canonical"
}

[[ "${1:-}" == "--yes" && "$#" -eq 1 ]] || {
  usage
  die "explicit --yes confirmation is required"
}

for command_name in docker flock id realpath sha256sum stat tar; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: ${command_name}"
done

"${CHECKPOINT_DIR}/verify.sh"
flock -n "$LOCK_FILE" true || die "a formal Agent run currently holds ${LOCK_FILE}"
validate_secret_file

if ! docker image inspect "$AGENT_IMAGE_ID" >/dev/null 2>&1 || \
   ! docker image inspect "$PROXY_IMAGE_ID" >/dev/null 2>&1; then
  printf 'loading_checkpoint_images=true\n'
  docker image load -i "${PAYLOAD_DIR}/deployment-images.tar.gz"
fi

readonly RESTORE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP_DIR="${CHECKPOINT_DIR}/restore-backups/${RESTORE_ID}"
mkdir -p -- "${BACKUP_DIR}/repositories" "${BACKUP_DIR}/home-volumes"

backup_volume() {
  local variant="$1"
  local volume="${PROJECT_NAME}_${variant}-home"
  docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --user 1007:1007 \
    -v "${volume}:/source:ro" -v "${BACKUP_DIR}/home-volumes:/backup:rw" \
    "$AGENT_IMAGE" /bin/sh -c "cd /source && tar -czf /backup/${variant}-home.tar.gz ."
}

restore_volume() {
  local variant="$1"
  local volume="${PROJECT_NAME}_${variant}-home"
  # Compose creates root-owned bind-target placeholders in HOME volumes.
  # Use a networkless root helper with only the capabilities needed to replace them.
  docker run --rm --network none --cap-drop ALL \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --security-opt no-new-privileges:true --user 0:0 \
    -v "${volume}:/target:rw" -v "${PAYLOAD_DIR}:/payloads:ro" \
    "$AGENT_IMAGE" /bin/sh -c \
      "find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar --same-owner --same-permissions -xzf /payloads/${variant}-home.tar.gz -C /target"
}

printf 'restore_backup=%s\n' "$BACKUP_DIR"

# Back up current deployment files first. The checkpoint configuration is then
# restored before Compose is invoked, so a partially edited current Compose or
# launcher cannot prevent rollback.
tar -czf "${BACKUP_DIR}/deployment-config.tar.gz" -C "$BENCH_ROOT" \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/Dockerfile.agent \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/apparmor-codex-bwrap-0.12.0.draft \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.agent.yaml \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/run-agent.sh \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/run-experiment.sh \
  tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json \
  environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/config.toml \
  environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-v4-pro.config.toml \
  environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-flash.config.toml \
  environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-v4-pro/models.json \
  environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json \
  environments/network/haproxy-3.2.23/deepseek-tls-egress.cfg
tar --same-permissions -xzf "${PAYLOAD_DIR}/deployment-config.tar.gz" -C "$BENCH_ROOT"

# Compose interpolation needs a path for `down`, but this operation never opens
# the secret. Named HOME volumes are preserved by omitting `--volumes`.
DEEPSEEK_API_KEY_FILE=/dev/null docker compose \
  --project-directory "$TASK_DIR" -f "${TASK_DIR}/compose.agent.yaml" down

# Preserve the live state before replacing it. The repositories are moved, not
# deleted, so a failed restore can be reversed manually from BACKUP_DIR.
mv -- "${BASELINE_PARENT}/scrapy" "${BACKUP_DIR}/repositories/baseline-scrapy"
for variant in "${VARIANTS[@]}"; do
  mv -- "${TASK_DIR}/runs/${variant}/scrapy" \
    "${BACKUP_DIR}/repositories/${variant}-scrapy"
  backup_volume "$variant"
done

tar --same-permissions -xzf "${PAYLOAD_DIR}/baseline-repo.tar.gz" -C "$BASELINE_PARENT"
for variant in "${VARIANTS[@]}"; do
  tar --same-permissions -xzf "${PAYLOAD_DIR}/${variant}-repo.tar.gz" -C "${TASK_DIR}/runs/${variant}"
  restore_volume "$variant"
done

DEEPSEEK_API_KEY_FILE="$SECRET_FILE" docker compose \
  --project-directory "$TASK_DIR" -f "${TASK_DIR}/compose.agent.yaml" \
  up -d --wait --wait-timeout 120
DEEPSEEK_API_KEY_FILE="$SECRET_FILE" "${TASK_DIR}/run-agent.sh" verify

printf 'checkpoint_restore=PASS backup=%s\n' "$BACKUP_DIR"
