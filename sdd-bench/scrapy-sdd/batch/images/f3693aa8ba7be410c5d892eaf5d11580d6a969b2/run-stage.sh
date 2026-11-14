#!/bin/sh
set -eu

if [ "$#" -lt 4 ]; then
  echo "usage: $0 detect|update openspec|speckit|cc-sdd WORKSPACE OUTPUT [COMMAND ...]" >&2
  exit 64
fi

stage=$1
tool=$2
workspace=$(realpath "$3")
output=$(realpath "$4")
shift 4

case "$stage" in detect|update) ;; *) echo "invalid stage" >&2; exit 64 ;; esac
case "$tool" in openspec|speckit|cc-sdd) ;; *) echo "invalid SDD tool" >&2; exit 64 ;; esac
test -d "$workspace/scrapy" && test -d "$workspace/tests"
test -d "$output"
if [ "$#" -eq 0 ]; then
  set -- sleep infinity
fi

run_id="f3693aa8ba7b-${tool}-${stage}-$(date -u +%Y%m%dT%H%M%SZ)-$$"
image='scrapy-sdd-batch-agent:f3693aa8ba7be410c5d892eaf5d11580d6a969b2'

if [ "$stage" = detect ]; then
  planning=$(realpath "$output/../planning-artifacts")
  test -d "$planning"
  case "$tool" in
    openspec) planning_target=/workspace/openspec/changes ;;
    speckit) planning_target=/workspace/specs ;;
    cc-sdd) planning_target=/workspace/.kiro/specs ;;
  esac
  exec docker run --rm --name "sdd-$run_id" --network none --read-only     --cap-drop ALL --security-opt no-new-privileges:true     --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=2147483648     --tmpfs /run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=1073741824     --mount "type=bind,src=$workspace,dst=/workspace,readonly"     --mount "type=bind,src=$planning,dst=$planning_target"     --mount "type=bind,src=$output,dst=/output"     --env "SDD_STAGE=$stage" --env "SDD_TOOL=$tool" --env "SDD_RUN_ID=$run_id"     "$image" "$@"
fi

exec docker run --rm --name "sdd-$run_id" --network none --read-only   --cap-drop ALL --security-opt no-new-privileges:true   --tmpfs /tmp:rw,nosuid,nodev,mode=1777,size=2147483648   --tmpfs /run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=1073741824   --mount "type=bind,src=$workspace,dst=/workspace,readonly"   --mount "type=bind,src=$workspace/tests,dst=/workspace/tests"   --mount "type=bind,src=$output,dst=/output"   --env "SDD_STAGE=$stage" --env "SDD_TOOL=$tool" --env "SDD_RUN_ID=$run_id"   "$image" "$@"
