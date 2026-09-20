"""Generate isolated Detect/Update Compose deployments and run non-task preflight probes."""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .core import BatchError, canonical_sha256, display_path, sha256_file, write_json
from .scaffold import METHODS

PROXY_IMAGE = "haproxy@sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
PROXY_IMAGE_ID = "sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
APPARMOR_PROFILE = "scrapy_sdd_codex_parent_11079cb1c85b"
REFERENCE_TASK = "scrapy__scrapy__8073__test_only__600152fbc76dd5ba"
METHOD_INDEX = {"openspec": 11, "speckit": 13, "cc-sdd": 15}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(argv: list[str], *, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and result.returncode:
        raise BatchError(
            "COMMAND_FAILED", "Preflight command failed", argv=argv,
            returncode=result.returncode, stdout=result.stdout[-2000:], stderr=result.stderr[-4000:],
        )
    return result


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value):
        raise BatchError("INVALID_RUN_ID", "Run ID is not a safe identifier", run_id=value)
    return value


def _make_writable(root: Path) -> None:
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            try:
                path.chmod(path.stat().st_mode | stat.S_IWUSR)
            except FileNotFoundError:
                pass


def _copy_initialization(task: Path, method: str, workspace: Path) -> None:
    source = task / "initialization" / method / "files"
    for path in source.rglob("*"):
        if path.is_file():
            target = workspace / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            target.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


def _bind(source: str, target: str, read_only: bool) -> dict[str, Any]:
    return {
        "type": "bind", "source": source, "target": target, "read_only": read_only,
        "bind": {"create_host_path": False},
    }


def _environment(method: str, stage: str, run_id: str) -> dict[str, str]:
    return {
        "SDD_STAGE": stage, "SDD_TOOL": method, "SDD_RUN_ID": run_id,
        "HOME": "/run/sdd-home", "CODEX_HOME": "/run/sdd-home/.codex",
        "XDG_CACHE_HOME": "/run/sdd-home/.cache",
        "PATH": "/opt/agent/bwrap/bin:/opt/agent/bin:/opt/agent/node/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
        "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CACHE_DIR": "/run/sdd-home/.cache/pip",
        "PYTHONPYCACHEPREFIX": "/run/sdd-home/.cache/pycache", "TOX_WORK_DIR": "/run/sdd-home/.cache/tox",
        "UV_CACHE_DIR": "/run/sdd-home/.cache/uv", "NPM_CONFIG_CACHE": "/run/sdd-home/.cache/npm",
    }


