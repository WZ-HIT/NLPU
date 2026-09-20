#!/usr/bin/env bash
# Restore every pre-experiment checkpoint, not just the one a script was cut for.
#
# The per-experiment restore.sh scripts are pinned to a single task: TASK_DIR,
# PROJECT_NAME and the payload names are all hardcoded, and each new experiment
# got a fresh copy with three lines changed. That is why nothing restored "all
# PRs" -- there was no such entry point -- and it is also why Docker accumulated
# leftovers: a task whose checkpoint is not named in a script is never restored,
# and the Compose stacks it owns are never brought down by anything.
#
# This driver owns them. Every fact it needs is already in checkpoint.json:
# task_id, task_base_sha, deployment.compose_project, deployment.agent_image,
# repositories[] and home_volumes[]. It restores each *task* to its pre-SDD
# state, and it brings down **every** Compose stack in that task's directory
# first, not only the agent stack -- both stacks bind the same
# runs/<variant>/scrapy repositories, so swapping those under a live container
# would corrupt whichever one is still up.
#
# What it deliberately does not do: delete a Docker volume that no payload can
# put back. `down` therefore omits --volumes, so the base stack's own HOME
# volumes survive a restore. Use --keep-backups to bound restore-backups/.
#
# Usage: restore-all.sh --yes [--dry-run] [--checkpoint ID]... [--keep-backups N]

set -Eeuo pipefail

umask 077

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BENCH_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd -P)"
readonly DEFAULT_SECRET_FILE="/home/wangzuohit/.config/sdd-bench/deepseek-api-key"

DRY_RUN=0
CONFIRMED=0
KEEP_BACKUPS=""
# Filled by validate_secret_file; pre-declared so a --dry-run, which never
# reaches that check, can still print the Compose commands it would run.
SECRET_FILE=""
declare -a REQUESTED=()

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf 'Usage: %s --yes [options]\n\n' "$0" >&2
  printf '  --yes                 required confirmation\n' >&2
  printf '  --dry-run             print the plan, change nothing\n' >&2
  printf '  --checkpoint ID       restore this checkpoint (repeatable);\n' >&2
  printf '                        default is the newest per task\n' >&2
  printf '  --keep-backups N      prune restore-backups/ to the N newest\n' >&2
  printf '  --secret-file PATH    override the API key file\n' >&2
  printf '\nDefault secret: %s\n' "$DEFAULT_SECRET_FILE" >&2
}

# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

