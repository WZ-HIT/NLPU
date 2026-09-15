#!/usr/bin/env bash
set -Eeuo pipefail

umask 077

readonly TASK_ID="scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
readonly SAMPLE_ID="scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
readonly PR_ID="8073"
readonly BASE_SHA="11079cb1c85b9e75a39a7269943c69d1a975d485"
readonly PROJECT_NAME="scrapy-sdd-8073-600152fbc76dd5ba-agent"
readonly PROFILE_NAME="deepseek-flash"
readonly RUN_TIMEOUT_SECONDS=2700
readonly KILL_AFTER_SECONDS=30
readonly FINISH_POLICY="output-only-manual-review"
readonly AGENT_IMAGE_ID="sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9"
readonly PROXY_IMAGE_ID="sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
readonly PARENT_APPARMOR_PROFILE="scrapy_sdd_codex_parent_11079cb1c85b"
RUN_LOCK_HELD=0
ALL_MODE=0
ALL_TASK_INPUT_SHA256=""
ALL_CONFIG_SHA256=""
readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BENCH_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd -P)"
readonly COMPOSE_FILE="${SCRIPT_DIR}/compose.agent.yaml"
readonly DEFAULT_CONFIG="${SCRIPT_DIR}/experiment.json"
readonly DEFAULT_SECRET_FILE="/home/wangzuohit/.config/sdd-bench/deepseek-api-key"
readonly AUDIT_ROOT="${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/experiments"
readonly LOCK_FILE="/tmp/${PROJECT_NAME}.run.lock"

readonly COMMON_CONFIG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/config.toml"
readonly PROFILE_CONFIG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-flash.config.toml"
readonly MODEL_CATALOG="${BENCH_ROOT}/environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json"

readonly EXPECTED_COMPOSE_SHA256="11789f438228df24976e397a6b446edbe51736ba6a9f3288718bdcf40b4f2904"
readonly EXPECTED_COMMON_CONFIG_SHA256="b1c8c6d896b4c7e56adb864487f6d667cd682e21ccf1d0989c5646abc981851f"
readonly EXPECTED_PROFILE_CONFIG_SHA256="2e594da8abb241ef9c54cc376956a198371d305db4252d21341bd8d4fa1dd029"
readonly EXPECTED_MODEL_CATALOG_SHA256="4240127a851f7582bb4f92b9fe3b258f18393d560446e84430e5f90f473db9a1"

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
  run-experiment.sh prepare <pr8073-NNN>
  run-experiment.sh validate-config [experiment.json|pr8073-NNN]
  run-experiment.sh all [experiment.json|pr8073-NNN]
  run-experiment.sh parallel-all [experiment.json|pr8073-NNN]
  run-experiment.sh begin <openspec|speckit|cc-sdd> [experiment.json|pr8073-NNN]
  run-experiment.sh phase <openspec|speckit|cc-sdd> <phase> [experiment.json|pr8073-NNN]
  run-experiment.sh finish <openspec|speckit|cc-sdd> [experiment.json|pr8073-NNN]
  run-experiment.sh status <openspec|speckit|cc-sdd> [experiment.json|pr8073-NNN]
  run-experiment.sh probe <openspec|speckit|cc-sdd> [experiment.json|pr8073-NNN]

Phases:
  openspec: propose, apply
  speckit:  specify, plan, tasks, implement
  cc-sdd:   spec, implement

The default secret file is:
  /home/wangzuohit/.config/sdd-bench/deepseek-api-key

Set DEEPSEEK_API_KEY_FILE to override that path for a different credential.
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

require_runtime_commands() {
  local name
  for name in awk cat cmp cp docker flock git grep id mktemp mv python3 realpath rm rmdir sha256sum sleep sort stat tee timeout; do
    require_command "$name"
  done
}

acquire_run_lock() {
  ((RUN_LOCK_HELD == 0)) || return 0
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another formal Agent run is active"
  RUN_LOCK_HELD=1
}

assert_sha256() {
  local path="$1"
  local expected="$2"
  local label="$3"
  local actual

  [[ -f "$path" ]] || die "missing ${label}: ${path}"
  actual="$(sha256sum -- "$path" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || die "${label} SHA256 mismatch: ${actual}"
}

validate_secret_file() {
  local supplied="${DEEPSEEK_API_KEY_FILE:-$DEFAULT_SECRET_FILE}"
  local canonical owner mode

  [[ "$supplied" == /* ]] || die "DEEPSEEK_API_KEY_FILE must be absolute"
  [[ ! -L "$supplied" ]] || die "secret file must not be a symbolic link"
  canonical="$(realpath -e -- "$supplied")" || die "secret file does not exist"
  [[ -f "$canonical" && -r "$canonical" && -s "$canonical" ]] || \
    die "secret file must be a readable, non-empty regular file"
  case "$canonical" in
    "$BENCH_ROOT"|"$BENCH_ROOT"/*) die "secret file must be outside the benchmark tree" ;;
  esac
  owner="$(stat -c '%u' -- "$canonical")"
  [[ "$owner" == "$(id -u)" ]] || die "secret file must be owned by the invoking user"
  mode="$(stat -c '%a' -- "$canonical")"
  (( (8#$mode & 8#077) == 0)) || die "secret file must have no group/other permissions"
  SECRET_FILE="$canonical"
}

compose_with_secret() {
  DEEPSEEK_API_KEY_FILE="$SECRET_FILE" docker compose \
    --project-directory "$SCRIPT_DIR" -f "$COMPOSE_FILE" "$@"
}

validate_variant() {
  case "$1" in
    openspec|speckit|cc-sdd) ;;
    *) die "unknown variant: $1" ;;
  esac
}

expected_branch() {
  case "$1" in
    openspec) printf '%s\n' 'experiment/openspec' ;;
    speckit) printf '%s\n' 'experiment/speckit' ;;
    cc-sdd) printf '%s\n' 'experiment/cc-sdd' ;;
    *) die "unknown variant: $1" ;;
  esac
}

agent_service() {
  printf '%s-agent\n' "$1"
}

proxy_service() {
  printf '%s-egress\n' "$1"
}

generated_manifest() {
  case "$1" in
    openspec)
      printf '%s\n' "${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/openspec-init-formal-12/step12-formal-hashes.txt"
      ;;
    speckit)
      printf '%s\n' "${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/speckit-init-formal-16/generated-files.sha256"
      ;;
    cc-sdd)
      printf '%s\n' "${BENCH_ROOT}/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/cc-sdd-init-formal-20/generated-files.sha256"
      ;;
    *) die "unknown variant: $1" ;;
  esac
}

expected_manifest_sha256() {
  case "$1" in
    openspec) printf '%s\n' '70168a45d79ce6cd6d686c280476e3fbaf57179cc239cda700b49cac298c7141' ;;
    speckit) printf '%s\n' '404c4d70c695f254aa9bd372bf0f0b508ce53c6f3ab4f8f8446931eda6c0ce34' ;;
    cc-sdd) printf '%s\n' '3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca' ;;
    *) die "unknown variant: $1" ;;
  esac
}

expected_phases() {
  case "$1" in
    openspec) printf '%s\n' propose apply ;;
    speckit) printf '%s\n' specify plan tasks implement ;;
    cc-sdd) printf '%s\n' spec implement ;;
    *) die "unknown variant: $1" ;;
  esac
}

alias_config_path() {
  local alias="$1"
  local alias_pr run_number

  [[ "$alias" =~ ^pr([1-9][0-9]*)-([0-9]{3,})$ ]] || \
    die "invalid experiment alias: ${alias} (expected pr${PR_ID}-NNN)"
  alias_pr="${BASH_REMATCH[1]}"
  run_number="${BASH_REMATCH[2]}"
  [[ "$alias_pr" == "$PR_ID" ]] || \
    die "experiment alias PR ${alias_pr} does not match launcher PR ${PR_ID}"
  printf '%s/experiment-pr%s-comparison-%s.json\n' "$SCRIPT_DIR" "$alias_pr" "$run_number"
}

resolve_config_reference() {
  local supplied="${1:-$DEFAULT_CONFIG}"

  if [[ "$supplied" != */* && "$supplied" =~ ^pr[1-9][0-9]*-[0-9]{3,}$ ]]; then
    alias_config_path "$supplied"
  else
    printf '%s\n' "$supplied"
  fi
}