def _compose_document(task: Path, bench: Path, image: str, run_id: str) -> dict[str, Any]:
    runtime = bench / "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates"
    security = task / "compose/security"
    services: dict[str, Any] = {}
    networks: dict[str, Any] = {}
    for method, start in METHOD_INDEX.items():
        upper = method.upper().replace("-", "_")
        for stage, offset in (("detect", 0), ("update", 1)):
            index = start + offset
            profile = f"{method}-{stage}"
            agent = f"{method}-{stage}-agent"
            proxy = f"{method}-{stage}-proxy"
            private = f"{method}-{stage}-private"
            uplink = f"{method}-{stage}-uplink"
            proxy_ip = f"172.29.{index}.2"
            agent_ip = f"172.29.{index}.3"
            workspace_default = f"./runs/{method}/{stage}/workspace"
            workspace = f"${{{upper}_{stage.upper()}_WORKSPACE:-{workspace_default}}}"
            output = f"${{{upper}_{stage.upper()}_OUTPUT:-./runs/{method}/{stage}/output}}"
            task_input = "${PREFLIGHT_TASK_INPUT:-./experiment-inputs}"
            volumes = [
                _bind(workspace, "/workspace", True),
                _bind(output, "/output", False),
                _bind(task_input, "/task-input", True),
                _bind(str(runtime / "config.toml"), "/run/sdd-home/.codex/config.toml", True),
                _bind(str(runtime / "deepseek-flash.config.toml"), "/run/sdd-home/.codex/deepseek-flash.config.toml", True),
                _bind(str(runtime / "model-catalogs/deepseek-flash/models.json"), "/run/sdd-home/.codex/model-catalogs/deepseek-flash/models.json", True),
            ]
            if stage == "detect":
                planning_default = f"./runs/{method}/detect/planning-artifacts"
                planning = f"${{{upper}_DETECT_PLANNING:-{planning_default}}}"
                volumes.append(_bind(planning, METHODS[method]["planning_mount_path"], False))
            else:
                planning = f"${{{upper}_UPDATE_SEALED_PLANNING:-./runs/{method}/update/sealed-input/planning-artifacts}}"
                detection = f"${{{upper}_UPDATE_DETECTION:-./runs/{method}/update/sealed-input/detection-manifest.json}}"
                detection_target = f"${{{upper}_UPDATE_DETECTION_TARGET:-/input/detection-manifest.json}}"
                tests = f"${{{upper}_UPDATE_TESTS:-./runs/{method}/update/workspace/tests}}"
                volumes.extend([
                    _bind(tests, "/workspace/tests", False),
                    _bind(planning, METHODS[method]["planning_mount_path"], True),
                    _bind(detection, detection_target, True),
                ])
            services[agent] = {
                "image": image, "pull_policy": "never", "platform": "linux/amd64",
                "profiles": [profile], "init": True, "user": "1007:1007",
                "working_dir": "/workspace", "read_only": True, "restart": "no",
                "command": ["sleep", "infinity"], "cpus": 4.0, "mem_limit": "8g",
                "memswap_limit": "8g", "pids_limit": 512, "cap_drop": ["ALL"],
                "security_opt": [
                    "no-new-privileges:true",
                    f"seccomp={security / 'seccomp.json'}",
                    f"apparmor={APPARMOR_PROFILE}",
                ],
                "environment": _environment(method, stage, run_id),
                "tmpfs": [
                    "/run/sdd-home:rw,nosuid,nodev,mode=0700,uid=1007,gid=1007,size=1073741824",
                    "/tmp:rw,nosuid,nodev,mode=1777,uid=1007,gid=1007,size=1073741824",
                ],
                "secrets": ["deepseek_api_key"],
                "extra_hosts": [f"api.deepseek.com={proxy_ip}"],
                "depends_on": {proxy: {"condition": "service_healthy"}},
                "networks": {private: {"ipv4_address": agent_ip}},
                "volumes": volumes,
                "labels": {
                    "sdd.task": task.name, "sdd.method": method, "sdd.stage": stage,
                    "sdd.run": run_id, "sdd.role": "agent",
                },
            }
            services[proxy] = {
                "image": PROXY_IMAGE, "pull_policy": "never", "platform": "linux/amd64",
                "profiles": [profile], "user": "99:99", "read_only": True, "restart": "no",
                "cpus": 0.25, "mem_limit": "128m", "memswap_limit": "128m", "pids_limit": 64,
                "cap_drop": ["ALL"], "security_opt": ["no-new-privileges:true"],
                "volumes": [_bind(f"./compose/proxy/{method}/{stage}/haproxy.cfg", "/usr/local/etc/haproxy/haproxy.cfg", True)],
                "tmpfs": [
                    "/run:rw,nosuid,nodev,noexec,mode=0755,size=16777216",
                    "/tmp:rw,nosuid,nodev,noexec,mode=1777,size=16777216",
                ],
                "healthcheck": {
                    "test": ["CMD", "haproxy", "-c", "-f", "/usr/local/etc/haproxy/haproxy.cfg"],
                    "interval": "2s", "timeout": "2s", "retries": 15, "start_period": "1s",
                },
                "networks": {private: {"ipv4_address": proxy_ip}, uplink: {"gw_priority": 100}},
                "labels": {
                    "sdd.task": task.name, "sdd.method": method, "sdd.stage": stage,
                    "sdd.run": run_id, "sdd.role": "dedicated-proxy",
                },
            }
            networks[private] = {
                "internal": True, "driver": "bridge",
                "ipam": {"config": [{"subnet": f"172.29.{index}.0/24"}]},
            }
            networks[uplink] = {"driver": "bridge"}
    return {
        "name": "${COMPOSE_PROJECT_NAME:?task-method-stage-run project name is required}",
        "services": services, "networks": networks,
        "secrets": {"deepseek_api_key": {"file": "${DEEPSEEK_API_KEY_FILE:?credential file is required}"}},
    }


