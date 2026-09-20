#!/usr/bin/env python3
"""Record immutable images and perform host-only image/runtime audits."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if check and result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {args!r}\n"
            + result.stderr.decode(errors="replace")[-4000:]
        )
    return result


def docker_inspect(image: str) -> dict[str, Any]:
    return json.loads(run("docker", "image", "inspect", image).stdout)[0]


def docker_output(image: str, entrypoint: str, *args: str) -> str:
    return run(
        "docker", "run", "--rm", "--network", "none",
        "--tmpfs", "/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007",
        "--env", "SDD_AGENT_NO_TESTS=0", "--entrypoint", entrypoint,
        image, *args,
    ).stdout.decode().strip()


def normalized_lines(value: str) -> tuple[list[str], str]:
    lines = sorted(line for line in value.splitlines() if line)
    normalized = ("\n".join(lines) + "\n").encode()
    return lines, sha256_bytes(normalized)


def make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISLNK(mode):
            path.chmod(mode | stat.S_IWUSR)


def tracked_manifest(repo: Path, paths: list[str]) -> str:
    entries = []
    for relative in paths:
        path = repo / relative
        data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
        entries.append({"path": relative, "sha256": sha256_bytes(data)})
    return sha256_bytes(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())


# Scrapy is reinstalled from each base's own tree, so the installed revision is
# a property of the base rather than a fixed toolchain version. Comparing the
# two trees is the only check that sees this: the pattern-based leak scan below
# exempts /opt/scrapy-source by path and has no source-code patterns, so a
# stale install is invisible to it. Runs inside the baseline image with no
# network, and ignores __pycache__ because the smoke test imports from a bind
# mount, not from this copy.
VERIFY_SCRAPY_PROGRAM = r"""
import hashlib, json, pathlib, sys

def manifest(root):
    root = pathlib.Path(root)
    if not root.is_dir():
        return None
    files = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files

