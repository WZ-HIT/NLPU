#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly TASK_ID="scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
readonly PROJECT_NAME="scrapy-sdd-8073-600152fbc76dd5ba-agent"
readonly AGENT_IMAGE="scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate"
readonly AGENT_IMAGE_ID="sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9"
readonly PROXY_IMAGE="haproxy@sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
readonly PROXY_IMAGE_ID="sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
readonly PROFILE_NAME="deepseek-flash"
readonly RUN_TIMEOUT_SECONDS=2700
readonly KILL_AFTER_SECONDS=30
readonly BASE_SHA="11079cb1c85b9e75a39a7269943c69d1a975d485"
readonly PARENT_APPARMOR_PROFILE="scrapy_sdd_codex_parent_11079cb1c85b"

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BENCH_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/compose.agent.yaml"
readonly AUDIT_RUN_ROOT="${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/agent-runs"
readonly LOCK_FILE="/tmp/${PROJECT_NAME}.run.lock"

readonly COMMON_CONFIG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/config.toml"
readonly PROFILE_CONFIG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-flash.config.toml"
readonly MODEL_CATALOG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json"
readonly PROXY_CONFIG="${BENCH_ROOT}/environments/network/haproxy-3.2.23/deepseek-tls-egress.cfg"
readonly SECCOMP_PROFILE="${SCRIPT_DIR}/seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json"
readonly APPARMOR_PROFILE="${SCRIPT_DIR}/apparmor-codex-bwrap-0.12.0.draft"
readonly INITIALIZATION_AUDIT_ROOT="${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits"

readonly EXPECTED_COMPOSE_SHA256="11789f438228df24976e397a6b446edbe51736ba6a9f3288718bdcf40b4f2904"
readonly EXPECTED_RENDERED_COMPOSE_SHA256="77a7414b9be70c21de92838a17b91701a3fb0ee3860d650759761d929e985714"
readonly EXPECTED_COMMON_CONFIG_SHA256="b1c8c6d896b4c7e56adb864487f6d667cd682e21ccf1d0989c5646abc981851f"
readonly EXPECTED_PROFILE_CONFIG_SHA256="2e594da8abb241ef9c54cc376956a198371d305db4252d21341bd8d4fa1dd029"
readonly EXPECTED_MODEL_CATALOG_SHA256="4240127a851f7582bb4f92b9fe3b258f18393d560446e84430e5f90f473db9a1"
readonly EXPECTED_PROXY_CONFIG_SHA256="73ab4db6da9857ecf8c8c71b4d00bec70dfba321b0ddf785d2b6aee016b4a6b6"
readonly EXPECTED_SECCOMP_SHA256="1a25ca5c611f8acd56d436b6bf61cce4dd4f9115291e22929152b50a9915ac25"
readonly EXPECTED_APPARMOR_SHA256="c86d37481ca8c4eb44cc6432f4a8de4c65224f4fe9945ebfb772bf18b13d0b48"
readonly EXPECTED_OPENSPEC_GENERATED_MANIFEST_SHA256="70168a45d79ce6cd6d686c280476e3fbaf57179cc239cda700b49cac298c7141"
readonly EXPECTED_SPECKIT_GENERATED_MANIFEST_SHA256="404c4d70c695f254aa9bd372bf0f0b508ce53c6f3ab4f8f8446931eda6c0ce34"
readonly EXPECTED_CC_SDD_GENERATED_MANIFEST_SHA256="3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca"

readonly -a TARGET_SUBNETS=("172.28.11.0/24" "172.28.12.0/24" "172.28.13.0/24")
readonly -a AGENT_SERVICES=("openspec-agent" "speckit-agent" "cc-sdd-agent")
readonly -a PROXY_SERVICES=("openspec-egress" "speckit-egress" "cc-sdd-egress")
readonly -a VARIANTS=("openspec" "speckit" "cc-sdd")
readonly -a OLD_BASELINE_CONTAINERS=(
  "scrapy-sdd-8073-600152fbc76dd5ba-openspec"
  "scrapy-sdd-8073-600152fbc76dd5ba-speckit"
  "scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd"
)

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '%s\n' "$*" >&2
}