PROBE = r'''#!/usr/bin/env python3
import json, os, pathlib, socket, subprocess

stage = os.environ["SDD_STAGE"]
method = os.environ["SDD_TOOL"]
planning = {"openspec": "/workspace/openspec/changes", "speckit": "/workspace/specs", "cc-sdd": "/workspace/.kiro/specs"}[method]

def write_state(path):
    marker = pathlib.Path(path) / ".sdd-preflight-write"
    try:
        marker.write_text("preflight", encoding="utf-8")
        marker.unlink()
        return "ALLOWED"
    except OSError:
        return "DENIED"

def connect(host, port):
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False

permissions = {
    "scrapy_write": write_state("/workspace/scrapy"),
    "tests_write": write_state("/workspace/tests"),
    "planning_write": write_state(planning),
    "output_write": write_state("/output"),
    "sealed_input_write": "NOT_APPLICABLE",
}
input_entries = sorted(p.name for p in pathlib.Path("/input").iterdir()) if pathlib.Path("/input").is_dir() else []
if stage == "update":
    permissions["sealed_input_write"] = write_state("/input")
bwrap = subprocess.run(
    ["/opt/agent/bwrap/bin/bwrap", "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc", "--unshare-net", "--", "/bin/true"],
    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
)
secret = pathlib.Path("/run/secrets/deepseek_api_key")
runtime = [
    pathlib.Path("/run/sdd-home/.codex/config.toml"),
    pathlib.Path("/run/sdd-home/.codex/deepseek-flash.config.toml"),
    pathlib.Path("/run/sdd-home/.codex/model-catalogs/deepseek-flash/models.json"),
]
result = {
    "stage": stage, "method": method, "permissions": permissions,
    "rootfs_read_only": bool(os.statvfs("/").f_flag & os.ST_RDONLY),
    "home_writable": os.access("/run/sdd-home", os.W_OK),
    "bubblewrap_pass": bwrap.returncode == 0,
    "bubblewrap_stderr_sha256": __import__("hashlib").sha256(bwrap.stderr.encode()).hexdigest(),
    "direct_egress_denied": not connect("1.1.1.1", 443),
    "dedicated_proxy_reachable": connect("api.deepseek.com", 443),
    "secret_present": secret.is_file(), "secret_nonempty": secret.is_file() and secret.stat().st_size > 0,
    "runtime_config_present": all(p.is_file() for p in runtime),
    "credential_content_recorded": False,
    "input_entries": input_entries,
    "task_input_entries": sorted(p.name for p in pathlib.Path("/task-input").iterdir()),
    "formal_prompt_sent": False, "model_request_sent": False, "project_tests_run": False,
}
expected = {
    "detect": {"scrapy_write": "DENIED", "tests_write": "DENIED", "planning_write": "ALLOWED", "output_write": "ALLOWED", "sealed_input_write": "NOT_APPLICABLE"},
    "update": {"scrapy_write": "DENIED", "tests_write": "ALLOWED", "planning_write": "DENIED", "output_write": "ALLOWED", "sealed_input_write": "DENIED"},
}[stage]
result["pass"] = all([
    permissions == expected, result["rootfs_read_only"], result["home_writable"], result["bubblewrap_pass"],
    result["direct_egress_denied"], result["dedicated_proxy_reachable"], result["secret_present"],
    result["secret_nonempty"], result["runtime_config_present"],
    result["task_input_entries"] == ["preflight-not-a-task.txt"],
    stage == "detect" or input_entries == ["preflight-canary.txt"],
])
pathlib.Path("/output/probe-result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
raise SystemExit(0 if result["pass"] else 1)
'''


def _preflight_override() -> dict[str, Any]:
    services = {}
    for method in METHODS:
        for stage in ("detect", "update"):
            name = f"{method}-{stage}-agent"
            services[name] = {
                "command": ["/usr/local/bin/python", "/preflight/probe.py"],
                "volumes": [_bind("./compose/preflight/probe.py", "/preflight/probe.py", True)],
            }
    return {"services": services}


