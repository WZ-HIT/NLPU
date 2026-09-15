#!/usr/bin/env bash
set -Eeuo pipefail

readonly CHECKPOINT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
readonly PAYLOAD_DIR="${CHECKPOINT_DIR}/payloads"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"
command -v python3 >/dev/null 2>&1 || die "python3 is required"
[[ -f "${CHECKPOINT_DIR}/checkpoint.json" ]] || die "checkpoint.json is missing"
[[ -f "${PAYLOAD_DIR}/SHA256SUMS" ]] || die "payloads/SHA256SUMS is missing"

(
  cd -- "$PAYLOAD_DIR"
  sha256sum --check --strict SHA256SUMS
)

python3 - "$CHECKPOINT_DIR/checkpoint.json" <<'PY'
import hashlib
import json
import pathlib
import re
import sys
import tarfile
import tomllib

path = pathlib.Path(sys.argv[1])
data = json.loads(path.read_text(encoding="utf-8"))
expected = "pre-experiment-pr8073-flash-high-20260914T064502Z"
if data.get("checkpoint_id") != expected:
    raise SystemExit(f"ERROR: unexpected checkpoint_id: {data.get('checkpoint_id')!r}")
if data.get("contains_api_secret") is not False:
    raise SystemExit("ERROR: checkpoint secret-exclusion declaration is missing")
if len(data.get("repositories", [])) != 4:
    raise SystemExit("ERROR: expected four repository records")
if len(data.get("home_volumes", [])) != 3:
    raise SystemExit("ERROR: expected three HOME-volume records")

deployment = data.get("deployment", {})
expected_effort = "high"
expected_profile_sha = "2e594da8abb241ef9c54cc376956a198371d305db4252d21341bd8d4fa1dd029"
expected_catalog_sha = "4240127a851f7582bb4f92b9fe3b258f18393d560446e84430e5f90f473db9a1"
if deployment.get("model_reasoning_effort") != expected_effort:
    raise SystemExit("ERROR: checkpoint metadata does not pin high reasoning effort")
if deployment.get("provider_profile_sha256") != expected_profile_sha:
    raise SystemExit("ERROR: checkpoint metadata has an unexpected provider-profile hash")
if deployment.get("model_catalog_sha256") != expected_catalog_sha:
    raise SystemExit("ERROR: checkpoint metadata has an unexpected model-catalog hash")

payload = path.parent / "payloads" / deployment["configuration_payload"]
prefix = "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates"
members = {
    "profile": f"{prefix}/deepseek-flash.config.toml",
    "catalog": f"{prefix}/model-catalogs/deepseek-flash/models.json",
    "launcher": "tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/run-agent.sh",
}
with tarfile.open(payload, "r:gz") as archive:
    content = {}
    for key, member in members.items():
        stream = archive.extractfile(member)
        if stream is None:
            raise SystemExit(f"ERROR: checkpoint deployment payload is missing {member}")
        content[key] = stream.read()

profile_sha = hashlib.sha256(content["profile"]).hexdigest()
catalog_sha = hashlib.sha256(content["catalog"]).hexdigest()
if profile_sha != expected_profile_sha or catalog_sha != expected_catalog_sha:
    raise SystemExit("ERROR: checkpoint deployment payload has stale model configuration")

profile = tomllib.loads(content["profile"].decode("utf-8"))
catalog = json.loads(content["catalog"].decode("utf-8"))
if profile.get("model") != "deepseek-flash":
    raise SystemExit("ERROR: archived provider profile does not select deepseek-flash")
if profile.get("model_reasoning_effort") != expected_effort:
    raise SystemExit("ERROR: archived provider profile does not use high reasoning effort")
models = catalog.get("models", [])
if len(models) != 1 or models[0].get("slug") != "deepseek-flash":
    raise SystemExit("ERROR: archived model catalog does not contain only deepseek-flash")
if models[0].get("default_reasoning_level") != expected_effort:
    raise SystemExit("ERROR: archived model catalog does not default to high reasoning")

launcher = content["launcher"].decode("utf-8")
for variable, expected_sha in (
    ("EXPECTED_PROFILE_CONFIG_SHA256", expected_profile_sha),
    ("EXPECTED_MODEL_CATALOG_SHA256", expected_catalog_sha),
):
    match = re.search(rf'^readonly {variable}="([0-9a-f]{{64}})"$', launcher, re.MULTILINE)
    if match is None or match.group(1) != expected_sha:
        raise SystemExit(f"ERROR: archived run-agent.sh has stale {variable}")

print(f"checkpoint_metadata=PASS id={expected} reasoning_effort={expected_effort}")
PY

printf 'checkpoint_verification=PASS\n'