prepare_config() {
  local alias="$1"
  local target experiment_id

  target="$(alias_config_path "$alias")"
  experiment_id="$(basename -- "$target" .json)"
  experiment_id="${experiment_id#experiment-}"

  [[ ! -e "$target" ]] || die "experiment config already exists: ${target}"
  [[ ! -e "${AUDIT_ROOT}/${experiment_id}" ]] || \
    die "experiment results already exist: ${AUDIT_ROOT}/${experiment_id}"

  # Validate the canonical template before deriving a new configuration from it.
  load_config "$DEFAULT_CONFIG"
  python3 - "$DEFAULT_CONFIG" "$target" "$experiment_id" <<'PY'
import json
import pathlib
import sys

source_path = pathlib.Path(sys.argv[1])
target_path = pathlib.Path(sys.argv[2])
experiment_id = sys.argv[3]
data = json.loads(source_path.read_text(encoding="utf-8"))
data["experiment_id"] = experiment_id
with target_path.open("x", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2)
    stream.write("\n")
PY
  load_config "$target"
  info "config_prepare=PASS"
  info "experiment_id=${EXPERIMENT_ID}"
  info "config=${CONFIG_FILE}"
}

load_config() {
  local supplied="${1:-$DEFAULT_CONFIG}"
  local canonical
  local -a values

  [[ ! -L "$supplied" ]] || die "experiment config must not be a symbolic link"
  canonical="$(realpath -e -- "$supplied")" || die "experiment config does not exist: ${supplied}"
  [[ -f "$canonical" && -r "$canonical" ]] || die "experiment config is not readable"
  case "$canonical" in
    "$SCRIPT_DIR"/*) ;;
    *) die "experiment config must be inside ${SCRIPT_DIR}" ;;
  esac

  mapfile -t values < <(python3 - "$canonical" <<'PY'
import json
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    data = json.load(stream)

allowed = {
    "$schema", "schema_version", "experiment_id", "task_id", "sample_id",
    "pr_id", "task_base_sha", "input", "execution_order", "workflow",
}
required = allowed - {"$schema"}
if not isinstance(data, dict) or set(data) - allowed or not required <= set(data):
    raise SystemExit("invalid root fields in experiment config")
if data["schema_version"] != 1:
    raise SystemExit("schema_version must be 1")
if "$schema" in data and data["$schema"] != "./experiment.schema.json":
    raise SystemExit("unsupported $schema value")
if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", data["experiment_id"]):
    raise SystemExit("invalid experiment_id")
if not isinstance(data["pr_id"], int) or isinstance(data["pr_id"], bool) or data["pr_id"] < 1:
    raise SystemExit("invalid pr_id")
if not re.fullmatch(r"[0-9a-f]{40}", data["task_base_sha"]):
    raise SystemExit("invalid task_base_sha")

source = data["input"]
if not isinstance(source, dict) or source.get("mode") not in {"manual", "dataset"}:
    raise SystemExit("input mode must be manual or dataset")
expected_source_keys = {"mode", "path"} if source["mode"] == "manual" else {"mode", "path", "sample_id"}
if set(source) != expected_source_keys or not isinstance(source["path"], str) or not source["path"]:
    raise SystemExit("invalid input fields")
if source["mode"] == "manual":
    if source["path"].startswith("/") or ".." in source["path"].split("/"):
        raise SystemExit("manual input path must be task-relative and cannot contain ..")
elif source["sample_id"] != data["sample_id"]:
    raise SystemExit("dataset input sample_id must match the experiment sample_id")

order = data["execution_order"]
if not isinstance(order, list) or len(order) != 3 or set(order) != {"openspec", "speckit", "cc-sdd"}:
    raise SystemExit("execution_order must contain each variant exactly once")
workflow = data["workflow"]
if workflow != {"mode": "official-multistage", "human_intervention_between_phases": False}:
    raise SystemExit("unsupported workflow policy")

for value in (
    data["experiment_id"], data["task_id"], data["sample_id"], str(data["pr_id"]),
    data["task_base_sha"], source["mode"], source["path"], ",".join(order),
):
    if not isinstance(value, str) or "\n" in value or "\x00" in value:
        raise SystemExit("config contains an unsupported control character")
    print(value)
PY
  )
  ((${#values[@]} == 8)) || die "failed to load experiment config"

  CONFIG_FILE="$canonical"
  EXPERIMENT_ID="${values[0]}"
  CONFIG_TASK_ID="${values[1]}"
  CONFIG_SAMPLE_ID="${values[2]}"
  CONFIG_PR_ID="${values[3]}"
  CONFIG_BASE_SHA="${values[4]}"
  INPUT_MODE="${values[5]}"
  INPUT_PATH="${values[6]}"
  EXECUTION_ORDER="${values[7]}"

  [[ "$CONFIG_TASK_ID" == "$TASK_ID" ]] || die "task_id does not match this launcher"
  [[ "$CONFIG_SAMPLE_ID" == "$SAMPLE_ID" ]] || die "sample_id does not match this launcher"
  [[ "$CONFIG_PR_ID" == "$PR_ID" ]] || die "pr_id does not match this launcher"
  [[ "$CONFIG_BASE_SHA" == "$BASE_SHA" ]] || die "task_base_sha does not match this launcher"
}

resolve_input() {
  local destination="$1"
  local supplied canonical

  if [[ "$INPUT_MODE" == "manual" ]]; then
    supplied="${SCRIPT_DIR}/${INPUT_PATH}"
    [[ ! -L "$supplied" ]] || die "manual task input must not be a symbolic link"
    canonical="$(realpath -e -- "$supplied")" || die "manual task input does not exist"
    case "$canonical" in
      "$SCRIPT_DIR"/*) ;;
      *) die "manual task input escaped the task directory" ;;
    esac
    [[ -f "$canonical" && -r "$canonical" && -s "$canonical" ]] || die "manual task input is invalid"
    cp -- "$canonical" "$destination"
    return
  fi

  supplied="$INPUT_PATH"
  [[ "$supplied" == /* ]] || supplied="${SCRIPT_DIR}/${supplied}"
  [[ ! -L "$supplied" ]] || die "dataset input must not be a symbolic link"
  canonical="$(realpath -e -- "$supplied")" || die "dataset input does not exist"
  [[ -f "$canonical" && -r "$canonical" ]] || die "dataset input is not readable"
  python3 - "$canonical" "$CONFIG_SAMPLE_ID" "$PR_ID" >"$destination" <<'PY'
import json
import sys

path, sample_id, pr_id = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    records = json.load(stream)
matches = [item for item in records if item.get("sample_id") == sample_id]
if len(matches) != 1:
    raise SystemExit(f"expected one dataset record, found {len(matches)}")
record = matches[0]
if str(record.get("pr_id")) != pr_id:
    raise SystemExit("dataset pr_id does not match the experiment pr_id")
description = record.get("nl_description")
if not isinstance(description, str) or not description.strip():
    raise SystemExit("dataset natural-language description is empty")
sys.stdout.write(
    "# Test-only maintenance task\n\n"
    "Repository: `scrapy/scrapy`\n\n"
    + description.strip()
    + "\n\n## Constraints\n\n"
    "- Infer the relevant files and test cases by inspecting the base repository.\n"
    "- Modify files only beneath the repository-root `test/` or `tests/` directories.\n"
    "- Do not modify production code.\n"
    "- Do not access Git remotes, future commits, pull-request patches, merged code, "
    "gold tests, or reference answers.\n"
    "- Do not run tests during the current output-only experiment.\n"
)
PY
}

verify_repository_identity() {
  local variant="$1"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
  local head branch

  [[ -d "${repo}/.git" ]] || die "missing repository for ${variant}"
  head="$(git -C "$repo" rev-parse HEAD)"
  [[ "$head" == "$BASE_SHA" ]] || die "${variant} HEAD changed: ${head}"
  branch="$(git -C "$repo" branch --show-current)"
  [[ "$branch" == "$(expected_branch "$variant")" ]] || die "${variant} branch changed: ${branch}"
  [[ -z "$(git -C "$repo" remote)" ]] || die "${variant} repository has a remote"
}

verify_deployment_runtime() {
  local variant="$1"
  local agent proxy agent_id proxy_id value security_options

  assert_sha256 "$COMPOSE_FILE" "$EXPECTED_COMPOSE_SHA256" "deployment Compose"
  assert_sha256 "$COMMON_CONFIG" "$EXPECTED_COMMON_CONFIG_SHA256" "common Codex config"
  assert_sha256 "$PROFILE_CONFIG" "$EXPECTED_PROFILE_CONFIG_SHA256" "provider profile"
  assert_sha256 "$MODEL_CATALOG" "$EXPECTED_MODEL_CATALOG_SHA256" "model catalog"
  compose_with_secret config --quiet

  agent="$(agent_service "$variant")"
  proxy="$(proxy_service "$variant")"
  agent_id="$(compose_with_secret ps -q "$agent")"
  proxy_id="$(compose_with_secret ps -q "$proxy")"
  [[ -n "$agent_id" && -n "$proxy_id" ]] || die "missing runtime service for ${variant}"
  value="$(docker inspect --format '{{.State.Running}}' "$agent_id")"
  [[ "$value" == "true" ]] || die "Agent container is not running for ${variant}"
  value="$(docker inspect --format '{{.Image}}' "$agent_id")"
  [[ "$value" == "$AGENT_IMAGE_ID" ]] || die "Agent image mismatch for ${variant}"
  security_options="$(docker inspect --format '{{json .HostConfig.SecurityOpt}}' "$agent_id")"
  grep -q "apparmor=${PARENT_APPARMOR_PROFILE}" <<<"$security_options" || die "Agent AppArmor mismatch"
  grep -q 'no-new-privileges:true' <<<"$security_options" || die "Agent no-new-privileges missing"
  value="$(docker inspect --format '{{.State.Running}}' "$proxy_id")"
  [[ "$value" == "true" ]] || die "proxy container is not running for ${variant}"
  value="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$proxy_id")"
  [[ "$value" == "healthy" ]] || die "proxy is not healthy for ${variant}: ${value}"
  value="$(docker inspect --format '{{.Image}}' "$proxy_id")"
  [[ "$value" == "$PROXY_IMAGE_ID" ]] || die "proxy image mismatch for ${variant}"
}

verify_variant_pristine() {
  local variant="$1"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
  local manifest expected_sha

  verify_repository_identity "$variant"
  [[ -z "$(git -C "$repo" status --porcelain --untracked-files=no)" ]] || \
    die "${variant} has tracked or staged changes before experiment-begin"
  manifest="$(generated_manifest "$variant")"
  expected_sha="$(expected_manifest_sha256 "$variant")"
  assert_sha256 "$manifest" "$expected_sha" "${variant} initialization manifest"
  cmp -s \
    <(git -C "$repo" ls-files --others --exclude-standard | LC_ALL=C sort) \
    <(awk '{sub(/^[[:xdigit:]]+[[:space:]][[:space:]]/, ""); print}' "$manifest" | LC_ALL=C sort) \
    || die "${variant} initial generated path set changed"
  (cd -- "$repo" && sha256sum --check --strict --quiet "$manifest") || \
    die "${variant} initial generated file content changed"
}

test_path_allowed() {
  case "$1" in
    test/*|tests/*) return 0 ;;
    *) return 1 ;;
  esac
}

untracked_path_allowed() {
  local variant="$1"
  local path="$2"
  case "$variant:$path" in
    openspec:.agents/*|openspec:openspec/*) return 0 ;;
    speckit:.agents/*|speckit:.specify/*|speckit:specs/*) return 0 ;;
    cc-sdd:.agents/*|cc-sdd:.codex/*|cc-sdd:.kiro/*|cc-sdd:AGENTS.md) return 0 ;;
    *) return 1 ;;
  esac
}

verify_continuation_state() {
  local variant="$1"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
  local path

  verify_repository_identity "$variant"
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if ! test_path_allowed "$path"; then
      info "ERROR: tracked change outside repository-root test/ or tests/: ${path}"
      return 1
    fi
  done < <(
    { git -C "$repo" diff --no-renames --name-only; git -C "$repo" diff --cached --no-renames --name-only; } | LC_ALL=C sort -u
  )
  while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    if ! test_path_allowed "$path" && ! untracked_path_allowed "$variant" "$path"; then
      info "ERROR: untracked path outside test directories or ${variant} SDD scope: ${path}"
      return 1
    fi
  done < <(git -C "$repo" ls-files --others --exclude-standard)
}

experiment_dir() {
  printf '%s/%s/%s\n' "$AUDIT_ROOT" "$EXPERIMENT_ID" "$1"
}

state_file() {
  printf '%s/state.json\n' "$(experiment_dir "$1")"
}

create_state() {
  local variant="$1"
  local root="$2"
  local config_sha input_sha prestate_sha
  local -a phases
  mapfile -t phases < <(expected_phases "$variant")
  config_sha="$(sha256sum -- "${root}/config.snapshot.json" | awk '{print $1}')"
  input_sha="$(sha256sum -- "${root}/task-input.md" | awk '{print $1}')"
  prestate_sha="$(sha256sum -- "${root}/repository-prestate.txt" | awk '{print $1}')"
  python3 - "${root}/state.json" "$EXPERIMENT_ID" "$variant" "$config_sha" "$input_sha" "$prestate_sha" "${phases[@]}" <<'PY'
import datetime
import json
import os
import sys

path, experiment_id, variant, config_sha, input_sha, prestate_sha, *phases = sys.argv[1:]
data = {
    "schema_version": 1,
    "experiment_id": experiment_id,
    "variant": variant,
    "status": "active",
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "config_sha256": config_sha,
    "task_input_sha256": input_sha,
    "repository_prestate_sha256": prestate_sha,
    "expected_phases": phases,
    "completed_phases": [],
    "phase_records": [],
}
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.replace(temporary, path)
PY
}

state_value() {
  local path="$1"
  local key="$2"
  python3 - "$path" "$key" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    data = json.load(stream)
value = data[sys.argv[2]]
if isinstance(value, list):
    print(len(value))
else:
    print(value)
PY
}

prior_variants() {
  local requested="$1"
  local item
  local -a order
  IFS=',' read -r -a order <<<"$EXECUTION_ORDER"
  for item in "${order[@]}"; do
    [[ "$item" == "$requested" ]] && return 0
    printf '%s\n' "$item"
  done
  die "variant is absent from execution_order: ${requested}"
}

verify_execution_turn() {
  local variant="$1"
  local prior prior_state prior_status expected_config_sha actual_config_sha

  # Coordinated `all` modes enforce ordering or a start barrier at the parent.
  # A failed independent SDD must not gate another worker through state files.
  ((ALL_MODE == 0)) || return 0
  actual_config_sha="$(sha256sum -- "$CONFIG_FILE" | awk '{print $1}')"
  while IFS= read -r prior; do
    [[ -n "$prior" ]] || continue
    prior_state="$(state_file "$prior")"
    [[ -f "$prior_state" ]] || die "execution_order requires ${prior} to finish before ${variant}"
    prior_status="$(state_value "$prior_state" status)"
    [[ "$prior_status" == "finished_unverified" ]] || \
      die "execution_order predecessor ${prior} is not finished: ${prior_status}"
    expected_config_sha="$(state_value "$prior_state" config_sha256)"
    [[ "$actual_config_sha" == "$expected_config_sha" ]] || \
      die "experiment config changed after ${prior}"
  done < <(prior_variants "$variant")
}

verify_state_contract() {
  local variant="$1"
  local path="$2"
  local expected actual

  [[ "$(state_value "$path" experiment_id)" == "$EXPERIMENT_ID" ]] || die "state experiment_id mismatch"
  [[ "$(state_value "$path" variant)" == "$variant" ]] || die "state variant mismatch"
  expected="$(state_value "$path" config_sha256)"
  actual="$(sha256sum -- "$CONFIG_FILE" | awk '{print $1}')"
  [[ "$actual" == "$expected" ]] || die "experiment config changed after begin"
}

record_phase() {
  local path="$1"
  local phase="$2"
  local exit_code="$3"
  local prompt_sha="$4"
  local jsonl_sha="$5"
  python3 - "$path" "$phase" "$exit_code" "$prompt_sha" "$jsonl_sha" <<'PY'
import datetime
import json
import os
import sys

path, phase, exit_code, prompt_sha, jsonl_sha = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    data = json.load(stream)
record = {
    "phase": phase,
    "exit_code": int(exit_code),
    "finished_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "prompt_sha256": prompt_sha,
    "jsonl_sha256": jsonl_sha,
}
data["phase_records"].append(record)
if int(exit_code) == 0:
    data["completed_phases"].append(phase)
else:
    data["status"] = "phase_failed"
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.replace(temporary, path)
PY
}

mark_finished() {
  local path="$1"
  local status="$2"
  python3 - "$path" "$status" <<'PY'
import datetime
import json
import os
import sys

path, status = sys.argv[1:]
with open(path, encoding="utf-8") as stream:
    data = json.load(stream)
data["status"] = status
data["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
temporary = path + ".tmp"
with open(temporary, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
os.replace(temporary, path)
PY
}

capture_repository_state() {
  local variant="$1"
  local destination="$2"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"

  {
    printf 'head=%s\n' "$(git -C "$repo" rev-parse HEAD)"
    printf 'branch=%s\n' "$(git -C "$repo" branch --show-current)"
    printf 'remote_count=%s\n' "$(git -C "$repo" remote | wc -l)"
    printf '%s\n' '[status]'
    git -C "$repo" status --porcelain=v1
    printf '%s\n' '[untracked-sha256]'
    while IFS= read -r path; do
      [[ -n "$path" ]] || continue
      (cd -- "$repo" && sha256sum -- "$path")
    done < <(git -C "$repo" ls-files --others --exclude-standard | LC_ALL=C sort)
  } >"$destination"
}

build_phase_prompt() {
  local variant="$1"
  local phase="$2"
  local task_input="$3"
  local destination="$4"
  local research_limit research_mode

  case "$variant:$phase" in
    openspec:propose)
      cat >"$destination" <<'EOF'
Use the repository skill `$openspec-propose` for the shared task below.
Create the complete OpenSpec proposal, specs, design, and tasks. This phase is
planning only: do not edit project source or test code, and stop after the
planning artifacts are ready. Do not ask for interactive clarification; record
the smallest reasonable assumption when needed. Write the required artifacts as
soon as sufficient repository evidence is available, then return immediately.
EOF
      ;;
    openspec:apply)
      cat >"$destination" <<'EOF'
Use the repository skill `$openspec-apply-change` for the single active change
created by the preceding phase. Implement only the shared test-update task. Do
not modify production code. File changes are allowed only beneath the
repository-root `test/` or `tests/` directories. Update the OpenSpec task
state as prescribed, and stop immediately. Treat the preceding OpenSpec
artifacts as the authoritative scope; do not repeat proposal-stage discovery.
Do not run any test command; validation is reserved for later manual review.
EOF
      ;;
    speckit:specify)
      cat >"$destination" <<'EOF'
Use the repository skill `$speckit-specify` for the shared task below. Produce
the feature specification only. Do not edit project source or test code. Do not
ask for interactive clarification; make the smallest reasonable assumption.
Write and validate the specification as soon as the exact repository matches
have been inspected, then return immediately.
EOF
      ;;
    speckit:plan)
      cat >"$destination" <<'EOF'
Use the repository skill `$speckit-plan` for the feature created by the
preceding phase. Produce the implementation plan and its prescribed design
artifacts only. Treat the preceding specification as the authoritative scope:
read it first, do not rediscover the affected tests, and fill the concrete plan
before any strictly necessary supplemental lookup. Do not edit project source
or test code. Stop immediately when the prescribed plan artifacts are complete.
EOF
      ;;
    speckit:tasks)
      cat >"$destination" <<'EOF'
Use the repository skill `$speckit-tasks` for the feature created by the
preceding phases. Produce the dependency-ordered tasks only. Do not edit project
source or test code. Derive tasks from the existing specification and plan; do
not rescan the repository or third-party packages. Stop when tasks.md is ready.
EOF
      ;;
    speckit:implement)
      cat >"$destination" <<'EOF'
Use the repository skill `$speckit-implement` for the single prepared feature.
Implement only the shared test-update task. Do not modify production code. File
changes are allowed only beneath the repository-root `test/` or `tests/`
directories. Record the prescribed task completion state and stop. Do not run
any test command; validation is reserved for later manual review. Use the
prepared tasks as the authoritative scope and do not repeat planning research.
EOF
      ;;
    cc-sdd:spec)
      cat >"$destination" <<'EOF'
Use the repository skill `$kiro-spec-quick` in `--auto` mode for the shared task
below. Complete its requirements, design, tasks, approvals, and final sanity
review, but do not implement or edit project source or test code in this phase.
Write artifacts progressively. As soon as `spec.json` records
`ready_for_implementation=true`, return immediately without additional research.
EOF
      ;;
    cc-sdd:implement)
      cat >"$destination" <<'EOF'
Use the repository skill `$kiro-impl` for the single approved spec created by
the preceding phase. Determine its feature name from `.kiro/specs/`. Implement
only the shared test-update task. Do not modify production code. File changes
are allowed only beneath the repository-root `test/` or `tests/` directories.
Stop after the implementation output is ready. Do not run any test command;
validation is reserved for later manual review. Treat the approved `.kiro`
artifacts as authoritative and do not repeat spec-stage repository research.
EOF
      ;;
    *) die "unsupported phase: ${variant}:${phase}" ;;
  esac

  case "$variant:$phase" in
    openspec:propose|speckit:specify|cc-sdd:spec)
      research_limit=12
      research_mode="initial bounded discovery"
      ;;
    openspec:apply|speckit:plan|speckit:tasks|cc-sdd:implement)
      research_limit=6
      research_mode="reuse preceding artifacts"
      ;;
    speckit:implement)
      research_limit=4
      research_mode="implementation-only lookup"
      ;;
    *) die "missing research policy: ${variant}:${phase}" ;;
  esac
  cat >>"$destination" <<EOF

--- Bounded research contract (identical policy class across SDDs) ---

- Mode: ${research_mode}.
- Use no more than ${research_limit} repository-investigation commands in this
  phase. Reads required solely to load the selected SDD skill and its directly
  referenced templates do not count toward this number.
- Use one exact 'rg' search for the reported marker during initial discovery.
  Once matches or predecessor artifacts establish scope, do not repeat searches
  with equivalent patterns.
- Read only focused file ranges and cap each investigation command at 200 output
  lines. Do not enumerate the whole repository, dump full CI workflow sets, or
  inspect whole installed dependency source trees.
- Prefer predecessor artifacts over new investigation. Write mandatory artifacts
  before optional checks and return immediately once this phase is complete.
- These limits do not reveal a target file or test; infer scope from the allowed
  base-repository evidence.
EOF
  {
    printf '\n--- Shared task (identical semantic input for every SDD) ---\n\n'
    cat -- "$task_input"
    printf '\n'
  } >>"$destination"
}

execute_codex() {
  local variant="$1"
  local label="$2"
  local prompt_file="$3"
  local output_dir="$4"
  local service jsonl stderr_file
  local -a pipeline_status

  service="$(agent_service "$variant")"
  jsonl="${output_dir}/${label}.jsonl"
  stderr_file="${output_dir}/${label}.stderr.log"
  [[ ! -e "$jsonl" && ! -e "$stderr_file" ]] || die "run output already exists: ${label}"

  set +e
  compose_with_secret exec -T "$service" \
    timeout --foreground --signal=TERM --kill-after="${KILL_AFTER_SECONDS}s" "${RUN_TIMEOUT_SECONDS}s" \
    codex exec --strict-config --profile "$PROFILE_NAME" --ephemeral --json --color never -C /workspace - \
    <"$prompt_file" 2>"$stderr_file" | tee "$jsonl"
  pipeline_status=("${PIPESTATUS[@]}")
  # Callers disable errexit while collecting the Codex status. Do not re-enable
  # it here, or a non-zero return would bypass their failure recording logic.
  ((pipeline_status[1] == 0)) || die "failed to persist Codex JSONL for ${label}"
  return "${pipeline_status[0]}"
}

begin_experiment() {
  local variant="$1"
  local root state input_temporary input_sha prior prior_state expected_input_sha
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"

  validate_secret_file
  acquire_run_lock
  verify_deployment_runtime "$variant"
  verify_variant_pristine "$variant"
  verify_execution_turn "$variant"
  root="$(experiment_dir "$variant")"
  state="$(state_file "$variant")"
  [[ ! -e "$root" ]] || die "experiment state already exists: ${root}"
  input_temporary="$(mktemp /tmp/sdd-task-input.XXXXXX)"
  resolve_input "$input_temporary"
  input_sha="$(sha256sum -- "$input_temporary" | awk '{print $1}')"
  if ((ALL_MODE == 1)); then
    [[ "$input_sha" == "$ALL_TASK_INPUT_SHA256" ]] || {
      rm -f -- "$input_temporary"
      die "resolved task input changed during all run"
    }
  else
    while IFS= read -r prior; do
      [[ -n "$prior" ]] || continue
      prior_state="$(state_file "$prior")"
      expected_input_sha="$(state_value "$prior_state" task_input_sha256)"
      [[ "$input_sha" == "$expected_input_sha" ]] || {
        rm -f -- "$input_temporary"
        die "resolved task input differs from predecessor ${prior}"
      }
    done < <(prior_variants "$variant")
  fi
  mkdir -p -- "$root/phases"
  cp -- "$CONFIG_FILE" "$root/config.snapshot.json"
  mv -- "$input_temporary" "$root/task-input.md"
  capture_repository_state "$variant" "$root/repository-prestate.txt"
  git -C "$repo" diff --binary >"$root/prestate.diff"
  create_state "$variant" "$root"
  info "experiment_begin=PASS"
  info "variant=${variant}"
  info "state=${state}"
}

run_phase() {
  local variant="$1"
  local phase="$2"
  local root state status completed expected index phase_dir prompt_file
  local exit_code scope_code prompt_sha jsonl_sha
  local -a phases

  validate_secret_file
  root="$(experiment_dir "$variant")"
  state="$(state_file "$variant")"
  [[ -f "$state" ]] || die "run experiment-begin first for ${variant}"
  verify_state_contract "$variant" "$state"
  status="$(state_value "$state" status)"
  [[ "$status" == "active" ]] || die "experiment state is not active: ${status}"
  completed="$(state_value "$state" completed_phases)"
  mapfile -t phases < <(expected_phases "$variant")
  ((completed < ${#phases[@]})) || die "all phases are already complete"
  expected="${phases[$completed]}"
  [[ "$phase" == "$expected" ]] || die "expected phase ${expected}, got ${phase}"
  index="$(printf '%02d' "$((completed + 1))")"
  phase_dir="${root}/phases"
  prompt_file="${phase_dir}/${index}-${phase}.prompt.md"

  acquire_run_lock
  verify_deployment_runtime "$variant"
  verify_continuation_state "$variant"
  build_phase_prompt "$variant" "$phase" "$root/task-input.md" "$prompt_file"
  prompt_sha="$(sha256sum -- "$prompt_file" | awk '{print $1}')"

  set +e
  execute_codex "$variant" "${index}-${phase}" "$prompt_file" "$phase_dir"
  exit_code=$?
  verify_continuation_state "$variant"
  scope_code=$?
  set -e
  ((scope_code == 0)) || exit_code=125
  jsonl_sha="$(sha256sum -- "${phase_dir}/${index}-${phase}.jsonl" | awk '{print $1}')"
  record_phase "$state" "$phase" "$exit_code" "$prompt_sha" "$jsonl_sha"
  ((exit_code == 0)) || die "phase failed: ${variant}:${phase} (exit ${exit_code})"
  info "experiment_phase=PASS"
  info "variant=${variant}"
  info "phase=${phase}"
  info "progress=$((completed + 1))/${#phases[@]}"
}

capture_final_evidence() {
  local variant="$1"
  local root="$2"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"

  git -C "$repo" status --porcelain=v1 >"${root}/changed-files.txt"
  git -C "$repo" diff --binary >"${root}/git.diff"
  git -C "$repo" diff --cached --binary >"${root}/git-cached.diff"
  capture_repository_state "$variant" "${root}/repository-poststate.txt"
}

finish_experiment() {
  local variant="$1"
  local root state status completed
  local -a phases

  validate_secret_file
  root="$(experiment_dir "$variant")"
  state="$(state_file "$variant")"
  [[ -f "$state" ]] || die "run experiment-begin first for ${variant}"
  verify_state_contract "$variant" "$state"
  status="$(state_value "$state" status)"
  [[ "$status" == "active" ]] || die "experiment state is not active: ${status}"
  completed="$(state_value "$state" completed_phases)"
  mapfile -t phases < <(expected_phases "$variant")
  ((completed == ${#phases[@]})) || die "workflow incomplete: ${completed}/${#phases[@]} phases"

  acquire_run_lock
  verify_deployment_runtime "$variant"
  verify_continuation_state "$variant"
  capture_final_evidence "$variant" "$root"
  python3 - "${root}/summary.json" "$variant" "$completed" "$FINISH_POLICY" <<'PY'
import json
import sys

path, variant, calls, finish_policy = sys.argv[1:]
data = {
    "variant": variant,
    "llm_call_count": int(calls),
    "status": "AWAITING_MANUAL_REVIEW",
    "finish_policy": finish_policy,
    "validation_status": "NOT_RUN",
    "validation_exit_code": None,
    "manual_review_required": True,
}
with open(path, "w", encoding="utf-8") as stream:
    json.dump(data, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY
  mark_finished "$state" "finished_unverified"
  info "experiment_finish=finished_unverified"
  info "validation_status=NOT_RUN"
  info "manual_review_required=true"
  info "results=${root}"
}

repository_fingerprint() {
  local variant="$1"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"
  {
    git -C "$repo" status --porcelain=v1
    git -C "$repo" diff --binary
    while IFS= read -r path; do
      [[ -n "$path" ]] || continue
      (cd -- "$repo" && sha256sum -- "$path")
    done < <(git -C "$repo" ls-files --others --exclude-standard | LC_ALL=C sort)
  } | sha256sum | awk '{print $1}'
}

probe_multistage() {
  local variant="$1"
  local probe_id root before after first_exit second_exit

  validate_secret_file
  acquire_run_lock
  verify_deployment_runtime "$variant"
  verify_variant_pristine "$variant"
  probe_id="$(date -u +%Y%m%dT%H%M%SZ)"
  root="${AUDIT_ROOT}/launcher-probes/${probe_id}/${variant}"
  mkdir -p -- "$root"
  before="$(repository_fingerprint "$variant")"
  cat >"${root}/01-read-only.prompt.md" <<'EOF'
Read the shared task and inspect the relevant existing test files.
Do not modify, create, move, or delete any file. Do not run an SDD workflow.
Reply briefly with the exact marker PROBE_STAGE_1_OK.
EOF
  set +e
  execute_codex "$variant" 01-read-only "${root}/01-read-only.prompt.md" "$root"
  first_exit=$?
  cat >"${root}/02-read-only.prompt.md" <<'EOF'
This is an independent second launcher phase. Read the shared task and relevant
existing test files. Do not modify, create, move, or delete any file. Reply
briefly with the exact marker PROBE_STAGE_2_OK.
EOF
  execute_codex "$variant" 02-read-only "${root}/02-read-only.prompt.md" "$root"
  second_exit=$?
  set -e
  after="$(repository_fingerprint "$variant")"
  [[ "$before" == "$after" ]] || die "probe changed repository content"
  ((first_exit == 0 && second_exit == 0)) || die "probe Codex call failed"
  grep -q 'PROBE_STAGE_1_OK' "${root}/01-read-only.jsonl" || die "first probe marker missing"
  grep -q 'PROBE_STAGE_2_OK' "${root}/02-read-only.jsonl" || die "second probe marker missing"
  printf 'before_sha256=%s\nafter_sha256=%s\n' "$before" "$after" >"${root}/repository-fingerprint.txt"
  info "multistage_probe=PASS"
  info "variant=${variant}"
  info "results=${root}"
}

capture_failure_evidence() {
  local variant="$1"
  local root="$2"
  local repo="${SCRIPT_DIR}/runs/${variant}/scrapy"

  [[ -d "${repo}/.git" ]] || return 0
  mkdir -p -- "$root"
  git -C "$repo" status --porcelain=v1 >"${root}/changed-files.txt"
  git -C "$repo" diff --binary >"${root}/git.diff"
  git -C "$repo" diff --cached --binary >"${root}/git-cached.diff"
  capture_repository_state "$variant" "${root}/repository-poststate.txt"
}

record_variant_failure() {
  local variant="$1"
  local stage="$2"
  local exit_code="$3"
  local orchestration_log="$4"
  local root

  root="$(experiment_dir "$variant")"
  mkdir -p -- "$root"
  python3 - "$root/failure.json" "$root" "$variant" "$stage" "$exit_code" "$orchestration_log" <<'PY'
import datetime
import json
import pathlib
import sys

output, root_value, variant, stage, exit_code, log_value = sys.argv[1:]
root = pathlib.Path(root_value)
reason = None
source = None
phase_name = stage.partition(":")[2] if stage.startswith("phase:") else None
jsonl_files = (
    sorted((root / "phases").glob(f"*-{phase_name}.jsonl"), reverse=True)
    if phase_name
    else []
)
for jsonl in jsonl_files:
    candidates = []
    for line in jsonl.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error" and isinstance(event.get("message"), str):
            candidates.append(event["message"])
        error = event.get("error")
        if event.get("type") == "turn.failed" and isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                candidates.append(message)
    if candidates:
        reason = candidates[-1]
        source = str(jsonl.relative_to(root))
        break
if reason is None and stage == "finish":
    summary = root / "summary.json"
    if summary.is_file():
        try:
            validation_exit = json.loads(summary.read_text(encoding="utf-8")).get(
                "validation_exit_code"
            )
        except (json.JSONDecodeError, OSError):
            validation_exit = None
        if isinstance(validation_exit, int) and validation_exit != 0:
            reason = f"validation command exited with code {validation_exit}"
            source = summary.name
if reason is None:
    log = pathlib.Path(log_value)
    if log.is_file():
        lines = [line.strip() for line in log.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
        errors = [line for line in lines if line.startswith("ERROR:")]
        if errors or lines:
            reason = (errors or lines)[-1]
            source = log.name
if reason is None:
    reason = f"workflow exited with code {exit_code}"

state_status = None
state = root / "state.json"
if state.is_file():
    try:
        state_status = json.loads(state.read_text(encoding="utf-8")).get("status")
    except (json.JSONDecodeError, OSError):
        pass

data = {
    "schema_version": 1,
    "variant": variant,
    "status": "FAIL",
    "failed_stage": stage,
    "exit_code": int(exit_code),
    "reason": reason,
    "reason_source": source,
    "state_status": state_status,
    "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
path = pathlib.Path(output)
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY
}

write_all_summary() {
  local overall_status="$1"
  local execution_mode="$2"
  local start_barrier_status="$3"
  shift 3
  local root
  root="$(dirname -- "$(experiment_dir "$1")")"

  python3 - "$root/all-summary.json" "$overall_status" "$execution_mode" "$start_barrier_status" "$EXECUTION_ORDER" "$@" <<'PY'
import datetime
import json
import pathlib
import sys

output, overall_status, execution_mode, start_barrier_status, execution_order, *variants = sys.argv[1:]
root = pathlib.Path(output).parent
records = []
for variant in variants:
    variant_root = root / variant
    failure_path = variant_root / "failure.json"
    summary_path = variant_root / "summary.json"
    state_path = variant_root / "state.json"
    record = {"variant": variant, "status": "UNKNOWN"}
    if failure_path.is_file():
        failure = json.loads(failure_path.read_text(encoding="utf-8"))
        record.update({
            "status": "FAIL",
            "failed_stage": failure.get("failed_stage"),
            "exit_code": failure.get("exit_code"),
            "reason": failure.get("reason"),
        })
    elif summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        record.update({
            "status": summary.get("status", "UNKNOWN"),
            "finish_policy": summary.get("finish_policy"),
            "validation_status": summary.get("validation_status"),
            "validation_exit_code": summary.get("validation_exit_code"),
            "manual_review_required": summary.get("manual_review_required"),
        })
    elif state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        record["status"] = state.get("status", "UNKNOWN")
    records.append(record)

data = {
    "schema_version": 1,
    "experiment_id": root.name,
    "status": overall_status,
    "execution_mode": execution_mode,
    "start_barrier_status": start_barrier_status,
    "execution_order": execution_order.split(","),
    "variants": records,
    "finished_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
path = pathlib.Path(output)
temporary = path.with_suffix(path.suffix + ".tmp")
temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
temporary.replace(path)
PY
}

run_all_variant_preflight() {
  local variant="$1"
  local stage_file="$2"

  printf '%s\n' preflight >"$stage_file"
  [[ "$(sha256sum -- "$CONFIG_FILE" | awk '{print $1}')" == "$ALL_CONFIG_SHA256" ]] || \
    die "experiment config changed during coordinated run"
  verify_deployment_runtime "$variant" || return $?
  verify_variant_pristine "$variant" || return $?
}

run_all_variant_workflow() {
  local variant="$1"
  local stage_file="$2"
  local phase
  local -a phases

  printf '%s\n' begin >"$stage_file"
  begin_experiment "$variant" || return $?
  mapfile -t phases < <(expected_phases "$variant")
  for phase in "${phases[@]}"; do
    printf 'phase:%s\n' "$phase" >"$stage_file"
    run_phase "$variant" "$phase" || return $?
  done
  printf '%s\n' finish >"$stage_file"
  finish_experiment "$variant" || return $?
}

run_all_variant() {
  local variant="$1"
  local stage_file="$2"

  run_all_variant_preflight "$variant" "$stage_file" || return $?
  run_all_variant_workflow "$variant" "$stage_file"
}

run_parallel_all_variant() {
  local variant="$1"
  local stage_file="$2"
  local ready_file="$3"
  local start_file="$4"

  run_all_variant_preflight "$variant" "$stage_file" || return $?
  printf '%s\n' ready >"$ready_file"
  while [[ ! -f "$start_file" ]]; do
    sleep 0.05
  done
  run_all_variant_workflow "$variant" "$stage_file"
}

run_all_experiments() {
  local variant root variant_log stage_file shared_input
  local variant_exit log_exit overall_exit=0 overall_status="AWAITING_MANUAL_REVIEW"
  local -a order

  validate_secret_file
  acquire_run_lock
  IFS=',' read -r -a order <<<"$EXECUTION_ORDER"

  # Result collisions are experiment-wide configuration errors. Refuse the
  # whole run before the first model call rather than overwrite prior evidence.
  for variant in "${order[@]}"; do
    validate_variant "$variant"
    root="$(experiment_dir "$variant")"
    [[ ! -e "$root" ]] || die "experiment state already exists: ${root}"
  done

  shared_input="$(mktemp /tmp/sdd-all-task-input.XXXXXX)"
  resolve_input "$shared_input"
  ALL_TASK_INPUT_SHA256="$(sha256sum -- "$shared_input" | awk '{print $1}')"
  ALL_CONFIG_SHA256="$(sha256sum -- "$CONFIG_FILE" | awk '{print $1}')"
  rm -f -- "$shared_input"
  ALL_MODE=1

  info "experiment_all=START"
  info "execution_order=${EXECUTION_ORDER}"
  for variant in "${order[@]}"; do
    root="$(experiment_dir "$variant")"
    variant_log="$(mktemp /tmp/sdd-all-${variant}.stderr.XXXXXX)"
    stage_file="$(mktemp /tmp/sdd-all-${variant}.stage.XXXXXX)"
    info "experiment_all_variant=${variant}"

    set +e
    (run_all_variant "$variant" "$stage_file") 2> >(tee "$variant_log" >&2)
    variant_exit=$?
    wait
    log_exit=$?
    set -e
    ((log_exit == 0)) || die "failed to persist orchestration log for ${variant}"

    mkdir -p -- "$root"
    mv -- "$variant_log" "${root}/all.stderr.log"
    if ((variant_exit != 0)); then
      capture_failure_evidence "$variant" "$root"
      record_variant_failure "$variant" "$(cat -- "$stage_file")" "$variant_exit" "${root}/all.stderr.log"
      overall_exit=1
      overall_status="FAIL"
      info "experiment_all_variant_failed=${variant}"
      info "experiment_all_continuing=true"
    else
      info "experiment_all_variant_passed=${variant}"
    fi
    rm -f -- "$stage_file"
  done

  write_all_summary "$overall_status" "sequential" "not_applicable" "${order[@]}"
  info "experiment_all=${overall_status}"
  info "results=${AUDIT_ROOT}/${EXPERIMENT_ID}"
  return "$overall_exit"
}

run_parallel_all_experiments() {
  local variant root shared_input barrier_dir start_file deadline ready_count barrier_failed=0
  local barrier_status="DEGRADED"
  local variant_exit stage overall_exit=0 overall_status="AWAITING_MANUAL_REVIEW"
  local -a order
  local -A pids logs stages readies

  validate_secret_file
  acquire_run_lock
  IFS=',' read -r -a order <<<"$EXECUTION_ORDER"

  # Refuse the entire comparison before launching any worker if prior evidence
  # would be overwritten.
  for variant in "${order[@]}"; do
    validate_variant "$variant"
    root="$(experiment_dir "$variant")"
    [[ ! -e "$root" ]] || die "experiment state already exists: ${root}"
  done

  shared_input="$(mktemp /tmp/sdd-parallel-task-input.XXXXXX)"
  resolve_input "$shared_input"
  ALL_TASK_INPUT_SHA256="$(sha256sum -- "$shared_input" | awk '{print $1}')"
  ALL_CONFIG_SHA256="$(sha256sum -- "$CONFIG_FILE" | awk '{print $1}')"
  rm -f -- "$shared_input"
  ALL_MODE=1

  barrier_dir="$(mktemp -d /tmp/sdd-parallel-all.XXXXXX)"
  start_file="${barrier_dir}/start"
  info "experiment_parallel_all=START"
  info "execution_order=${EXECUTION_ORDER}"
  info "execution_mode=parallel"

  for variant in "${order[@]}"; do
    logs[$variant]="$(mktemp "/tmp/sdd-parallel-${variant}.console.XXXXXX")"
    stages[$variant]="$(mktemp "/tmp/sdd-parallel-${variant}.stage.XXXXXX")"
    readies[$variant]="${barrier_dir}/${variant}.ready"
    info "experiment_parallel_worker_launch=${variant}"
    (
      trap 'worker_exit=$?; if [[ ! -f "'"${readies[$variant]}"'" ]]; then printf "%s\n" "$worker_exit" >"'"${readies[$variant]}.failed"'"; fi' EXIT
      run_parallel_all_variant "$variant" "${stages[$variant]}" \
        "${readies[$variant]}" "$start_file"
    ) >"${logs[$variant]}" 2>&1 &
    pids[$variant]=$!
  done

  deadline=$((SECONDS + 60))
  while :; do
    ready_count=0
    barrier_failed=0
    for variant in "${order[@]}"; do
      [[ -f "${readies[$variant]}" ]] && ready_count=$((ready_count + 1))
      [[ -f "${readies[$variant]}.failed" ]] && barrier_failed=1
    done
    ((ready_count == ${#order[@]})) && break
    ((barrier_failed == 0 && SECONDS < deadline)) || break
    sleep 0.05
  done

  printf '%s\n' start >"$start_file"
  if ((ready_count == ${#order[@]})); then
    barrier_status="PASS"
    info "parallel_start_barrier=PASS"
  else
    info "parallel_start_barrier=DEGRADED ready=${ready_count}/${#order[@]}"
  fi

  for variant in "${order[@]}"; do
    set +e
    wait "${pids[$variant]}"
    variant_exit=$?
    set -e

    root="$(experiment_dir "$variant")"
    mkdir -p -- "$root"
    mv -- "${logs[$variant]}" "${root}/parallel-all.console.log"
    stage="$(cat -- "${stages[$variant]}")"
    [[ -n "$stage" ]] || stage="preflight"
    if ((variant_exit != 0)); then
      capture_failure_evidence "$variant" "$root"
      record_variant_failure "$variant" "$stage" "$variant_exit" \
        "${root}/parallel-all.console.log"
      overall_exit=1
      overall_status="FAIL"
      info "experiment_parallel_worker_failed=${variant}"
    else
      info "experiment_parallel_worker_passed=${variant}"
    fi
    rm -f -- "${stages[$variant]}" "${readies[$variant]}" "${readies[$variant]}.failed"
  done

  rm -f -- "$start_file"
  rmdir -- "$barrier_dir"
  write_all_summary "$overall_status" "parallel" "$barrier_status" "${order[@]}"
  info "experiment_parallel_all=${overall_status}"
  info "results=${AUDIT_ROOT}/${EXPERIMENT_ID}"
  return "$overall_exit"
}

show_status() {
  local variant="$1"
  local state
  state="$(state_file "$variant")"
  [[ -f "$state" ]] || die "no experiment state for ${variant}"
  cat -- "$state"
}

main() {
  local command="${1:-help}"
  local variant phase config
  shift || true

  case "$command" in
    help|-h|--help)
      usage
      ;;
    prepare)
      (($# == 1)) || { usage; exit 2; }
      require_command basename
      require_command python3
      require_command realpath
      prepare_config "$1"
      ;;
    validate-config)
      (($# <= 1)) || { usage; exit 2; }
      require_command python3
      require_command realpath
      config="$(resolve_config_reference "${1:-$DEFAULT_CONFIG}")"
      load_config "$config"
      info "config_validation=PASS"
      info "experiment_id=${EXPERIMENT_ID}"
      ;;
    all)
      (($# <= 1)) || { usage; exit 2; }
      config="$(resolve_config_reference "${1:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      load_config "$config"
      run_all_experiments
      ;;
    parallel-all)
      (($# <= 1)) || { usage; exit 2; }
      config="$(resolve_config_reference "${1:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      load_config "$config"
      run_parallel_all_experiments
      ;;
    begin)
      ((1 <= $# && $# <= 2)) || { usage; exit 2; }
      variant="$1"
      config="$(resolve_config_reference "${2:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      validate_variant "$variant"
      load_config "$config"
      begin_experiment "$variant"
      ;;
    phase)
      ((2 <= $# && $# <= 3)) || { usage; exit 2; }
      variant="$1"
      phase="$2"
      config="$(resolve_config_reference "${3:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      validate_variant "$variant"
      load_config "$config"
      run_phase "$variant" "$phase"
      ;;
    finish)
      ((1 <= $# && $# <= 2)) || { usage; exit 2; }
      variant="$1"
      config="$(resolve_config_reference "${2:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      validate_variant "$variant"
      load_config "$config"
      finish_experiment "$variant"
      ;;
    status)
      ((1 <= $# && $# <= 2)) || { usage; exit 2; }
      variant="$1"
      config="$(resolve_config_reference "${2:-$DEFAULT_CONFIG}")"
      require_command python3
      require_command realpath
      validate_variant "$variant"
      load_config "$config"
      show_status "$variant"
      ;;
    probe)
      ((1 <= $# && $# <= 2)) || { usage; exit 2; }
      variant="$1"
      config="$(resolve_config_reference "${2:-$DEFAULT_CONFIG}")"
      require_runtime_commands
      validate_variant "$variant"
      load_config "$config"
      probe_multistage "$variant"
      ;;
    *)
      usage
      die "unknown command: ${command}"
      ;;
  esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
