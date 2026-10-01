#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
config=${SDD_BATCH_CONFIG:-"$script_dir/batch/pilot/pr8073-pilot.json"}

if [ "$#" -lt 1 ]; then
  echo "usage: ./run-pilot.sh detect|update|all|inspect|probe|status|evaluate|evaluate-host|report [runner options]" >&2
  exit 2
fi

command=$1
shift
exec "$script_dir/bin/sdd-pilot" "$command" --config "$config" "$@"
