#!/usr/bin/env bash
# Restore one pre-experiment checkpoint for a batch (pilot) task.
#
# The hand-made 8073 checkpoints restore a *deployment*: they stop Compose,
# refill three named HOME volumes and start the containers again. A pilot task
# has no deployment to restart. Its containers live for one run, its HOME is a
# tmpfs, and every byte SDD can modify sits in the bind-mounted repository at
# runs/<method>/detect/workspace. So this restores those repositories and the
# task's deployment configuration, stops any stray stack that is still up, and
# starts nothing -- there is nothing to start.
#
# It also never opens the API key, because it never runs the launcher.
#
# What it deliberately leaves alone: runs/*/{executions,output,audit}. Those are
# the evidence produced after the moment recorded here, and a rollback that
# erased them would destroy the audit trail it exists to protect. The same rule
# is written into the hand-made checkpoints' README.
#
# Two things it does move rather than leave, into the same backup, because
# leaving them would restore the files without restoring the ability to run:
# the Detect seal (``update/sealed-input``, one-way -- a second Detect refuses
# while it exists) and whatever Detect wrote into its planning-artifacts mount
# point. Neither is deleted, so nothing is lost either way.
#
# Usage: restore.sh --yes [--dry-run]

set -Eeuo pipefail

umask 077

readonly CHECKPOINT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly BENCH_ROOT="$(cd -- "${CHECKPOINT_DIR}/../.." && pwd -P)"

DRY_RUN=0
CONFIRMED=0

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while (( $# )); do
  case "$1" in
    --yes) CONFIRMED=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) printf 'Usage: %s --yes [--dry-run]\n' "$0"; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

if (( ! CONFIRMED && ! DRY_RUN )); then
  die "explicit --yes confirmation is required"
fi

for command_name in docker python3 sha256sum tar stat realpath; do
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
# Metadata
# --------------------------------------------------------------------------

[[ -f "${CHECKPOINT_DIR}/checkpoint.json" ]] || die "no checkpoint.json"

plan() {
  python3 - "$CHECKPOINT_DIR/checkpoint.json" <<'PY'
import json
import shlex
import sys

document = json.loads(open(sys.argv[1], encoding="utf-8").read())
deployment = document["deployment"]
rows = {
    "CP_ID": document["checkpoint_id"],
    "CP_TASK_ID": document["task_id"],
    "CP_BASE_SHA": document["task_base_sha"],
    "CP_PREFIX": deployment.get("compose_project_prefix") or "",
    "CP_CONFIG_PAYLOAD": deployment["configuration_payload"],
    "CP_IMAGE_PAYLOAD": deployment["offline_image_payload"],
    "CP_AGENT_IMAGE_ID": deployment["agent_image_id"],
    "CP_METHODS": " ".join(
        record["name"] for record in document["repositories"] if record["name"] != "baseline"
    ),
    "CP_PLANNING": " ".join(
        f'{record["method"]}:{record["path"]}'
        for record in document.get("detect_planning_artifacts") or []
    ),
}
for key, value in rows.items():
    print(f"{key}={shlex.quote(value)}")
PY
}

eval "$(plan)"

readonly TASK_DIR="${BENCH_ROOT}/tasks/${CP_TASK_ID}"
readonly BASELINE_DIR="${BENCH_ROOT}/batch/baselines/${CP_BASE_SHA}/repository"
readonly PAYLOAD_DIR="${CHECKPOINT_DIR}/payloads"

# The task directory is fatal when missing: it is the only one of the two that
# no payload puts back. The baseline is not, because baseline-repo.tar.gz does
# -- and it is precisely the piece an interrupted restore has already moved
# aside, so refusing here is what made a failed restore need hand recovery
# before it could even be retried.
[[ -d "$TASK_DIR" ]] || die "task directory is missing: ${TASK_DIR}"
[[ -d "$BASELINE_DIR" ]] || printf 'baseline_missing=%s restoring_from_payload=true\n' "$BASELINE_DIR"

printf 'checkpoint=%s\ntask=%s\nbase_sha=%s\n' "$CP_ID" "$CP_TASK_ID" "$CP_BASE_SHA"

# Detect's mount point, read from the checkpoint when it records one. The
# checkpoints cut before that field existed do not, and a missing bind source
# is what stopped every Detect target of the 2026-09-19 rerun -- so for those
# the convention is re-derived rather than the restore refusing to run.
planning_mount() {
  local method="$1" record
  for record in $CP_PLANNING; do
    if [[ "${record%%:*}" == "$method" ]]; then
      printf '%s\n' "${TASK_DIR}/${record#*:}"
      return 0
    fi
  done
  # stderr: this function's stdout *is* the path.
  printf 'planning_mount_source=convention method=%s\n' "$method" >&2
  printf '%s\n' "${TASK_DIR}/runs/${method}/detect/planning-artifacts"
}

# Resolved once: each path is used by three separate steps -- move aside,
# recreate, chmod -- and asking per use would print the fallback notice three
# times per method.
declare -A PLANNING_DIR=()
for method in $CP_METHODS; do
  PLANNING_DIR["$method"]="$(planning_mount "$method")"
