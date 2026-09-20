#!/usr/bin/env bash
# Verify one pre-experiment checkpoint without touching anything.
#
# Checked: every payload against payloads/SHA256SUMS, and every claim in
# checkpoint.json that a restore would act on. Not checked: Docker. This script
# is deliberately usable on a host with no daemon and no images loaded, because
# "is this rollback point intact" has to be answerable before deciding whether
# to reload anything -- the mistake is finding out during a restore.
#
# Usage: verify.sh [CHECKPOINT_DIR]

set -Eeuo pipefail

readonly CHECKPOINT_DIR="$(cd -- "${1:-$(dirname -- "${BASH_SOURCE[0]}")}" && pwd -P)"

failures=0
fail() {
  printf 'FAIL: %s\n' "$*" >&2
  failures=$((failures + 1))
}
note() { printf 'ok: %s\n' "$*"; }

[[ -f "${CHECKPOINT_DIR}/checkpoint.json" ]] || { echo "FAIL: no checkpoint.json" >&2; exit 1; }
[[ -d "${CHECKPOINT_DIR}/payloads" ]] || { echo "FAIL: no payloads/" >&2; exit 1; }

printf 'checkpoint=%s\n' "$(basename -- "$CHECKPOINT_DIR")"

# --------------------------------------------------------------------------
# 1. Payload bytes
# --------------------------------------------------------------------------

if [[ ! -f "${CHECKPOINT_DIR}/payloads/SHA256SUMS" ]]; then
  fail "payloads/SHA256SUMS is missing"
elif ( cd "${CHECKPOINT_DIR}/payloads" && sha256sum --check --status SHA256SUMS ); then
  note "payload checksums"
else
  fail "payload checksums do not match SHA256SUMS"
  ( cd "${CHECKPOINT_DIR}/payloads" && sha256sum --check SHA256SUMS ) >&2 || true
fi

# --------------------------------------------------------------------------
# 2. Metadata, and the join between metadata and payloads
# --------------------------------------------------------------------------

problems="$(python3 - "$CHECKPOINT_DIR" <<'PY'
import json
import pathlib
import sys

directory = pathlib.Path(sys.argv[1])
document = json.loads((directory / "checkpoint.json").read_text(encoding="utf-8"))
problems: list[str] = []

if document.get("schema_version") != 1:
    problems.append("schema_version is not 1")
if document.get("checkpoint_id") != directory.name:
    problems.append(
        f'checkpoint_id {document.get("checkpoint_id")!r} does not match the directory name'
    )
if document.get("contains_api_secret") is not False:
    problems.append("contains_api_secret is not false")
if not document.get("task_id"):
    problems.append("task_id is missing")
if not document.get("task_base_sha"):
    problems.append("task_base_sha is missing")

# An empty home_volumes list is meaningful for a pilot task, not an omission:
# its HOME is a tmpfs. What would be wrong is the key being absent, or the list
# being non-empty while home_kind still claims tmpfs.
if "home_volumes" not in document:
    problems.append("home_volumes is missing entirely")
elif document["home_volumes"] and str(document.get("home_kind", "")).startswith("tmpfs"):
    problems.append("home_volumes is non-empty but home_kind says tmpfs")

repositories = document.get("repositories") or []
if not repositories:
    problems.append("repositories is empty")
if "baseline" not in {record.get("name") for record in repositories}:
    problems.append("no baseline repository is recorded")
for record in repositories:
    if not record.get("head"):
        problems.append(f'repository {record.get("name")!r} has no recorded head')
    if not record.get("payload"):
        problems.append(f'repository {record.get("name")!r} has no payload')

deployment = document.get("deployment") or {}
if not deployment.get("agent_image_id"):
    problems.append("deployment.agent_image_id is missing")
if not deployment.get("configuration_payload"):
    problems.append("deployment.configuration_payload is missing")
if deployment.get("container_lifetime") != "per-run":
    problems.append("deployment.container_lifetime is not per-run")

initial = document.get("initial_workspaces") or []
if len(initial) != len(repositories) - 1:
    problems.append("initial_workspaces does not cover every method repository")
