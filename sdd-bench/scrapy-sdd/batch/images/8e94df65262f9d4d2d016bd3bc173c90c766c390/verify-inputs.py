#!/usr/bin/env python3
"""Fail-closed verification for immutable, gold-blind image build inputs."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


EXPECTED = {
    "environments/sdd-tools/openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64/package-lock.json": "c91b3c7c1dd3abf597291759371c9bf34b24f6bd8a04a580f20ab3af3864081f",
    "environments/sdd-tools/openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64/npm-artifacts/artifact-manifest.json": "fb9ee0748d19a1f956867184488abfb2d3b3dbff4d33f4e1bbe982713cec3d74",
    "environments/sdd-tools/cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64/package-lock.json": "933c67ed634facbb5a724d45cb05089b0ac7bb31e7664489879a9ca9cf300000",
    "environments/sdd-tools/cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64/npm-artifacts/artifact-manifest.json": "b4b8ce58e82144f5b85f36396313673b42e570f9fe7325368ea6dcd5e8b90f5d",
    "environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/artifact-manifest.json": "02341f37f1977a1e8ef4ce401a57e573b97778f22ce6389b954b155ec3f389e8",
    "environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/install-requirements.txt": "82bf7f378fb41407beae68fbe90e21995c41e234e8343a30448b89067419562b",
    "environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/dist/specify_cli-1.0.4-py3-none-any.whl": "6dea3ff784224dde35fd02d265462ddb3c4bfc97d1184127fcc71106a233d880",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def main() -> None:
    repository_root = Path(sys.argv[1]).resolve()
    base_sha = sys.argv[2]
    bench = repository_root / "sdd-bench/scrapy-sdd"
    cache = bench / "batch/baselines" / base_sha
    lock = json.loads((cache / "baseline-lock.json").read_text())
    if lock["base_sha"] != base_sha:
        raise SystemExit("baseline lock base mismatch")
    if git(cache / "repository", "rev-parse", "HEAD") != base_sha:
        raise SystemExit("baseline repository HEAD mismatch")
    if git(cache / "repository", "rev-parse", "HEAD^{tree}") != lock["tree_sha"]:
        raise SystemExit("baseline repository tree mismatch")
    for relative, expected in EXPECTED.items():
        path = bench / relative
        actual = sha256(path)
        if actual != expected:
            raise SystemExit(f"locked build input mismatch: {relative}: {actual}")
    image_dir = Path(__file__).resolve().parent
    forbidden = (
        b"raw_prs", b"gold_patch", b"gold_test", b"TEST_ONLY_PR",
        b"MIXED_CODE_AND_TEST_PR", b"comparison-007",
    )
    build_context_files = {
        "Dockerfile.baseline", "Dockerfile.agent", "entrypoint.sh", "sitecustomize.py"
    }
    for name in sorted(build_context_files):
        data = (image_dir / name).read_bytes()
        hits = [token.decode() for token in forbidden if token in data]
        if hits:
            raise SystemExit(f"forbidden host-only marker in build context file {name}: {hits}")
    print(json.dumps({"status": "PASS", "base_sha": base_sha, "tree_sha": lock["tree_sha"], "locked_inputs": len(EXPECTED)}))


if __name__ == "__main__":
    main()
