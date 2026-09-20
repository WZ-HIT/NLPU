#!/usr/bin/env python3
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