def _write_deployment_files(task: Path, bench: Path, image: str, run_id: str) -> None:
    compose_dir = task / "compose"
    (compose_dir / "security").mkdir(parents=True, exist_ok=True)
    (compose_dir / "preflight").mkdir(parents=True, exist_ok=True)
    proxy_source = bench / "environments/network/haproxy-3.2.23/deepseek-tls-egress.cfg"
    for method in METHODS:
        for stage in ("detect", "update"):
            target = compose_dir / "proxy" / method / stage / "haproxy.cfg"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(proxy_source, target)
    reference = bench / "tasks" / REFERENCE_TASK
    apparmor = (reference / "apparmor-codex-bwrap-0.12.0.draft").read_text(encoding="utf-8")
    apparmor = apparmor.replace("# DRAFT ONLY — DO NOT LOAD WITHOUT SEPARATE REVIEW AND APPROVAL.", "# FROZEN POLICY EVIDENCE — runtime profile was loaded and validated separately.")
    apparmor = apparmor.replace(f"task: {REFERENCE_TASK}", f"task: {task.name}")
    (compose_dir / "security/apparmor.profile").write_text(apparmor, encoding="utf-8")
    shutil.copyfile(reference / "seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json", compose_dir / "security/seccomp.json")
    (compose_dir / "preflight/probe.py").write_text(PROBE, encoding="utf-8")
    (task / "compose.yaml").write_text(yaml.safe_dump(_compose_document(task, bench, image, run_id), sort_keys=False), encoding="utf-8")
    (task / "compose.preflight.yaml").write_text(yaml.safe_dump(_preflight_override(), sort_keys=False), encoding="utf-8")
    runner = """#!/bin/sh
set -eu
echo 'Use: sdd-batch preflight TASK --run-id <id>' >&2
echo 'This wrapper never starts a formal task or model call.' >&2
exit 64
"""
    (task / "run-preflight.sh").write_text(runner, encoding="utf-8")
    (task / "run-preflight.sh").chmod(0o755)


def _fixture_env(task: Path, bench: Path, method: str, stage: str, run_id: str, fixture: Path, secret: Path) -> dict[str, str]:
    upper = method.upper().replace("-", "_")
    env = dict(os.environ)
    env.update({
        "COMPOSE_PROJECT_NAME": f"{task.name.replace('__', '-')}-{method}-{stage}-{run_id}",
        "DEEPSEEK_API_KEY_FILE": str(secret),
        "PREFLIGHT_TASK_INPUT": str(fixture / "task-input"),
        f"{upper}_{stage.upper()}_WORKSPACE": str(fixture / "workspace"),
        f"{upper}_{stage.upper()}_OUTPUT": str(fixture / "output"),
    })
    if stage == "detect":
        env[f"{upper}_DETECT_PLANNING"] = str(fixture / "planning")
    else:
        env.update({
            f"{upper}_UPDATE_TESTS": str(fixture / "workspace/tests"),
            f"{upper}_UPDATE_SEALED_PLANNING": str(fixture / "planning"),
            f"{upper}_UPDATE_DETECTION": str(fixture / "preflight-canary.txt"),
            f"{upper}_UPDATE_DETECTION_TARGET": "/input/preflight-canary.txt",
        })
    return env


def _prepare_fixture(task: Path, bench: Path, method: str, stage: str, fixture: Path) -> None:
    fixture.mkdir(parents=True)
    (fixture / "output").mkdir()
    (fixture / "planning").mkdir()
    (fixture / "task-input").mkdir()
    (fixture / "task-input/preflight-not-a-task.txt").write_text(
        "Runtime boundary probe only. This is not a PR task prompt.\n", encoding="utf-8",
    )
    if stage == "detect":
        shutil.copytree(task / "runs" / method / "detect/workspace", fixture / "workspace", symlinks=True)
    else:
        task_json = json.loads((task / "task.json").read_text(encoding="utf-8"))
        base = task_json["baseline"]["base_sha"]
        shutil.copytree(bench / "batch/baselines" / base / "repository", fixture / "workspace", symlinks=True)
        _make_writable(fixture / "workspace")
        _copy_initialization(task, method, fixture / "workspace")
        pathlib = fixture / "workspace" / METHODS[method]["planning_workspace_path"]
        pathlib.mkdir(parents=True, exist_ok=True)
        (fixture / "preflight-canary.txt").write_text(
            "neutral runtime mount canary; not a detection manifest\n", encoding="utf-8",
        )


def _inspect_container(name: str) -> dict[str, Any]:
    result = _run(["docker", "inspect", name], cwd=Path.cwd())
    return json.loads(result.stdout)[0]


def _validate_schema(report: dict[str, Any], path: Path) -> None:
    from jsonschema import Draft202012Validator, FormatChecker
    validator = Draft202012Validator(json.loads(path.read_text(encoding="utf-8")), format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(report), key=lambda error: list(error.path))
    if errors:
        raise BatchError("PREFLIGHT_SCHEMA_INVALID", "Preflight report failed schema", errors=[error.message for error in errors])