while (( $# )); do
  case "$1" in
    --yes) CONFIRMED=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --checkpoint) [[ $# -ge 2 ]] || die "--checkpoint needs a value"; REQUESTED+=("$2"); shift 2 ;;
    --keep-backups) [[ $# -ge 2 ]] || die "--keep-backups needs a value"; KEEP_BACKUPS="$2"; shift 2 ;;
    --secret-file) [[ $# -ge 2 ]] || die "--secret-file needs a value"; DEEPSEEK_API_KEY_FILE="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unknown argument: $1" ;;
  esac
done

if (( ! CONFIRMED && ! DRY_RUN )); then
  usage
  die "explicit --yes confirmation is required"
fi
if [[ -n "$KEEP_BACKUPS" && ! "$KEEP_BACKUPS" =~ ^[0-9]+$ ]]; then
  die "--keep-backups must be a non-negative integer"
fi

for command_name in docker flock id realpath sha256sum stat tar python3; do
  command -v "$command_name" >/dev/null 2>&1 || die "required command not found: ${command_name}"
done

# Every mutating command goes through here, which is what makes --dry-run a
# property of the script rather than of each call site.
run() {
  if (( DRY_RUN )); then
    printf 'DRY: %s\n' "$*"
    return 0
  fi
  "$@"
}

# --------------------------------------------------------------------------
# Secrets
# --------------------------------------------------------------------------

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

# --------------------------------------------------------------------------
# Checkpoint discovery
# --------------------------------------------------------------------------

# The newest checkpoint per task, unless the caller named checkpoints outright.
# Restoring two checkpoints of the same task in sequence would only ever leave
# the last one standing, so "all" has to mean "one per task" to be meaningful.
select_checkpoints() {
  if (( ${#REQUESTED[@]} )); then
    printf '%s\n' "${REQUESTED[@]}"
    return 0
  fi
  python3 - "$SCRIPT_DIR" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
best: dict[str, tuple[str, str]] = {}
for directory in sorted(root.glob("pre-experiment-*")):
    meta = directory / "checkpoint.json"
    if not meta.is_file() or not (directory / "payloads").is_dir():
        continue
    try:
        document = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        continue
    key = document.get("task_id")
    stamp = document.get("created_at_utc", "")
    if key and (key not in best or stamp > best[key][0]):
        best[key] = (stamp, document["checkpoint_id"])
for _, checkpoint_id in sorted(best.values()):
    print(checkpoint_id)
PY
}

# A checkpoint's own metadata, emitted as shell assignments. Nothing is
# hardcoded here: the pinned restore.sh scripts restated all of this by hand,
# which is exactly how they drifted apart.
checkpoint_plan() {
  python3 - "$1" <<'PY'
import json
import shlex
import sys

document = json.loads(open(sys.argv[1], encoding="utf-8").read())
deployment = document["deployment"]
rows = {
    "CP_ID": document["checkpoint_id"],
    "CP_TASK_ID": document["task_id"],
    "CP_BASE_SHA": document["task_base_sha"],
    # Two task generations are recorded here and they restore differently. A
    # batch task's containers live for one run and its HOME is a tmpfs, so its
    # checkpoint carries its own restore procedure; the template task's stack is
    # long-lived and is handled inline below.
    "CP_LIFETIME": deployment.get("container_lifetime", "long-lived"),
    "CP_PROJECT": deployment["compose_project"],
    "CP_AGENT_IMAGE": deployment["agent_image"],
    "CP_AGENT_IMAGE_ID": deployment["agent_image_id"],
    "CP_CONFIG_PAYLOAD": deployment["configuration_payload"],
    "CP_IMAGE_PAYLOAD": deployment["offline_image_payload"],
    "CP_REPOS": " ".join(record["name"] for record in document["repositories"]),
    "CP_HOMES": " ".join(
        f'{record["variant"]}:{record["volume"]}:{record["payload"]}'
        for record in document["home_volumes"]
    ),
}
for key, value in rows.items():
    print(f"{key}={shlex.quote(value)}")
PY
}

# --------------------------------------------------------------------------
# Compose helpers
# --------------------------------------------------------------------------

# project<TAB>compose-file for every stack in a task directory. The literal
# `name:` is the project, which is how a stack started by hand is identified;
# the batch harness instead substitutes ${COMPOSE_PROJECT_NAME} per run, and
# those stacks are the harness's own to tear down.
compose_stacks() {
  local dir="$1" file name
  for file in "$dir"/compose*.yaml "$dir"/compose*.yml; do
    [[ -f "$file" ]] || continue
    name="$(sed -nE 's/^[[:space:]]*name:[[:space:]]*([^[:space:]]+)[[:space:]]*$/\1/p' "$file" | head -1)"
    [[ -n "$name" && "$name" != \$* ]] || continue
    printf '%s\t%s\n' "$name" "$file"
  done
}

project_is_up() {
  [[ -n "$(docker ps -q --filter "label=com.docker.compose.project=$1")" ]]
}

# --------------------------------------------------------------------------
# Volume payloads
# --------------------------------------------------------------------------

backup_volume() {
  local image="$1" volume="$2" destination="$3"
  run docker run --rm --network none --read-only --cap-drop ALL \
    --security-opt no-new-privileges:true --user 1007:1007 \
    -v "${volume}:/source:ro" -v "$(dirname -- "$destination"):/backup:rw" \
    "$image" /bin/sh -c "cd /source && tar -czf /backup/$(basename -- "$destination") ."
}

restore_volume() {
  local image="$1" volume="$2" payload="$3"
  # Compose creates root-owned bind-target placeholders in HOME volumes, so the
  # replacement needs a networkless root helper with only the capabilities that
  # taking ownership of those entries requires.
  run docker run --rm --network none --cap-drop ALL \
    --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
    --security-opt no-new-privileges:true --user 0:0 \
    -v "${volume}:/target:rw" -v "$(dirname -- "$payload"):/payloads:ro" \
    "$image" /bin/sh -c \
      "find /target -mindepth 1 -maxdepth 1 -exec rm -rf -- {} + && tar --same-owner --same-permissions -xzf /payloads/$(basename -- "$payload") -C /target"
}

# --------------------------------------------------------------------------
# One checkpoint
# --------------------------------------------------------------------------

restore_one() {
  local checkpoint_id="$1"
  local checkpoint_dir="${SCRIPT_DIR}/${checkpoint_id}"

  [[ -f "${checkpoint_dir}/checkpoint.json" ]] || die "no checkpoint.json in ${checkpoint_dir}"
  [[ -d "${checkpoint_dir}/payloads" ]] || die "no payloads/ in ${checkpoint_dir}"

  local CP_ID CP_TASK_ID CP_BASE_SHA CP_LIFETIME CP_PROJECT CP_AGENT_IMAGE CP_AGENT_IMAGE_ID
  local CP_CONFIG_PAYLOAD CP_IMAGE_PAYLOAD CP_REPOS CP_HOMES
  eval "$(checkpoint_plan "${checkpoint_dir}/checkpoint.json")"

  # A batch checkpoint carries its own restore procedure, because restoring it
  # means something different: the task has no deployment to restart, its HOME
  # is a tmpfs, and its repositories sit one level deeper than the template
  # task's. Re-implementing that here would only be a second copy to drift.
  if [[ "$CP_LIFETIME" == "per-run" ]]; then
    printf '\n=== %s ===\ntask=%s\n' "$CP_ID" "$CP_TASK_ID"
    if (( DRY_RUN )); then
      run "${checkpoint_dir}/restore.sh" --dry-run
    else
      run "${checkpoint_dir}/restore.sh" --yes
    fi
    printf 'checkpoint_restore=PASS id=%s\n' "$CP_ID"
    return 0
  fi

  local task_dir="${BENCH_ROOT}/tasks/${CP_TASK_ID}"
  local baseline_parent="${BENCH_ROOT}/environments/scrapy__scrapy__base_${CP_BASE_SHA}/baseline"
  local payload_dir="${checkpoint_dir}/payloads"

  [[ -d "$task_dir" ]] || die "task directory is missing: ${task_dir}"
  [[ -d "$baseline_parent" ]] || die "baseline parent is missing: ${baseline_parent}"

  printf '\n=== %s ===\n' "$CP_ID"
  printf 'task=%s project=%s\n' "$CP_TASK_ID" "$CP_PROJECT"

  # 1. Payload integrity first: a restore that starts from an unverified
  #    archive is worse than no restore.
  "${checkpoint_dir}/verify.sh"

  # 2. Which stacks this task owns, and which of them are up right now. Both
  #    facts are read before anything moves, because the answer decides both
  #    what has to come down and what has to come back up.
  local -a stack_projects=() stack_files=() stack_up=()
  local project file variant
  while IFS=$'\t' read -r project file; do
    [[ -n "$project" ]] || continue
    stack_projects+=("$project")
    stack_files+=("$file")
    if project_is_up "$project"; then
      stack_up+=("$project")
    fi
  done < <(compose_stacks "$task_dir")

  (( ${#stack_projects[@]} )) || die "no Compose stack found in ${task_dir}"

  # 3. Images: load only when the pinned ids are genuinely absent.
  local -a missing=()
  if ! docker image inspect "$CP_AGENT_IMAGE_ID" >/dev/null 2>&1; then
    missing+=("$CP_AGENT_IMAGE_ID")
  fi
  if (( ${#missing[@]} )); then
    printf 'loading_checkpoint_images=true payload=%s\n' "$CP_IMAGE_PAYLOAD"
    run docker image load -i "${payload_dir}/${CP_IMAGE_PAYLOAD}"
  fi

  local restore_id
  restore_id="$(date -u +%Y%m%dT%H%M%SZ)"
  local backup_dir="${checkpoint_dir}/restore-backups/${restore_id}"
  printf 'restore_backup=%s\n' "$backup_dir"
  run mkdir -p -- "${backup_dir}/repositories" "${backup_dir}/home-volumes"

  # 4. Down every stack of this task. Stacks are read from disk, so this covers
  #    the base smoke stack that the pinned scripts never touched -- which is
  #    why its containers and volumes survived for nine days. --volumes is
  #    deliberately omitted: a base-stack HOME volume is in no payload.
  local index
  for (( index = 0; index < ${#stack_projects[@]}; index++ )); do
    run env DEEPSEEK_API_KEY_FILE=/dev/null docker compose \
      --project-directory "$task_dir" -f "${stack_files[$index]}" \
      down --remove-orphans
  done

  # 5. Back up what is about to be replaced. Repositories are moved, not
  #    deleted, so a failed restore is reversible by hand from backup_dir.
  local member
  mapfile -t config_members < <(tar -tzf "${payload_dir}/${CP_CONFIG_PAYLOAD}")
  (( ${#config_members[@]} )) || die "deployment config payload is empty"
  run tar -czf "${backup_dir}/deployment-config.tar.gz" -C "$BENCH_ROOT" \
    --ignore-failed-read -- "${config_members[@]}"

  if [[ -d "${baseline_parent}/scrapy" ]]; then
    run mv -- "${baseline_parent}/scrapy" "${backup_dir}/repositories/baseline-scrapy"
  fi
  for variant in $CP_REPOS; do
    [[ "$variant" == "baseline" ]] && continue
    [[ -d "${task_dir}/runs/${variant}/scrapy" ]] || continue
    run mv -- "${task_dir}/runs/${variant}/scrapy" "${backup_dir}/repositories/${variant}-scrapy"
  done
  local record volume_name payload_name
  for record in $CP_HOMES; do
    variant="${record%%:*}"
    volume_name="$(cut -d: -f2 <<<"$record")"
    run backup_volume "$CP_AGENT_IMAGE" "$volume_name" \
      "${backup_dir}/home-volumes/${variant}-home.tar.gz"
  done

  # 6. Put the recorded state back. The deployment configuration is extracted
  #    before Compose is invoked again, so a half-edited Compose file cannot
  #    prevent the rollback it is part of.
  run tar --same-permissions -xzf "${payload_dir}/${CP_CONFIG_PAYLOAD}" -C "$BENCH_ROOT"
  run mkdir -p -- "${baseline_parent}"
  run tar --same-permissions -xzf "${payload_dir}/baseline-repo.tar.gz" -C "$baseline_parent"
  for variant in $CP_REPOS; do
    [[ "$variant" == "baseline" ]] && continue
    run mkdir -p -- "${task_dir}/runs/${variant}"
    run tar --same-permissions -xzf "${payload_dir}/${variant}-repo.tar.gz" -C "${task_dir}/runs/${variant}"
  done
  for record in $CP_HOMES; do
    variant="${record%%:*}"
    volume_name="$(cut -d: -f2 <<<"$record")"
    payload_name="${record##*:}"
    run restore_volume "$CP_AGENT_IMAGE" "$volume_name" "${payload_dir}/${payload_name}"
  done

  # 7. Bring back exactly what was up, plus the checkpoint's own project. The
  #    pinned scripts only ever restored their agent stack, which silently left
  #    a task half-running whenever the base stack had been up too.
  local -A wanted=(["$CP_PROJECT"]=1)
  for project in "${stack_up[@]}"; do
    wanted["$project"]=1
  done
  for (( index = 0; index < ${#stack_projects[@]}; index++ )); do
    project="${stack_projects[$index]}"
    [[ -n "${wanted[$project]:-}" ]] || continue
    if [[ "$project" == "$CP_PROJECT" ]]; then
      run env DEEPSEEK_API_KEY_FILE="$SECRET_FILE" docker compose \
        --project-directory "$task_dir" -f "${stack_files[$index]}" \
        up -d --wait --wait-timeout 120
    else
      run env DEEPSEEK_API_KEY_FILE="$SECRET_FILE" docker compose \
        --project-directory "$task_dir" -f "${stack_files[$index]}" up -d
    fi
  done

  printf 'checkpoint_restore=PASS id=%s backup=%s\n' "$CP_ID" "$backup_dir"
}

# --------------------------------------------------------------------------

prune_backups() {
  [[ -n "$KEEP_BACKUPS" ]] || return 0
  local checkpoint_dir="$1" directory stamps=() index
  directory="${checkpoint_dir}/restore-backups"
  [[ -d "$directory" ]] || return 0
  mapfile -t stamps < <(ls -1 -- "$directory" | sort)
  (( ${#stamps[@]} > KEEP_BACKUPS )) || return 0
  for (( index = 0; index < ${#stamps[@]} - KEEP_BACKUPS; index++ )); do
    printf 'prune_backup=%s\n' "${stamps[$index]}"
    run rm -rf -- "${directory}/${stamps[$index]}"
  done
}

main() {
  (( DRY_RUN )) || validate_secret_file

  local -a selected=()
  mapfile -t selected < <(select_checkpoints)
  (( ${#selected[@]} )) || die "no pre-experiment checkpoint found in ${SCRIPT_DIR}"

  flock -n /tmp/sdd-restore-all.run.lock true || die "another restore-all is running"

  printf 'restore_all_plan=%s\n' "${selected[*]}"
  local checkpoint_id
  for checkpoint_id in "${selected[@]}"; do
    restore_one "$checkpoint_id"
    prune_backups "${SCRIPT_DIR}/${checkpoint_id}"
  done
  printf '\nrestore_all=PASS checkpoints=%s\n' "${#selected[@]}"
}

main "$@"