for entry in initial:
    if len(entry.get("initial_workspace_sha256", "")) != 64:
        problems.append(f'method {entry.get("method")!r} has no workspace digest')

# The Detect mount points, which a restore recreates. A checkpoint that records
# a non-empty one was cut after Detect had run, and the digest is what a later
# capture would be compared against -- so both are checked here rather than
# trusted, since "the restore puts an empty directory back" is only correct if
# the directory was empty when recorded.
method_names = {record.get("name") for record in repositories} - {"baseline"}
planning = document.get("detect_planning_artifacts")
if planning is None:
    # Absent, not empty: checkpoints cut before this field existed fall back to
    # the path convention on restore, and are not retroactively wrong -- only
    # less specific than they could be.
    pass
elif {record.get("method") for record in planning} != method_names:
    problems.append("detect_planning_artifacts does not cover every method repository")
else:
    for record in planning:
        method = record.get("method")
        if record.get("empty_at_capture") is not True or record.get("file_count_at_capture") != 0:
            problems.append(f'detect mount point for {method!r} was not empty at capture')
        if len(record.get("manifest_sha256_at_capture", "")) != 64:
            problems.append(f'detect mount point for {method!r} has no manifest digest')
        if record.get("path") != f"runs/{method}/detect/planning-artifacts":
            problems.append(f'detect mount point for {method!r} has an unexpected path')
        if not record.get("container_mount"):
            problems.append(f'detect mount point for {method!r} has no container mount')

# Every payload the document points at must be listed in SHA256SUMS and present
# on disk. A payload on disk that nothing references is harmless; one that is
# referenced but unlisted is exactly the gap a restore would discover too late.
listed: set[str] = set()
sums = directory / "payloads" / "SHA256SUMS"
if sums.is_file():
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.strip():
            listed.add(line.split(maxsplit=1)[1].strip())

referenced = {record["payload"] for record in repositories if record.get("payload")}
referenced.add(deployment.get("configuration_payload"))
referenced.add(deployment.get("offline_image_payload"))
referenced.update(record["payload"] for record in document.get("home_volumes") or [])
for name in sorted(item for item in referenced if item):
    if name not in listed:
        problems.append(f"payload {name!r} is referenced but not listed in SHA256SUMS")
    elif not (directory / "payloads" / name).is_file():
        problems.append(f"payload {name!r} is listed but not present on disk")

for problem in problems:
    print(problem)
PY
)"

if [[ -n "$problems" ]]; then
  while IFS= read -r problem; do fail "$problem"; done <<<"$problems"
else
  note "checkpoint metadata"
fi

# --------------------------------------------------------------------------
# 3. What the checkpoint claims it will restore to
# --------------------------------------------------------------------------

while IFS=$'\t' read -r method digest files; do
  [[ -n "$method" ]] || continue
  note "initial workspace ${method}: ${files} files, ${digest:0:16}"
done < <(python3 - "$CHECKPOINT_DIR/checkpoint.json" <<'PY'
import json
import sys

document = json.loads(open(sys.argv[1], encoding="utf-8").read())
for entry in document.get("initial_workspaces") or []:
    print(
        "\t".join(
            [
                entry.get("method", ""),
                entry.get("initial_workspace_sha256", ""),
                str(entry.get("workspace_file_count", "?")),
            ]
        )
    )
PY
)

while IFS=$'\t' read -r method path mount; do
  [[ -n "$method" ]] || continue
  note "detect mount ${method}: ${path} -> ${mount} (empty)"
done < <(python3 - "$CHECKPOINT_DIR/checkpoint.json" <<'PY'
import json
import sys

document = json.loads(open(sys.argv[1], encoding="utf-8").read())
for record in document.get("detect_planning_artifacts") or []:
    print(
        "\t".join(
            [
                record.get("method", ""),
                record.get("path", ""),
                record.get("container_mount", ""),
            ]
        )
    )
PY
)

printf '\n'
if (( failures )); then
  printf 'checkpoint_verification=FAIL problems=%d\n' "$failures"
  exit 1
fi
printf 'checkpoint_verification=PASS\n'