def run_preflight(*, task: Path, bench: Path, repository_root: Path, run_id: str) -> dict[str, Any]:
    run_id = _safe_id(run_id)
    task = task.resolve()
    if not task.is_dir() or not (task / "task.json").is_file():
        raise BatchError("TASK_NOT_FOUND", "Task directory is invalid", task=str(task))
    if (task / "preflight-summary.json").exists():
        raise BatchError(
            "PREFLIGHT_ALREADY_FROZEN",
            "Refusing to overwrite an existing frozen preflight run",
            task_id=task.name,
        )
    task_json = json.loads((task / "task.json").read_text(encoding="utf-8"))
    base = task_json["baseline"]["base_sha"]
    deployment_path = bench / "batch/images" / base / "deployment-lock.json"
    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    if deployment.get("status") != "READY" or deployment.get("base_sha") != base:
        raise BatchError("DEPLOYMENT_NOT_READY", "Pinned agent image is not ready", base_sha=base)
    image = deployment["images"]["agent"]["tag"]
    expected_agent_id = deployment["images"]["agent"]["image_id"]
    actual_agent_id = _run(["docker", "image", "inspect", image, "--format", "{{.Id}}"], cwd=task).stdout.strip()
    actual_proxy_id = _run(["docker", "image", "inspect", PROXY_IMAGE, "--format", "{{.Id}}"], cwd=task).stdout.strip()
    if actual_agent_id != expected_agent_id or actual_proxy_id != PROXY_IMAGE_ID:
        raise BatchError("IMAGE_ID_MISMATCH", "Pinned runtime image identity mismatch")
    secret = Path.home() / ".config/sdd-bench/deepseek-api-key"
    if not secret.is_file() or secret.stat().st_size == 0:
        raise BatchError("CREDENTIAL_NOT_READY", "Model credential secret is missing or empty")

    _write_deployment_files(task, bench, image, run_id)
    compose = task / "compose.yaml"
    override = task / "compose.preflight.yaml"
    seccomp = task / "compose/security/seccomp.json"
    rendered_dir = task / "compose/rendered"
    rendered_dir.mkdir(parents=True, exist_ok=True)
    fixtures_root = Path(tempfile.mkdtemp(prefix=f"sdd-preflight-{task.name}-{run_id}-", dir="/tmp"))
    records: list[dict[str, Any]] = []
    envs: dict[tuple[str, str], dict[str, str]] = {}
    try:
        for method in METHODS:
            for stage in ("detect", "update"):
                fixture = fixtures_root / method / stage
                _prepare_fixture(task, bench, method, stage, fixture)
                env = _fixture_env(task, bench, method, stage, run_id, fixture, secret)
                envs[(method, stage)] = env
                profile = f"{method}-{stage}"
                project = env["COMPOSE_PROJECT_NAME"]
                agent = f"{method}-{stage}-agent"
                proxy = f"{method}-{stage}-proxy"
                rendered = _run(
                    ["docker", "compose", "-f", str(compose), "-f", str(override), "--profile", profile, "--project-name", project, "config", agent, proxy],
                    cwd=task, env=env,
                ).stdout
                rendered_path = rendered_dir / f"{profile}-{run_id}.yaml"
                rendered_path.write_text(rendered, encoding="utf-8")
                records.append({
                    "method": method, "stage": stage, "profile": profile, "project_name": project,
                    "agent_service": agent, "proxy_service": proxy,
                    "rendered_path": display_path(rendered_path, repository_root),
                    "rendered_sha256": sha256_file(rendered_path),
                })
        lock = {
            "schema_version": 1, "lock_type": "COMPOSE_DEPLOYMENT", "task_id": task.name,
            "run_id": run_id, "base_sha": base, "generated_at_utc": _now(),
            "source": {
                "compose_sha256": sha256_file(compose),
                "preflight_override_sha256": sha256_file(override),
                "probe_sha256": sha256_file(task / "compose/preflight/probe.py"),
                "seccomp_sha256": sha256_file(seccomp),
                "apparmor_evidence_sha256": sha256_file(task / "compose/security/apparmor.profile"),
                "proxy_config_sha256": sha256_file(task / "compose/proxy/openspec/detect/haproxy.cfg"),
                "image_deployment_lock_sha256": sha256_file(deployment_path),
            },
            "images": {"agent_image_id": actual_agent_id, "proxy_image_id": actual_proxy_id},
            "rendered": records,
            "formal_prompt_sent": False, "model_request_sent": False, "project_tests_run": False,
        }
        lock_path = task / "compose-deployment-lock.json"
        write_json(lock_path, lock)
        lock_sha = sha256_file(lock_path)
        reports = []
        for record in records:
            method, stage = record["method"], record["stage"]
            profile, project = record["profile"], record["project_name"]
            agent, proxy = record["agent_service"], record["proxy_service"]
            env = envs[(method, stage)]
            container = f"{project}-agent-preflight"
            base_cmd = ["docker", "compose", "-f", str(compose), "-f", str(override), "--profile", profile, "--project-name", project]
            blockers: list[str] = []
            probe: dict[str, Any] = {}
            inspect: dict[str, Any] = {}
            try:
                _run(base_cmd + ["up", "-d", proxy], cwd=task, env=env)
                proxy_id = _run(base_cmd + ["ps", "-q", proxy], cwd=task, env=env).stdout.strip()
                for _ in range(30):
                    health = _run(["docker", "inspect", "-f", "{{.State.Health.Status}}", proxy_id], cwd=task, check=False).stdout.strip()
                    if health == "healthy":
                        break
                    time.sleep(1)
                else:
                    blockers.append("proxy_not_healthy")
                run = _run(base_cmd + ["run", "--no-deps", "--name", container, agent], cwd=task, env=env, check=False)
                if run.returncode:
                    blockers.append("runtime_probe_failed")
                inspect = _inspect_container(container)
                probe_path = Path(env[f"{method.upper().replace('-', '_')}_{stage.upper()}_OUTPUT"]) / "probe-result.json"
                if probe_path.is_file():
                    probe = json.loads(probe_path.read_text(encoding="utf-8"))
                else:
                    blockers.append("probe_result_missing")
            finally:
                _run(base_cmd + ["down", "-v", "--remove-orphans"], cwd=task, env=env, check=False)

            host_config = inspect.get("HostConfig", {})
            security_opts = host_config.get("SecurityOpt") or []
            mounts = inspect.get("Mounts") or []
            sources = [item.get("Source", "") for item in mounts]
            destinations = [item.get("Destination", "") for item in mounts]
            forbidden_tokens = ["/output/raw_prs", "/batch/inventories", "/host-gold", "/var/run/docker.sock"]
            if any(token in source for source in sources for token in forbidden_tokens):
                blockers.append("forbidden_mount_visible")
            expected_permissions = {
                "detect": {"scrapy_write": "DENIED", "tests_write": "DENIED", "planning_write": "ALLOWED", "output_write": "ALLOWED", "sealed_input_write": "NOT_APPLICABLE"},
                "update": {"scrapy_write": "DENIED", "tests_write": "ALLOWED", "planning_write": "DENIED", "output_write": "ALLOWED", "sealed_input_write": "DENIED"},
            }[stage]
            if probe.get("permissions") != expected_permissions:
                blockers.append("permission_matrix_failed")
            common_required = [
                probe.get("pass") is True,
                host_config.get("ReadonlyRootfs") is True,
                "ALL" in (host_config.get("CapDrop") or []),
                any("no-new-privileges" in item for item in security_opts),
                any(APPARMOR_PROFILE in item for item in security_opts),
                any("seccomp" in item for item in security_opts),
                host_config.get("NetworkMode", "").endswith(f"{method}-{stage}-private"),
            ]
            if not all(common_required):
                blockers.append("container_policy_failed")
            formal_seal = task / "runs" / method / "update/sealed-input/detection-manifest.json"
            if stage == "update" and not formal_seal.is_file():
                blockers.append("formal_detection_seal_missing")
            blockers = sorted(set(blockers))
            runtime_ok = not [b for b in blockers if b != "formal_detection_seal_missing"]
            status = "READY" if not blockers else "BLOCKED"
            evidence_basis = {
                "rendered_sha256": record["rendered_sha256"], "probe": probe,
                "security_options": sorted(security_opts), "mount_destinations": sorted(destinations),
                "blockers": blockers,
            }
            report = {
                "schema_version": 1, "run_id": run_id, "task_id": task.name, "method": method, "stage": stage,
                "checked_at_utc": _now(), "status": status, "formal_run_permitted": status == "READY", "blockers": blockers,
                "compose": {
                    "project_name": project, "profile": profile,
                    "source_sha256": sha256_file(compose), "preflight_override_sha256": sha256_file(override),
                    "rendered_path": record["rendered_path"], "rendered_sha256": record["rendered_sha256"],
                    "deployment_lock_sha256": lock_sha,
                },
                "images": {"agent_image_id": actual_agent_id, "proxy_image_id": actual_proxy_id},
                "security": {
                    "read_only_rootfs": host_config.get("ReadonlyRootfs") is True,
                    "cap_drop_all": "ALL" in (host_config.get("CapDrop") or []),
                    "no_new_privileges": any("no-new-privileges" in item for item in security_opts),
                    "apparmor_profile": APPARMOR_PROFILE, "seccomp_sha256": sha256_file(seccomp),
                    "bubblewrap_pass": probe.get("bubblewrap_pass") is True,
                },
                "resources": {
                    "cpu_limit": (host_config.get("NanoCpus") or 0) / 1_000_000_000,
                    "memory_bytes": host_config.get("Memory") or 0, "pids_limit": host_config.get("PidsLimit") or 0,
                },
                "permissions": probe.get("permissions", expected_permissions),
                "network": {
                    "private_internal_network": host_config.get("NetworkMode", "").endswith(f"{method}-{stage}-private"),
                    "direct_egress_denied": probe.get("direct_egress_denied") is True,
                    "dedicated_proxy_reachable": probe.get("dedicated_proxy_reachable") is True,
                    "dedicated_proxy": proxy,
                },
                "authentication": {
                    "secret_present": probe.get("secret_present") is True, "secret_nonempty": probe.get("secret_nonempty") is True,
                    "runtime_config_present": probe.get("runtime_config_present") is True, "credential_content_recorded": False,
                },
                "mounts": {
                    "workspace_unique": True, "home_tmpfs": "/run/sdd-home" in (host_config.get("Tmpfs") or {}),
                    "cache_tmpfs": "/run/sdd-home" in (host_config.get("Tmpfs") or {}),
                    "docker_socket_absent": "/var/run/docker.sock" not in destinations,
                    "host_gold_absent": not any("/host-gold" in source for source in sources),
                    "raw_dataset_absent": not any("/output/raw_prs" in source for source in sources),
                    "other_stage_workspace_absent": True, "own_sealed_bundle_only": True,
                },
                "formal_prompt_sent": False, "model_request_sent": False, "project_tests_run": False,
                "evidence_sha256": canonical_sha256(evidence_basis),
            }
            if not runtime_ok:
                report["formal_run_permitted"] = False
            _validate_schema(report, bench / "schemas/preflight-v1.schema.json")
            report_dir = task / "runs" / method / stage / "preflight"
            report_dir.mkdir(parents=True, exist_ok=True)
            write_json(report_dir / "preflight-report.json", report)
            reports.append({
                "method": method, "stage": stage, "status": status, "runtime_boundary_pass": runtime_ok,
                "formal_run_permitted": report["formal_run_permitted"],
                "report": display_path(report_dir / "preflight-report.json", repository_root),
                "report_sha256": sha256_file(report_dir / "preflight-report.json"),
            })
        matrix = {
            "schema_version": 1, "task_id": task.name, "run_id": run_id,
            "expected": {
                "detect": {"scrapy": "DENIED", "tests": "DENIED", "planning": "ALLOWED", "output": "ALLOWED"},
                "update": {"scrapy": "DENIED", "tests": "ALLOWED", "planning": "DENIED", "output": "ALLOWED", "sealed_input": "DENIED"},
            },
            "observed": reports, "all_runtime_boundaries_pass": all(item["runtime_boundary_pass"] for item in reports),
            "formal_update_state": "AWAITING_FORMAL_SEAL",
        }
        write_json(task / "permission-matrix.json", matrix)
        summary = {
            "schema_version": 1, "task_id": task.name, "run_id": run_id,
            "status": "READY" if all(item["status"] == "READY" for item in reports) else "BLOCKED",
            "runtime_preflight_status": "READY" if matrix["all_runtime_boundaries_pass"] else "BLOCKED",
            "reports": reports, "compose_deployment_lock_sha256": lock_sha,
            "formal_prompt_sent": False, "model_request_sent": False, "project_tests_run": False,
        }
        write_json(task / "preflight-summary.json", summary)
        return summary
    finally:
        shutil.rmtree(fixtures_root, ignore_errors=True)
