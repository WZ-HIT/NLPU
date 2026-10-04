#!/bin/sh
set -eu

case "${SDD_STAGE:-}" in
  detect|update) ;;
  *) echo "SDD_STAGE must be exactly detect or update" >&2; exit 64 ;;
esac

case "${SDD_TOOL:-}" in
  openspec|speckit|cc-sdd) ;;
  *) echo "SDD_TOOL must be exactly openspec, speckit, or cc-sdd" >&2; exit 64 ;;
esac

test "${HOME:-}" = /run/sdd-home || {
  echo "HOME must be a fresh /run/sdd-home tmpfs" >&2
  exit 65
}
test -d /workspace && test -d /workspace/scrapy && test -d /workspace/tests || {
  echo "workspace is missing adapter-required paths" >&2
  exit 66
}
test -d /output && test -w /output || {
  echo "/output must be an independent writable stage output" >&2
  exit 66
}

python - <<'PY'
import os
import pathlib

stage = os.environ["SDD_STAGE"]

def readonly(path: str) -> bool:
    return bool(os.statvfs(path).f_flag & os.ST_RDONLY)

if not readonly("/workspace/scrapy"):
    raise SystemExit("production path /workspace/scrapy must be read-only")
if stage == "detect":
    for path in ("/workspace", "/workspace/tests"):
        if not readonly(path):
            raise SystemExit(f"detect requires read-only mount: {path}")
    planning = {
        "openspec": "/workspace/openspec/changes",
        "speckit": "/workspace/specs",
        "cc-sdd": "/workspace/.kiro/specs",
    }[os.environ["SDD_TOOL"]]
    if readonly(planning) or not os.access(planning, os.W_OK):
        raise SystemExit(f"detect planning mount must be writable: {planning}")
else:
    if readonly("/workspace/tests"):
        raise SystemExit("update requires a dedicated writable /workspace/tests mount")
if readonly("/run/sdd-home"):
    raise SystemExit("HOME must be writable tmpfs")
PY

mkdir -p "$HOME" "$XDG_CACHE_HOME" "$CODEX_HOME"
marker="$HOME/.sdd-stage-started"
( set -C; printf '%s\n' "$SDD_STAGE:$SDD_TOOL:${SDD_RUN_ID:-unset}" > "$marker" ) 2>/dev/null || {
  echo "HOME is not fresh; refusing stage/session reuse" >&2
  exit 67
}

umask 077
exec "$@"