usage() {
  cat >&2 <<'EOF'
Usage:
  run-agent.sh verify-static
  run-agent.sh preflight
  run-agent.sh up
  run-agent.sh verify
  run-agent.sh status
  run-agent.sh run <openspec|speckit|cc-sdd> <prompt-file> [run-id]

Required for every command except verify-static and help:
  DEEPSEEK_API_KEY_FILE=/absolute/path/outside/the/benchmark/git/tree

The run command is sequential, fixes the Codex profile and execution policy, and
writes JSONL plus stderr to the task's Log audit directory.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

assert_sha256() {
  local path="$1"
  local expected="$2"
  local label="$3"
  local actual

  [[ -f "$path" ]] || die "missing ${label}: ${path}"
  actual="$(sha256sum -- "$path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || die "${label} SHA256 mismatch: expected ${expected}, got ${actual}"
}

compose_with_secret() {
  DEEPSEEK_API_KEY_FILE="$SECRET_FILE" docker compose --project-directory "$SCRIPT_DIR" -f "$COMPOSE_FILE" "$@"
}

compose_without_secret() {
  DEEPSEEK_API_KEY_FILE=/dev/null docker compose --project-directory "$SCRIPT_DIR" -f "$COMPOSE_FILE" "$@"
}

validate_secret_file() {
  local supplied="${DEEPSEEK_API_KEY_FILE:-}"
  local canonical owner mode

  [[ -n "$supplied" ]] || die "DEEPSEEK_API_KEY_FILE is required"
  [[ "$supplied" == /* ]] || die "DEEPSEEK_API_KEY_FILE must be an absolute path"
  [[ ! -L "$supplied" ]] || die "DEEPSEEK_API_KEY_FILE must not be a symbolic link"
  canonical="$(realpath -e -- "$supplied")" || die "secret file does not exist"
  [[ -f "$canonical" && -r "$canonical" && -s "$canonical" ]] || die "secret file must be a readable, non-empty regular file"

  case "$canonical" in
    "$BENCH_ROOT"|"$BENCH_ROOT"/*)
      die "secret file must be outside the benchmark Git tree"
      ;;
  esac

  owner="$(stat -c '%u' -- "$canonical")"
  [[ "$owner" == "$(id -u)" ]] || die "secret file must be owned by the invoking user"
  mode="$(stat -c '%a' -- "$canonical")"
  (( (8#$mode & 8#077) == 0 )) || die "secret file must not grant group or other permissions"

  SECRET_FILE="$canonical"
  export SECRET_FILE
  info "secret_file=validated"
}

verify_files_and_images() {
  local actual rendered

  assert_sha256 "$COMPOSE_FILE" "$EXPECTED_COMPOSE_SHA256" "deployment Compose"
  assert_sha256 "$COMMON_CONFIG" "$EXPECTED_COMMON_CONFIG_SHA256" "common Codex config"
  assert_sha256 "$PROFILE_CONFIG" "$EXPECTED_PROFILE_CONFIG_SHA256" "provider profile"
  assert_sha256 "$MODEL_CATALOG" "$EXPECTED_MODEL_CATALOG_SHA256" "model catalog"
  assert_sha256 "$PROXY_CONFIG" "$EXPECTED_PROXY_CONFIG_SHA256" "HAProxy config"
  assert_sha256 "$SECCOMP_PROFILE" "$EXPECTED_SECCOMP_SHA256" "Seccomp profile"
  assert_sha256 "$APPARMOR_PROFILE" "$EXPECTED_APPARMOR_SHA256" "AppArmor profile source"

  compose_without_secret config --quiet
  rendered="$(compose_without_secret config --format json | sha256sum | awk '{print $1}')"
  [[ "$rendered" == "$EXPECTED_RENDERED_COMPOSE_SHA256" ]] || die "normalized Compose SHA256 mismatch"

  actual="$(docker image inspect --format '{{.Id}}' "$AGENT_IMAGE")"
  [[ "$actual" == "$AGENT_IMAGE_ID" ]] || die "Agent image ID mismatch: ${actual}"
  actual="$(docker image inspect --format '{{.Id}}' "$PROXY_IMAGE")"
  [[ "$actual" == "$PROXY_IMAGE_ID" ]] || die "proxy image ID mismatch: ${actual}"

  aa-status --enabled >/dev/null 2>&1 || die "AppArmor is not enabled"
  docker info --format '{{json .SecurityOptions}}' | grep -q 'apparmor' || die "Docker does not report AppArmor support"
  docker info --format '{{json .SecurityOptions}}' | grep -q 'seccomp' || die "Docker does not report Seccomp support"
}

assert_subnets_available() {
  local networks_json
  local -a network_ids=()

  mapfile -t network_ids < <(docker network ls -q)
  if ((${#network_ids[@]} == 0)); then
    networks_json='[]'
  else
    networks_json="$(docker network inspect "${network_ids[@]}")"
  fi

  NETWORKS_JSON="$networks_json" python3 - "${TARGET_SUBNETS[@]}" <<'PY'
import ipaddress
import json
import os
import sys

targets = [ipaddress.ip_network(value) for value in sys.argv[1:]]
collisions = []
for network in json.loads(os.environ["NETWORKS_JSON"]):
    for config in network.get("IPAM", {}).get("Config") or []:
        value = config.get("Subnet")
        if not value:
            continue
        try:
            current = ipaddress.ip_network(value)
        except ValueError:
            continue
        for target in targets:
            if current.version == target.version and current.overlaps(target):
                collisions.append(f"{network.get('Name', '<unknown>')}:{current} overlaps {target}")

if collisions:
    print("ERROR: deployment subnet collision:", file=sys.stderr)
    print("\n".join(collisions), file=sys.stderr)
    raise SystemExit(1)
PY
}

assert_project_absent() {
  local value

  value="$(docker ps -aq --filter "label=com.docker.compose.project=${PROJECT_NAME}")"
  [[ -z "$value" ]] || die "deployment project already has containers"
  value="$(docker network ls -q --filter "label=com.docker.compose.project=${PROJECT_NAME}")"
  [[ -z "$value" ]] || die "deployment project already has networks"
  value="$(docker volume ls -q --filter "label=com.docker.compose.project=${PROJECT_NAME}")"
  [[ -z "$value" ]] || die "deployment project already has volumes"
}

assert_old_baseline_stopped() {
  local name running

  for name in "${OLD_BASELINE_CONTAINERS[@]}"; do
    running="$(docker inspect --format '{{.State.Running}}' "$name" 2>/dev/null || true)"
    [[ "$running" != "true" ]] || die "old baseline container is still running: ${name}"
  done
}

expected_branch() {
  case "$1" in
    openspec) printf '%s\n' 'experiment/openspec' ;;
    speckit) printf '%s\n' 'experiment/speckit' ;;
    cc-sdd) printf '%s\n' 'experiment/cc-sdd' ;;
    *) die "unknown variant: $1" ;;
  esac
}

verify_repository_identity() {
  local variant="$1"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
  local head branch remotes

  [[ -d "${repo}/.git" ]] || die "missing Git repository for ${variant}: ${repo}"
  head="$(git -C "$repo" rev-parse HEAD)"
  [[ "$head" == "$BASE_SHA" ]] || die "${variant} HEAD mismatch: ${head}"
  branch="$(git -C "$repo" branch --show-current)"
  [[ "$branch" == "$(expected_branch "$variant")" ]] || die "${variant} branch mismatch: ${branch}"
  remotes="$(git -C "$repo" remote)"
  [[ -z "$remotes" ]] || die "${variant} repository has a Git remote"
}

generated_manifest() {
  case "$1" in
    openspec)
      printf '%s\n' "${INITIALIZATION_AUDIT_ROOT}/openspec-init-formal-12/step12-formal-hashes.txt"
      ;;
    speckit)
      printf '%s\n' "${INITIALIZATION_AUDIT_ROOT}/speckit-init-formal-16/generated-files.sha256"
      ;;
    cc-sdd)
      printf '%s\n' "${INITIALIZATION_AUDIT_ROOT}/cc-sdd-init-formal-20/generated-files.sha256"
      ;;
    *) die "unknown variant: $1" ;;
  esac
}

expected_generated_manifest_sha256() {
  case "$1" in
    openspec) printf '%s\n' "$EXPECTED_OPENSPEC_GENERATED_MANIFEST_SHA256" ;;
    speckit) printf '%s\n' "$EXPECTED_SPECKIT_GENERATED_MANIFEST_SHA256" ;;
    cc-sdd) printf '%s\n' "$EXPECTED_CC_SDD_GENERATED_MANIFEST_SHA256" ;;
    *) die "unknown variant: $1" ;;
  esac
}

verify_initialized_repositories() {
  local variant repo status manifest expected_manifest_sha

  for variant in "${VARIANTS[@]}"; do
    verify_repository_identity "$variant"
    repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
    status="$(git -C "$repo" status --porcelain --untracked-files=no)"
    [[ -z "$status" ]] || die "${variant} has tracked or staged changes"

    manifest="$(generated_manifest "$variant")"
    expected_manifest_sha="$(expected_generated_manifest_sha256 "$variant")"
    assert_sha256 "$manifest" "$expected_manifest_sha" "${variant} generated-file manifest"

    cmp -s \
      <(git -C "$repo" ls-files --others --exclude-standard | LC_ALL=C sort) \
      <(awk '{sub(/^[[:xdigit:]]+[[:space:]][[:space:]]/, ""); print}' "$manifest" | LC_ALL=C sort) \
      || die "${variant} generated path set differs from the approved initialization manifest"

    (cd -- "$repo" && sha256sum --check --strict --quiet "$manifest") \
      || die "${variant} generated file content differs from the approved initialization manifest"
  done
}

verify_static() {
  require_command aa-status
  require_command awk
  require_command docker
  require_command git
  require_command grep
  require_command python3
  require_command sha256sum
  verify_files_and_images
  verify_initialized_repositories
  assert_subnets_available
  info "verify-static=PASS"
}

preflight() {
  validate_secret_file
  verify_static
  compose_with_secret config --quiet
  assert_project_absent
  info "preflight=PASS"
}

service_container_id() {
  local service="$1"
  local container_id

  container_id="$(compose_with_secret ps -q "$service")"
  [[ -n "$container_id" ]] || die "service has no container: ${service}"
  printf '%s\n' "$container_id"
}

verify_runtime() {
  local service container_id running health image security_options

  require_command docker
  require_command grep
  validate_secret_file
  verify_files_and_images
  verify_initialized_repositories

  for service in "${AGENT_SERVICES[@]}"; do
    container_id="$(service_container_id "$service")"
    running="$(docker inspect --format '{{.State.Running}}' "$container_id")"
    [[ "$running" == "true" ]] || die "Agent service is not running: ${service}"
    image="$(docker inspect --format '{{.Image}}' "$container_id")"
    [[ "$image" == "$AGENT_IMAGE_ID" ]] || die "Agent service image mismatch: ${service}"
    security_options="$(docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$container_id")"
    grep -q "apparmor=${PARENT_APPARMOR_PROFILE}" <<<"$security_options" || die "Agent AppArmor assignment mismatch: ${service}"
    grep -q 'no-new-privileges:true' <<<"$security_options" || die "Agent no-new-privileges missing: ${service}"
  done

  for service in "${PROXY_SERVICES[@]}"; do
    container_id="$(service_container_id "$service")"
    running="$(docker inspect --format '{{.State.Running}}' "$container_id")"
    [[ "$running" == "true" ]] || die "proxy service is not running: ${service}"
    health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$container_id")"
    [[ "$health" == "healthy" ]] || die "proxy service is not healthy: ${service} (${health})"
    image="$(docker inspect --format '{{.Image}}' "$container_id")"
    [[ "$image" == "$PROXY_IMAGE_ID" ]] || die "proxy service image mismatch: ${service}"
  done

  info "verify=PASS"
}

start_runtime() {
  preflight
  assert_old_baseline_stopped
  compose_with_secret up -d --wait --wait-timeout 120
  verify_runtime
  info "up=PASS"
}

variant_services() {
  case "$1" in
    openspec) printf '%s %s\n' 'openspec-agent' 'openspec-egress' ;;
    speckit) printf '%s %s\n' 'speckit-agent' 'speckit-egress' ;;
    cc-sdd) printf '%s %s\n' 'cc-sdd-agent' 'cc-sdd-egress' ;;
    *) die "unknown variant: $1" ;;
  esac
}

run_agent() {
  local variant="${1:-}"
  local prompt_supplied="${2:-}"
  local run_id="${3:-$(date -u +%Y%m%dT%H%M%SZ)}"
  local prompt_file agent_service proxy_service
  local jsonl_file stderr_file
  local -a pipeline_status

  [[ -n "$variant" && -n "$prompt_supplied" ]] || { usage; exit 2; }
  [[ "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "run-id contains unsupported characters"
  [[ ! -L "$prompt_supplied" ]] || die "prompt file must not be a symbolic link"
  prompt_file="$(realpath -e -- "$prompt_supplied")" || die "prompt file does not exist"
  [[ -f "$prompt_file" && -r "$prompt_file" && -s "$prompt_file" ]] || die "prompt must be a readable, non-empty regular file"

  read -r agent_service proxy_service < <(variant_services "$variant")
  require_command flock
  require_command git
  require_command sed
  require_command tee
  verify_repository_identity "$variant"
  verify_runtime

  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another formal Agent run is already active for ${TASK_ID}"

  mkdir -p -- "$AUDIT_RUN_ROOT"
  jsonl_file="${AUDIT_RUN_ROOT}/${run_id}-${variant}.jsonl"
  stderr_file="${AUDIT_RUN_ROOT}/${run_id}-${variant}.stderr.log"
  [[ ! -e "$jsonl_file" && ! -e "$stderr_file" ]] || die "run output already exists for run-id ${run_id}"

  info "variant=${variant}"
  info "agent_service=${agent_service}"
  info "timeout_seconds=${RUN_TIMEOUT_SECONDS}"
  info "jsonl=${jsonl_file}"

  set +e
  compose_with_secret exec -T "$agent_service" \
    timeout --foreground --signal=TERM --kill-after="${KILL_AFTER_SECONDS}s" "${RUN_TIMEOUT_SECONDS}s" \
    codex exec --strict-config --profile "$PROFILE_NAME" --ephemeral --json --color never -C /workspace - \
    <"$prompt_file" 2>"$stderr_file" | tee "$jsonl_file"
  pipeline_status=("${PIPESTATUS[@]}")
  set -e

  if [[ -s "$stderr_file" ]]; then
    printf '%s\n' '--- codex stderr ---' >&2
    sed -n '1,240p' "$stderr_file" >&2
  fi
  info "codex_exit_code=${pipeline_status[0]}"
  info "tee_exit_code=${pipeline_status[1]}"

  ((pipeline_status[1] == 0)) || die "failed to persist Codex JSONL output"
  return "${pipeline_status[0]}"
}

main() {
  local command="${1:-help}"
  shift || true

  case "$command" in
    help|-h|--help)
      usage
      ;;
    verify-static)
      (($# == 0)) || die "verify-static accepts no arguments"
      verify_static
      ;;
    preflight)
      (($# == 0)) || die "preflight accepts no arguments"
      preflight
      ;;
    up)
      (($# == 0)) || die "up accepts no arguments"
      start_runtime
      ;;
    verify)
      (($# == 0)) || die "verify accepts no arguments"
      verify_runtime
      ;;
    status)
      (($# == 0)) || die "status accepts no arguments"
      validate_secret_file
      compose_with_secret ps
      ;;
    run)
      ((2 <= $# && $# <= 3)) || { usage; exit 2; }
      run_agent "$@"
      ;;
    *)
      usage
      die "unknown command: ${command}"
      ;;
  esac
}

main "$@"