done

# --------------------------------------------------------------------------
# Payload integrity first
# --------------------------------------------------------------------------

"${CHECKPOINT_DIR}/verify.sh" || die "checkpoint verification failed; refusing to restore"

# --------------------------------------------------------------------------
# Stop whatever is still up for this task
# --------------------------------------------------------------------------
#
# Found through Docker's own project label rather than by re-reading a Compose
# file, because the harness substitutes a project name per run and there is no
# single file that names it. Going through the label is also what makes an
# *exited* container, or a network left behind by one, exactly as visible as a
# running one -- the miss that let a stray stack survive a restore that claimed
# to be complete.

live_projects() {
  docker ps -a --format '{{.Label "com.docker.compose.project"}}' 2>/dev/null \
    | sort -u | grep -E "^${CP_PREFIX}" || true
}

reclaim() {
  local label="label=com.docker.compose.project=$1"
  local ids
  for spec in "ps -aq|rm -f" "network ls -q|network rm" "volume ls -q|volume rm"; do
    ids="$(docker ${spec%%|*} --filter "$label" 2>/dev/null || true)"
    if [[ -n "$ids" ]]; then
      printf 'reclaim project=%s %s\n' "$1" "${spec%%|*}"
      # shellcheck disable=SC2086
      run docker ${spec##*|} $ids
    fi
  done
}

changed=0
while IFS= read -r project; do
  [[ -n "$project" ]] || continue
  changed=1
  reclaim "$project"
done < <(live_projects)

(( changed )) || printf 'live_stacks=none prefix=%s\n' "$CP_PREFIX"

# --------------------------------------------------------------------------
# Back up what is about to be replaced
# --------------------------------------------------------------------------
#
# Repositories are moved, never deleted, so a restore that fails halfway is
# reversible by hand from this directory.

readonly RESTORE_ID="$(date -u +%Y%m%dT%H%M%SZ)"
readonly BACKUP_DIR="${CHECKPOINT_DIR}/restore-backups/${RESTORE_ID}"
printf 'restore_backup=%s\n' "$BACKUP_DIR"
run mkdir -p -- "${BACKUP_DIR}/repositories"

run tar -czf "${BACKUP_DIR}/deployment-config.tar.gz" -C "$BENCH_ROOT" \
  --ignore-failed-read -- \
  $(python3 -c "
import json,sys
document = json.loads(open(sys.argv[1], encoding='utf-8').read())
print(' '.join(document['deployment']['configuration_members']))
" "$CHECKPOINT_DIR/checkpoint.json")

# Read-only directories are part of the recorded state: the baseline tree ships
# with a sealed read-only parent, and a sealed workspace is read-only itself.
# Two separate permissions block a rename, and missing either one produces the
# same bare "Permission denied":
#
#   * the moved directory needs to be writable, because the rename rewrites its
#     own ``..`` entry -- this is what stopped six of nine sealed directories
#     from moving during the 2026-09 rerun;
#   * the *parent* needs to be writable, because the rename edits the parent's
#     directory entry -- this is what stopped the baseline move here, since
#     batch/baselines/<sha> is mode 500.
#
# Both are opened up, and both are put back once the tree is in place again.
declare -a MODE_RECORDS=()
declare -A MODE_SEEN=()

record_mode() {
  local path="$1" mode
  [[ -e "$path" ]] || return 0
  # Idempotent on purpose: the same directory is opened once for the move and
  # again for the extraction that follows it, and the second look would read
  # back the loosened mode and record that as the one to return to.
  [[ -z "${MODE_SEEN[$path]:-}" ]] || return 0
  MODE_SEEN["$path"]=1
  mode="$(stat -c '%a' -- "$path")"
  MODE_RECORDS+=("${mode}"$'\t'"${path}")
  run chmod u+w -- "$path"
}

restore_modes() {
  (( ${#MODE_RECORDS[@]} )) || return 0
  if (( DRY_RUN )); then
    printf 'DRY: restore %d directory modes\n' "${#MODE_RECORDS[@]}"
    return 0
  fi
  local record mode path
  for record in "${MODE_RECORDS[@]}"; do
    mode="${record%%$'\t'*}"
    path="${record#*$'\t'}"
    [[ -e "$path" ]] && chmod "$mode" -- "$path"
  done
}

move_aside() {
  local source="$1" destination="$2"
  [[ -e "$source" ]] || return 0
  record_mode "$(dirname -- "$source")"
  record_mode "$source"
  # The destination's own parent is made here rather than by a single up-front
  # mkdir: the seal and the mount points were added as second and third kinds
  # of thing this script moves, and the up-front version only ever created the
  # repositories directory. Whichever helper owns the precondition cannot be
  # forgotten by the next thing added.
  run mkdir -p -- "$(dirname -- "$destination")"
  run mv -- "$source" "$destination"
}

move_aside "$BASELINE_DIR" "${BACKUP_DIR}/repositories/baseline"
for method in $CP_METHODS; do
  move_aside "${TASK_DIR}/runs/${method}/detect/workspace" \
    "${BACKUP_DIR}/repositories/${method}"
  # The Detect seal is one-way: batch/stages.py refuses to seal a second time
  # while sealed-input exists. Restoring the workspace but leaving the seal
  # would put the files back without putting back the ability to run Detect,
  # which is the whole point of a rollback. Moved, never deleted: the sealed
  # bubble is the Detect evidence, and it survives in the backup.
  move_aside "${TASK_DIR}/runs/${method}/update/sealed-input" \
    "${BACKUP_DIR}/sealed-input/${method}"
  # Whatever Detect wrote into its mount point is likewise post-capture state.
  # Moving it is what lets the next Detect start from an empty mount point
  # instead of inheriting the previous run's planning artifacts.
  move_aside "${PLANNING_DIR[$method]}" "${BACKUP_DIR}/planning-artifacts/${method}"
done

# --------------------------------------------------------------------------
# Put the recorded state back
# --------------------------------------------------------------------------

run tar --same-permissions -xzf "${PAYLOAD_DIR}/${CP_CONFIG_PAYLOAD}" -C "$BENCH_ROOT"

# Recreating a tree means creating its directory entry, so the parent has to be
# writable for the same reason the move did.
extract_into() {
  local payload="$1" target="$2"
  record_mode "$(dirname -- "$target")"
  run mkdir -p -- "$target"
  run tar --same-permissions -xzf "${PAYLOAD_DIR}/${payload}" -C "$target"
}

extract_into baseline-repo.tar.gz "$BASELINE_DIR"
for method in $CP_METHODS; do
  extract_into "${method}-repo.tar.gz" "${TASK_DIR}/runs/${method}/detect/workspace"
done

# The mount point has to exist again before Compose renders. The Detect service
# binds it with ``create_host_path: false``, so a missing directory does not
# produce an empty mount -- it produces no container at all. Scaffolding makes
# it, empty, at task creation and nothing recreates it; that is the recorded
# state, so that is what is put back. Mode 775 matches what Scaffolding created
# rather than this script's umask, so a restored tree is indistinguishable from
# a freshly scaffolded one.
for method in $CP_METHODS; do
  record_mode "${TASK_DIR}/runs/${method}/detect"
  run mkdir -p -- "${PLANNING_DIR[$method]}"
  run chmod 775 -- "${PLANNING_DIR[$method]}"
done

restore_modes

# --------------------------------------------------------------------------
# The acceptance test is the harness's own
# --------------------------------------------------------------------------
#
# _workspace_content_sha256 is the digest batch/stages.py checks before it will
# seal a Detect run. Re-deriving it here rather than reimplementing it is the
# point: a restore judged by a second implementation of the gate can pass while
# the gate it is meant to satisfy would still refuse.

if (( DRY_RUN )); then
  printf '\nDRY: skipping workspace re-verification\n'
  exit 0
fi

python3 - "$BENCH_ROOT" "$TASK_DIR" <<'PY' || die "restored workspace does not match its frozen digest"
import json
import sys
from pathlib import Path

bench = Path(sys.argv[1])
task_dir = Path(sys.argv[2])
sys.path.insert(0, str(bench))
from batch.stages import _workspace_content_sha256

lock = json.loads((task_dir / "initial-workspaces.json").read_text(encoding="utf-8"))
problems = []
for entry in lock["workspaces"]:
    method = entry["method"]
    workspace = task_dir / entry["detect_workspace"]
    actual = _workspace_content_sha256(workspace)
    status = "MATCH" if actual == entry["initial_workspace_sha256"] else "DRIFT"
    print(f"workspace {method:<9} {status}")
    if status == "DRIFT":
        problems.append(f"{method} workspace")

    # The mount point and the seal are the two facts that decide whether Detect
    # can run again at all, so "the files came back" is not the whole test. A
    # missing mount point is what failed all nine targets on 2026-09-19, and a
    # surviving seal is one-way in the other direction.
    mount = task_dir / "runs" / method / "detect" / "planning-artifacts"
    if not mount.is_dir():
        print(f"mount     {method:<9} MISSING")
        problems.append(f"{method} mount point")
    elif any(mount.iterdir()):
        print(f"mount     {method:<9} NOT_EMPTY")
        problems.append(f"{method} mount point")
    else:
        print(f"mount     {method:<9} EMPTY")

    seal = task_dir / "runs" / method / "update" / "sealed-input"
    if seal.exists():
        print(f"seal      {method:<9} STILL_PRESENT")
        problems.append(f"{method} seal")
    else:
        print(f"seal      {method:<9} ABSENT")

if problems:
    print(f"state that did not come back: {', '.join(problems)}", file=sys.stderr)
    raise SystemExit(1)
PY

printf '\ncheckpoint_restore=PASS id=%s backup=%s\n' "$CP_ID" "$BACKUP_DIR"
