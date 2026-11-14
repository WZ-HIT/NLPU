#!/bin/sh
set -eu

BASE_SHA=a6c017c2ca2b8a9bca8b46b692846f492fe77a00
SOURCE_BASELINE='scrapy-sdd-scrapy:base-11079cb1c85b-py311'
SOURCE_BASELINE_ID='sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa'
COMMON_RUNTIME='scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate'
COMMON_RUNTIME_ID='sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9'
BASELINE_TAG="scrapy-sdd-batch-baseline:${BASE_SHA}"
AGENT_TAG="scrapy-sdd-batch-agent:${BASE_SHA}"

IMAGE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BENCH_ROOT=$(CDPATH= cd -- "$IMAGE_DIR/../../.." && pwd)
REPOSITORY_ROOT=$(CDPATH= cd -- "$BENCH_ROOT/../.." && pwd)

actual_source_id=$(docker image inspect "$SOURCE_BASELINE" --format '{{.Id}}')
test "$actual_source_id" = "$SOURCE_BASELINE_ID" || {
  echo "immutable source baseline ID mismatch" >&2
  exit 2
}
actual_runtime_id=$(docker image inspect "$COMMON_RUNTIME" --format '{{.Id}}')
test "$actual_runtime_id" = "$COMMON_RUNTIME_ID" || {
  echo "immutable common runtime ID mismatch" >&2
  exit 2
}

python3 "$IMAGE_DIR/verify-inputs.py" "$REPOSITORY_ROOT" "$BASE_SHA"

docker build --pull=false --network=none --provenance=false \
  --build-arg SOURCE_DATE_EPOCH=0 \
  --build-arg "SOURCE_BASELINE_IMAGE=$SOURCE_BASELINE" \
  --build-context "purebase=$BENCH_ROOT/batch/baselines/$BASE_SHA/repository" \
  --tag "$BASELINE_TAG" \
  --file "$IMAGE_DIR/Dockerfile.baseline" \
  "$IMAGE_DIR"

baseline_id=$(docker image inspect "$BASELINE_TAG" --format '{{.Id}}')
test -n "$baseline_id"

docker build --pull=false --network=none --provenance=false \
  --build-arg SOURCE_DATE_EPOCH=0 \
  --build-arg "BASELINE_IMAGE=$BASELINE_TAG" \
  --build-arg "COMMON_RUNTIME_IMAGE=$COMMON_RUNTIME" \
  --build-context "openspec=$BENCH_ROOT/environments/sdd-tools/openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64" \
  --build-context "ccsdd=$BENCH_ROOT/environments/sdd-tools/cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64" \
  --build-context "speckit=$BENCH_ROOT/environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64" \
  --tag "$AGENT_TAG" \
  --file "$IMAGE_DIR/Dockerfile.agent" \
  "$IMAGE_DIR"

python3 "$IMAGE_DIR/record-deployment.py" "$REPOSITORY_ROOT" "$BASE_SHA" "$BASELINE_TAG" "$AGENT_TAG"