installed = manifest(sys.argv[1])
base = manifest(sys.argv[2])
extra = sorted(set(installed or {}) - set(base or {}))
missing = sorted(set(base or {}) - set(installed or {}))
differing = sorted(
    name for name, digest in (installed or {}).items()
    if (base or {}).get(name) != digest
)
print(json.dumps({
    "status": "PASS" if installed is not None and installed == base else "FAIL",
    "installed_root_exists": installed is not None,
    "installed_files": len(installed or {}),
    "base_files": len(base or {}),
    "extra_in_installed": extra,
    "missing_from_installed": missing,
    "differing": differing,
}))
"""


def verify_installed_scrapy(baseline_image: str) -> dict[str, Any]:
    return json.loads(
        docker_output(
            baseline_image, "/usr/local/bin/python", "-c", VERIFY_SCRAPY_PROGRAM,
            "/usr/local/lib/python3.11/site-packages/scrapy", "/workspace/scrapy",
        )
    )


def sensitive_patterns(repository_root: Path, baseline_lock: dict[str, Any]) -> dict[str, bytes]:
    raw_path = repository_root / baseline_lock["raw_source"]["path"]
    line_number = baseline_lock["raw_source"]["line_number"]
    raw_line = raw_path.read_bytes().splitlines(keepends=True)[line_number - 1]
    record = json.loads(raw_line)
    patterns: dict[str, bytes] = {
        "raw_record": raw_line.strip(),
        "classification_test_only": b"TEST_ONLY_PR",
        "classification_mixed": b"MIXED_CODE_AND_TEST_PR",
    }
    for key in ("head_sha", "merge_commit_sha"):
        value = record.get(key)
        if isinstance(value, str) and len(value) == 40:
            patterns[key] = value.encode()

    def visit(value: Any, prefix: str = "raw") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"patch", "gold_patch", "gold_test", "focal_method_after"}:
                    if isinstance(child, str) and len(child.encode()) >= 32:
                        patterns[f"{prefix}.{key}"] = child.encode()
                visit(child, f"{prefix}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{prefix}[{index}]")

    visit(record)
    for index, change in enumerate(record.get("test_changes", [])):
        value = change.get("file") if isinstance(change, dict) else None
        if isinstance(value, str) and value:
            patterns[f"gold_test_path[{index}]"] = value.encode()
    return patterns


def scan_added_layers(image: str, baseline_layer_count: int, patterns: dict[str, bytes]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="sdd-image-save-") as temporary:
        archive_path = Path(temporary) / "image.tar"
        run("docker", "image", "save", "--output", str(archive_path), image)
        hits: list[dict[str, str]] = []
        with tarfile.open(archive_path) as outer:
            manifest = json.loads(outer.extractfile("manifest.json").read())[0]
            layers = manifest["Layers"]
            for layer_index, layer_name in enumerate(layers[baseline_layer_count:], start=baseline_layer_count):
                layer_stream = outer.extractfile(layer_name)
                with tarfile.open(fileobj=layer_stream, mode="r|*") as layer:
                    for member in layer:
                        name_bytes = member.name.encode(errors="surrogateescape")
                        for label, pattern in patterns.items():
                            if pattern and pattern in name_bytes:
                                hits.append({"scope": f"layer-{layer_index}-path", "pattern": label})
                        if member.isfile() and member.size <= 32 * 1024 * 1024:
                            data = layer.extractfile(member).read()
                            for label, pattern in patterns.items():
                                if pattern and pattern in data:
                                    hits.append({"scope": f"layer-{layer_index}-content", "pattern": label})
        return {"status": "PASS" if not hits else "FAIL", "added_layer_count": len(layers) - baseline_layer_count, "hits": hits}


def scan_image_filesystem(
    image: str, patterns: dict[str, bytes], baseline_paths: set[str]
) -> dict[str, Any]:
    """Scan the merged image filesystem while excluding only baseline-native path names."""
    with tempfile.TemporaryDirectory(prefix="sdd-image-export-") as temporary:
        archive_path = Path(temporary) / "filesystem.tar"
        container_id = run("docker", "create", image).stdout.decode().strip()
        try:
            run("docker", "export", "--output", str(archive_path), container_id)
        finally:
            run("docker", "container", "rm", "--force", container_id, check=False)
        hits: list[dict[str, str]] = []
        regular_files = 0
        with tarfile.open(archive_path) as filesystem:
            for member in filesystem:
                normalized_name = member.name.lstrip("./")
                baseline_native = normalized_name == "opt/scrapy-source" or normalized_name.startswith("opt/scrapy-source/")
                name_bytes = member.name.encode(errors="surrogateescape")
                if not baseline_native:
                    for label, pattern in patterns.items():
                        baseline_test_path = (
                            label.startswith("gold_test_path[")
                            and normalized_name.startswith("workspace/")
                            and normalized_name.removeprefix("workspace/") in baseline_paths
                            and normalized_name.removeprefix("workspace/").encode() == pattern
                        )
                        if baseline_test_path:
                            continue
                        if pattern and pattern in name_bytes:
                            hits.append({"scope": "filesystem-path", "pattern": label})
                if member.isfile() and member.size <= 32 * 1024 * 1024:
                    regular_files += 1
                    data = filesystem.extractfile(member).read()
                    for label, pattern in patterns.items():
                        if pattern and pattern in data:
                            hits.append({"scope": "filesystem-content", "pattern": label})
        return {"status": "PASS" if not hits else "FAIL", "regular_files_scanned": regular_files, "hits": hits}


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen artifact: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


def main() -> None:
    repository_root = Path(sys.argv[1]).resolve()
    base_sha, baseline_image, agent_image = sys.argv[2:5]
    bench = repository_root / "sdd-bench/scrapy-sdd"
    image_dir = bench / "batch/images" / base_sha
    baseline_lock = json.loads((bench / "batch/baselines" / base_sha / "baseline-lock.json").read_text())
    adapter = json.loads((bench / "adapters/scrapy.json").read_text())
    baseline_inspect = docker_inspect(baseline_image)
    agent_inspect = docker_inspect(agent_image)
    if agent_inspect["Config"]["Labels"]["bench.base-sha"] != base_sha:
        raise RuntimeError("agent image base label mismatch")

    print("audit: collecting runtime versions", flush=True)
    versions = {
        "python": docker_output(agent_image, "/usr/local/bin/python", "-c", "import sys; print(sys.version.split()[0])"),
        "scrapy": docker_output(agent_image, "/usr/local/bin/python", "-c", "import importlib.metadata as m; print(m.version('Scrapy'))"),
        "pytest": docker_output(agent_image, "/usr/local/bin/python", "-c", "import importlib.metadata as m; print(m.version('pytest'))"),
        "node": docker_output(agent_image, "/opt/agent/node/bin/node", "--version"),
        "npm": docker_output(agent_image, "/opt/agent/node/bin/npm", "--version"),
        "codex": docker_output(agent_image, "/opt/agent/bin/codex", "--version"),
        "uv": docker_output(agent_image, "/opt/agent/bin/uv", "--version"),
        "bubblewrap": docker_output(agent_image, "/opt/agent/bwrap/bin/bwrap", "--version"),
        "openspec": docker_output(agent_image, "/opt/sdd-tools/bin/openspec", "--version"),
        "speckit": docker_output(agent_image, "/opt/sdd-tools/bin/specify", "--version"),
        "cc-sdd": docker_output(agent_image, "/opt/sdd-tools/bin/cc-sdd", "--version"),
    }
    print("audit: verifying the installed Scrapy is the frozen base tree", flush=True)
    scrapy_provenance = verify_installed_scrapy(baseline_image)
    if scrapy_provenance["status"] != "PASS":
        raise RuntimeError(f"installed Scrapy is not the base tree: {scrapy_provenance!r}")
    # Every other entry below is a toolchain version pinned across every base,
    # so a literal is the right freeze. Scrapy is not: it is the base's own
    # revision, and it read "2.18.0" here only while every image inherited the
    # root checkout's install. Taking it from the base tree keeps the check
    # meaningful (the agent image must report what the base tree says) without
    # pinning every future base to one revision.
    frozen_scrapy_version = docker_output(baseline_image, "/bin/cat", "/workspace/scrapy/VERSION")
    expected_versions = {
        "python": "3.11.15", "scrapy": frozen_scrapy_version, "pytest": "9.1.1",
        "node": "v24.20.0", "npm": "11.19.0", "codex": "codex-cli 0.153.4",
        "uv": "uv 0.12.10 (x86_64-unknown-linux-gnu)",
        "bubblewrap": "bubblewrap built for Codex", "openspec": "1.12.0",
        "speckit": "specify 1.0.4", "cc-sdd": "cc-sdd v3.0.2",
    }
    if versions != expected_versions:
        raise RuntimeError(f"runtime versions differ: {versions!r}")

    python_freeze, python_freeze_sha = normalized_lines(
        docker_output(agent_image, "/usr/local/bin/python", "-m", "pip", "freeze", "--all")
    )
    dpkg_lock, dpkg_lock_sha = normalized_lines(
        docker_output(agent_image, "/usr/bin/dpkg-query", "-W", "-f=${Package}=${Version}\\n")
    )
    speckit_freeze, speckit_freeze_sha = normalized_lines(
        docker_output(agent_image, "/opt/agent/bin/uv", "pip", "freeze", "--python", "/opt/sdd-tools/speckit/bin/python")
    )

    print("audit: running disposable baseline smoke test", flush=True)
    # The smoke target is frozen into this per-base audit, and gold-check hashes
    # that audit into every task's isolation evidence. Reading it from the shared
    # adapter made a permanent per-base artifact point at a file some candidate
    # pull request edits, so a recipe may pin its own. Directories built before
    # that option existed have no smoke-test.json and keep the adapter's target.
    smoke_config_path = image_dir / "smoke-test.json"
    if smoke_config_path.is_file():
        smoke_argv = json.loads(smoke_config_path.read_text())["argv"]
        smoke_source = "image-dir"
    else:
        smoke_argv = adapter["smoke_test"]["argv"]
        smoke_source = "adapter"
    tracked_paths = [item["path"] for item in baseline_lock["checkout_files"]]
    cache_repo = bench / "batch/baselines" / base_sha / "repository"
    frozen_manifest_before = tracked_manifest(cache_repo, tracked_paths)
    with tempfile.TemporaryDirectory(prefix="sdd-smoke-") as temporary:
        smoke_repo = Path(temporary) / "repository"
        shutil.copytree(cache_repo, smoke_repo, symlinks=True)
        make_writable(smoke_repo)
        disposable_before = tracked_manifest(smoke_repo, tracked_paths)
        smoke = run(
            "docker", "run", "--rm", "--network", "none", "--user", "1007:1007",
            "--workdir", "/workspace", "--tmpfs", "/tmp:rw,nosuid,nodev,mode=1777",
            "--mount", f"type=bind,src={smoke_repo},dst=/workspace",
            "--entrypoint", "/usr/local/bin/python", baseline_image,
            *smoke_argv[1:],
            check=False,
        )
        disposable_after = tracked_manifest(smoke_repo, tracked_paths)
        smoke_status = "PASS" if smoke.returncode == 0 and disposable_before == disposable_after else "FAIL"
        smoke_record = {
            "status": smoke_status,
            "exit_code": smoke.returncode,
            "argv": smoke_argv,
            "source": smoke_source,
            "stdout_tail": smoke.stdout.decode(errors="replace")[-2000:],
            "stderr_tail": smoke.stderr.decode(errors="replace")[-2000:],
            "tracked_manifest_before": disposable_before,
            "tracked_manifest_after": disposable_after,
            "frozen_cache_manifest_before": frozen_manifest_before,
            "frozen_cache_manifest_after": tracked_manifest(cache_repo, tracked_paths),
        }
    if smoke_record["status"] != "PASS" or smoke_record["frozen_cache_manifest_before"] != smoke_record["frozen_cache_manifest_after"]:
        raise RuntimeError(f"smoke validation failed: {smoke_record!r}")

    print("audit: validating fresh detect/update containers", flush=True)
    with tempfile.TemporaryDirectory(prefix="sdd-stage-audit-") as temporary:
        root = Path(temporary)
        stage_records = []
        container_ids = []
        for stage in ("detect", "update"):
            workspace = root / stage / "workspace"
            output = root / stage / "output"
            shutil.copytree(cache_repo, workspace, symlinks=True)
            make_writable(workspace)
            if stage == "detect":
                (workspace / "openspec/changes").mkdir(parents=True, exist_ok=True)
            output.mkdir(parents=True)
            (output.parent / "planning-artifacts").mkdir()
            command = [str(image_dir / "run-stage.sh"), stage, "openspec", str(workspace), str(output), "/bin/sh", "-c", "cat /etc/hostname"]
            result = run(*command, check=False)
            container_id = result.stdout.decode().strip().splitlines()[-1] if result.stdout.strip() else ""
            container_ids.append(container_id)
            stage_records.append({"stage": stage, "exit_code": result.returncode, "container_id": container_id})
        if any(item["exit_code"] for item in stage_records) or len(set(container_ids)) != 2:
            raise RuntimeError(f"fresh stage container validation failed: {stage_records!r}")

    print("audit: scanning history, agent-added layers, and merged filesystem", flush=True)
    history = run("docker", "history", "--no-trunc", "--format", "{{json .}}", agent_image).stdout
    patterns = sensitive_patterns(repository_root, baseline_lock)
    history_hits = sorted(label for label, pattern in patterns.items() if pattern and pattern in history)
    layer_scan = scan_added_layers(agent_image, len(baseline_inspect["RootFS"]["Layers"]), patterns)
    baseline_paths = {item["path"] for item in baseline_lock["checkout_files"]}
    filesystem_scan = scan_image_filesystem(agent_image, patterns, baseline_paths)
    if history_hits or layer_scan["status"] != "PASS" or filesystem_scan["status"] != "PASS":
        raise RuntimeError(f"image leak scan failed: history={history_hits}, layers={layer_scan}, filesystem={filesystem_scan}")

    build_files = ["Dockerfile.baseline", "Dockerfile.agent", ".dockerignore", "entrypoint.sh", "sitecustomize.py", "build-images.sh", "run-stage.sh", "verify-inputs.py", "record-deployment.py"]
    build_manifest = [{"path": name, "sha256": sha256_file(image_dir / name)} for name in build_files]
    build_context_manifest = [item for item in build_manifest if item["path"] in {"Dockerfile.baseline", "Dockerfile.agent", ".dockerignore", "entrypoint.sh", "sitecustomize.py"}]
    context_sha = sha256_bytes(json.dumps(build_context_manifest, sort_keys=True, separators=(",", ":")).encode())
    lock_paths = {
        "openspec_package_lock": bench / "environments/sdd-tools/openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64/package-lock.json",
        "openspec_artifact_manifest": bench / "environments/sdd-tools/openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64/npm-artifacts/artifact-manifest.json",
        "cc_sdd_package_lock": bench / "environments/sdd-tools/cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64/package-lock.json",
        "cc_sdd_artifact_manifest": bench / "environments/sdd-tools/cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64/npm-artifacts/artifact-manifest.json",
        "speckit_install_lock": bench / "environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/install-requirements.txt",
        "speckit_artifact_manifest": bench / "environments/sdd-tools/speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/artifact-manifest.json",
    }
    dependency_locks = {
        name: {"path": path.relative_to(repository_root).as_posix(), "sha256": sha256_file(path)}
        for name, path in lock_paths.items()
    }
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deployment = {
        "schema_version": 1, "status": "READY", "generated_at_utc": now,
        "repository": "scrapy/scrapy", "base_sha": base_sha,
        "tree_sha": baseline_lock["tree_sha"],
        "baseline_lock_sha256": sha256_file(bench / "batch/baselines" / base_sha / "baseline-lock.json"),
        "images": {
            "source_baseline": {"tag": "scrapy-sdd-scrapy:base-11079cb1c85b-py311", "image_id": "sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa"},
            "baseline": {"tag": baseline_image, "image_id": baseline_inspect["Id"], "repo_digests": baseline_inspect.get("RepoDigests") or [], "rootfs_layers": baseline_inspect["RootFS"]["Layers"]},
            "common_runtime": {"tag": "scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate", "image_id": "sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9"},
            "agent": {"tag": agent_image, "image_id": agent_inspect["Id"], "repo_digests": agent_inspect.get("RepoDigests") or [], "rootfs_layers": agent_inspect["RootFS"]["Layers"]},
        },
        "versions": versions,
        "python_dependencies": {"count": len(python_freeze), "freeze_sha256": python_freeze_sha, "entries": python_freeze},
        "system_packages": {"count": len(dpkg_lock), "lock_sha256": dpkg_lock_sha, "entries": dpkg_lock},
        "speckit_environment": {"count": len(speckit_freeze), "freeze_sha256": speckit_freeze_sha, "entries": speckit_freeze},
        "dependency_locks": dependency_locks,
        "build": {"network": "none", "pull": False, "provenance": False, "source_date_epoch": 0, "files": build_manifest, "allowlisted_context_files": build_context_manifest, "build_context_sha256": context_sha},
        "run_policy": {
            "stages": ["detect", "update"], "fresh_container_per_stage": True,
            "shared_container": False, "shared_workspace": False, "shared_home": False,
            "shared_cache": False, "shared_model_session": False,
            "detect_workspace": "read-only", "update_repository": "read-only with nested tests/ writable mount",
            "allowed_update_directories": adapter["modification_policy"]["allowed_directories"],
            "agent_tests": "forbidden", "runtime_dependency_installation": "forbidden",
        },
    }
    lock_path = image_dir / "deployment-lock.json"
    atomic_json(lock_path, deployment)

    audit = {
        "schema_version": 1, "audit_type": "HOST_ONLY_IMAGE_AUDIT", "audited_at_utc": now,
        "status": "PASS", "repository": "scrapy/scrapy", "base_sha": base_sha,
        "tree_sha": baseline_lock["tree_sha"],
        "deployment_lock": {"path": lock_path.relative_to(repository_root).as_posix(), "sha256": sha256_file(lock_path)},
        "version_validation": {"status": "PASS", "actual": versions, "expected": expected_versions},
        "smoke_test": smoke_record,
        "stage_isolation": {"status": "PASS", "records": stage_records, "distinct_container_ids": True, "distinct_workspace_paths": True, "tmpfs_home_per_container": True},
        "leak_scan": {
            "status": "PASS", "history": {"status": "PASS", "hit_labels": history_hits},
            "added_layers": layer_scan,
            "filesystem": filesystem_scan,
            "scope_note": "Target-specific path names are scanned in agent-added layers. Baseline-native paths remain readable by Detect by design; no host-side target selection metadata is added.",
            "pattern_values_recorded": False,
        },
        "frozen_baseline_unchanged": smoke_record["frozen_cache_manifest_before"] == smoke_record["frozen_cache_manifest_after"],
    }
    audit_path = bench / "batch/audits/images" / f"{base_sha}-image-audit.json"
    atomic_json(audit_path, audit)
    print(json.dumps({"status": "PASS", "deployment_lock": str(lock_path), "image_audit": str(audit_path), "agent_image_id": agent_inspect["Id"]}))


if __name__ == "__main__":
    main()
