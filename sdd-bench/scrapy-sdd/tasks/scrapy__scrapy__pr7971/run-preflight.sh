#!/bin/sh
set -eu
echo 'Use: sdd-batch preflight TASK --run-id <id>' >&2
echo 'This wrapper never starts a formal task or model call.' >&2
exit 64
