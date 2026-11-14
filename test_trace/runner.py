"""Bounded discovery and one-process-per-instance execution, without project branches."""
from __future__ import annotations

import concurrent.futures
import contextlib
import fcntl
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from . import __version__
from .common import TraceError, atomic_text, digest, file_hash, read_json, safe_relative, snapshot, write_json

_CLEANUP_LOCK = threading.Lock()

def _remove_tree(path: Path) -> None:
    """Tests may leave read-only owned directories; never follow their symlinks."""
    def repair(function, name, error):
        target = Path(name)
        parent = target.parent
        parent.chmod(parent.stat().st_mode | 0o700)
        if target.is_symlink():
            target.unlink()
            return
        target.chmod(target.stat().st_mode | (0o700 if target.is_dir() else 0o600))
        function(name)
    shutil.rmtree(path, onerror=repair)


@contextlib.contextmanager
def coordinator_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".coordinator.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TraceError("Another coordinator owns this output directory") from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def load_config(path: Path) -> dict[str, Any]:
    config = read_json(path)
    for key in ("repository", "output"):
        if not isinstance(config.get(key), str):
            raise TraceError(f"Configuration requires {key}")
        config[key] = str((path.parent / config[key]).resolve())
    repository, output = Path(config["repository"]), Path(config["output"])
    if not repository.is_dir() or output.is_relative_to(repository):
        raise TraceError("Repository must exist and output must be outside it")
    if config.get("worker_root") is not None:
        if not isinstance(config["worker_root"], str):
            raise TraceError("worker_root must be a path string")
        scratch = (path.parent / config["worker_root"]).resolve()
        if scratch == repository or scratch.is_relative_to(repository) or output == scratch or output.is_relative_to(scratch):
            raise TraceError("Worker scratch must be outside the source and may not contain durable output")
        config["worker_root"] = str(scratch)
    config.setdefault("runtime", {"kind": "local", "python": sys.executable})
    config.setdefault("test_paths", ["tests"])
    config.setdefault("pytest_args", [])
    config.setdefault("production_roots", [])
    config.setdefault("source_mappings", [])
    config.setdefault("workers", 1)
    config.setdefault("timeout_seconds", 120)
    config.setdefault("collection_timeout_seconds", 300)
    config.setdefault("budget_seconds", None)
    config.setdefault("raw_events", False)
    if config["runtime"].get("kind") not in {"local", "docker"}:
        raise TraceError("runtime.kind must be local or docker")
    if not isinstance(config["workers"], int) or not 1 <= config["workers"] <= 64:
        raise TraceError("workers must be an integer between 1 and 64")
    for key in ("timeout_seconds", "collection_timeout_seconds"):
        if not isinstance(config[key], (int, float)) or config[key] <= 0:
            raise TraceError(f"{key} must be positive")
    if config["budget_seconds"] is not None and config["budget_seconds"] <= 0:
        raise TraceError("budget_seconds must be positive")
    for key in ("test_paths", "production_roots"):
        if not isinstance(config[key], list):
            raise TraceError(f"{key} must be a list")
        for relative in config[key]:
            if relative != ".":
                safe_relative(relative)
    if not isinstance(config["pytest_args"], list) or not all(isinstance(x, str) for x in config["pytest_args"]):
        raise TraceError("pytest_args must be a list of arguments")
    # Parallel pytest, retries, or another profiler would invalidate attribution.
    forbidden = ("--numprocesses", "--dist", "--reruns", "--cov", "--trace", "--collect-only")
    if any(a == "-n" or a.startswith(forbidden) for a in config["pytest_args"]):
        raise TraceError("pytest_args may not enable xdist, retries, coverage, tracing or collection")
    for mapping in config["source_mappings"]:
        if mapping["repository_root"] != ".":
            safe_relative(mapping["repository_root"])
        if not Path(mapping["runtime_root"]).is_absolute():
            raise TraceError("source_mappings runtime_root must be absolute")
    return config


def _invoke(args: list[str], *, timeout: float, log: Path | None = None,
            cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str, bool]:
    stream = log.open("wb") if log else subprocess.PIPE
    process = subprocess.Popen(args, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
    timed_out = False
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
    finally:
        if log:
            stream.close()
    return process.returncode, output.decode(errors="replace") if output else "", timed_out


def environment(config: dict[str, Any]) -> dict[str, Any]:
    runtime = config["runtime"]
    if runtime["kind"] == "docker":
        result = subprocess.run(["docker", "image", "inspect", runtime["image"]], capture_output=True, text=True, check=True)
        image = json.loads(result.stdout)[0]
        runtime["image"] = image["Id"]
        label_base = (image.get("Config", {}).get("Labels") or {}).get("bench.base-sha")
        if label_base and config.get("base_sha") and label_base != config["base_sha"]:
            raise TraceError("Image base label does not match configured base")
        record = {"kind": "docker", "image_id": image["Id"], "network": runtime.get("network", "none"),
                  "configured_environment": runtime.get("env", {}), "python": runtime.get("python", "python3")}
    else:
        python = runtime.get("python", sys.executable)
        probe = subprocess.run([python, "-c", "import json,sys,importlib.metadata as m; print(json.dumps({'python':sys.version,'packages':sorted((d.metadata.get('Name',''),d.version) for d in m.distributions())}))"], capture_output=True, text=True, check=True)
        record = {"kind": "local", "python": python, "versions": json.loads(probe.stdout), "configured_environment": runtime.get("env", {})}
    return {**record, "environment_id": digest(record)}


def initialize(config: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    root = Path(config["output"])
    root.mkdir(parents=True, exist_ok=True)
    source = snapshot(Path(config["repository"]))
    env = environment(config)
    code_root = Path(__file__).parent
    collector_files = {p.name: file_hash(p) for p in sorted(code_root.glob("*.py"))}
    identity_config = {k: v for k, v in config.items() if k not in {"output", "workers", "budget_seconds"}}
    identity = {"source": source["snapshot_id"], "environment": env["environment_id"],
                "config": identity_config, "collector_files": collector_files, "version": __version__}
    run_key = digest(identity)
    path = root / "run.json"
    frozen_source = root / ".source"
    if path.exists():
        run = read_json(path)
        if run["run_key"] != run_key:
            raise TraceError("Source, environment, policy or collector changed; choose a new output directory")
        if not frozen_source.is_dir() or snapshot(frozen_source)["snapshot_id"] != run["snapshot_id"]:
            raise TraceError("Frozen source snapshot changed or is missing")
        return run, root
    if frozen_source.exists():
        shutil.rmtree(frozen_source)
    frozen_source.mkdir()
    for relative, checksum in source["files"].items():
        destination = frozen_source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(config["repository"]) / relative, destination)
        if file_hash(destination) != checksum:
            raise TraceError("Source changed while freezing: " + relative)
    run = {"schema_version": 1, "document_type": "TEST_TRACE_RUN", "run_key": run_key,
           "run_id": "trace-" + uuid.uuid4().hex[:16], "snapshot_id": source["snapshot_id"],
           "source_files": source["files"], "source_executable_bits": source["executable_bits"], "environment": env, "environment_id": env["environment_id"],
           "base_sha": config.get("base_sha"), "collector_version": __version__, "collector_files": collector_files,
           "config": config, "collection_scope": "test_body_only", "started_at": time.time(),
           "limitations": ["one_process_per_instance_changes_shared_fixture_execution_frequency",
                           "worker_containers_are_reused_but_processes_and_workspaces_are_fresh",
                           "subprocess_and_unattributed_thread_coverage_is_not_collected"]}
    write_json(path, run)
    return run, root


class Worker:
    def __init__(self, config: dict[str, Any], root: Path, number: int):
        self.config, self.root, self.number = config, root, number
        self.directory = Path(config.get("worker_root", root / ".workers")) / str(number)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.container: str | None = None
        self._source_files = None

    def start(self) -> None:
        runtime = self.config["runtime"]
        if runtime["kind"] != "docker" or self.container:
            return
        name = "test-trace-" + uuid.uuid4().hex[:16]
        args = ["docker", "run", "--detach", "--rm", "--name", name, "--network", runtime.get("network", "none"),
                "--cpus", str(runtime.get("cpus", 1)), "--memory", str(runtime.get("memory", "2g")),
                "--pids-limit", str(runtime.get("pids_limit", 256)), "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", f"{os.getuid()}:{os.getgid()}", "--mount", f"type=bind,src={self.directory},dst=/trace-work",
                "--mount", f"type=bind,src={Path(__file__).parent},dst=/trace-code/test_trace,readonly",
                "--workdir", "/trace-work", "--entrypoint", runtime.get("python", "python3"), runtime["image"],
                "-c", "import time; time.sleep(100000000)"]
        self.container = name
        try:
            result = subprocess.run(args, capture_output=True, text=True, timeout=runtime.get("startup_timeout_seconds", 360))
            if result.returncode:
                raise TraceError(f"Cannot start worker container: {result.stderr.strip()}")
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        if self.container:
            name = self.container
            self.container = None
            warning = None
            try:
                result = subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=60)
                if result.returncode and b"No such container" not in result.stderr:
                    warning = result.stderr.decode(errors="replace")
            except (subprocess.TimeoutExpired, OSError) as exc:
                warning = str(exc)
            if warning:
                # A cleanup failure must not erase an already observed result
                # or prevent aggregate/index publication after all instances end.
                with _CLEANUP_LOCK:
                    path = self.root / "cleanup-warnings.json"
                    warnings = read_json(path) if path.exists() else []
                    warnings.append({"container": name, "warning": warning, "time": time.time()})
                    write_json(path, warnings)

    def execute(self, mode: str, output: Path, nodeid: str | None, timeout: float,
                log: Path) -> tuple[int, bool]:
        self.start()
        work = self.directory / "repository"
        if work.exists():
            _remove_tree(work)
        shutil.copytree(self.root / ".source", work)
        for current, directories, names in os.walk(work):
            Path(current).chmod(0o755)
            for name in names:
                path = Path(current) / name
                path.chmod(path.stat().st_mode | 0o600)
        home = self.directory / "home"
        if home.exists():
            _remove_tree(home)
        home.mkdir()
        runtime = self.config["runtime"]
        is_docker = runtime["kind"] == "docker"
        runtime_root = "/trace-work" if is_docker else str(self.directory)
        plugin_output = self.directory / "result.json"
        plugin_output.unlink(missing_ok=True)
        if self._source_files is None:
            self._source_files = read_json(self.root / "run.json")["source_files"]
        plugin_config = {"mode": mode, "repository_root": runtime_root + "/repository", "output_file": runtime_root + "/result.json",
                         "production_roots": self.config["production_roots"], "source_mappings": self.config["source_mappings"],
                         "raw_events": self.config["raw_events"], "execution_id": nodeid, "base_sha": self.config.get("base_sha"),
                         "source_files": self._source_files}
        write_json(self.directory / "config.json", plugin_config)
        env_values = {**runtime.get("env", {}), "TEST_TRACE_CONFIG": runtime_root + "/config.json",
                      "PYTHONPATH": ("/trace-code" if is_docker else str(Path(__file__).parent.parent)) + ":" + runtime_root + "/repository" + (":" + runtime["env"]["PYTHONPATH"] if runtime.get("env", {}).get("PYTHONPATH") else ""),
                      "PYTHONDONTWRITEBYTECODE": "1", "HOME": runtime_root + "/home", "TMPDIR": runtime_root + "/home"}
        pytest = [runtime.get("python", "python3" if is_docker else sys.executable), "-m", "pytest", "-p", "test_trace.pytest_plugin",
                  "-p", "no:rerunfailures", "-p", "no:xdist", "-p", "no:xdist.looponfail", "-p", "no:pytest_cov",
                  "-o", "cache_dir=" + runtime_root + "/home/pytest-cache", "-q", "--tb=short",
                  *self.config["pytest_args"], *(["--collect-only", *self.config["test_paths"]] if mode == "discover" else [nodeid])]
        if "pytest_addopts" in self.config:
            # Override is explicit and pinned, never silently inferred from a project name.
            pytest.extend(["-o", "addopts=" + self.config["pytest_addopts"]])
        # Worker launcher kills the complete subprocess group, including leaked test children.
        payload = {"cwd": runtime_root + "/repository", "argv": pytest, "env": env_values, "timeout": timeout}
        write_json(self.directory / "launch.json", payload)
        launcher = ("/trace-code" if is_docker else str(Path(__file__).parent.parent)) + "/test_trace/launch.py"
        if is_docker:
            args = ["docker", "exec", self.container, runtime.get("python", "python3"), launcher, "/trace-work/launch.json"]
            rc, _, timed_out = _invoke(args, timeout=timeout + 30, log=log)
        else:
            rc, _, timed_out = _invoke([runtime.get("python", sys.executable), launcher, str(self.directory / "launch.json")], timeout=timeout + 30, log=log)
        timed_out = timed_out or rc == 124
        if timed_out:
            self.close()
        if plugin_output.exists():
            shutil.copyfile(plugin_output, output)
        return rc, timed_out


def discover(config: dict[str, Any], *, refresh: bool = False, _locked: bool = False) -> dict[str, Any]:
    if not _locked:
        with coordinator_lock(Path(config["output"])):
            return discover(config, refresh=refresh, _locked=True)
    run, root = initialize(config)
    destination = root / "collection.json"
    if destination.exists() and not refresh:
        return read_json(destination)
    if refresh and (root / "instances").exists():
        raise TraceError("Cannot refresh discovery after execution has started")
    worker = Worker(config, root, 0)
    try:
        rc, timed_out = worker.execute("discover", destination, None, config["collection_timeout_seconds"], root / "collection.log")
    finally:
        worker.close()
    collection = read_json(destination) if destination.exists() else {"items": [], "errors": ["Collection process produced no structured result"]}
    collection.update({"process_exit_code": rc, "timed_out": timed_out, "snapshot_id": run["snapshot_id"]})
    collection["collection_status"] = "complete" if not timed_out and rc == 0 and not collection.get("errors") else "partial_or_failed"
    ids = [item["execution_id"] for item in collection["items"]]
    if len(ids) != len(set(ids)):
        raise TraceError("Discovery returned duplicate execution IDs")
    write_json(destination, collection)
    return collection


def collect(config: dict[str, Any]) -> dict[str, Any]:
    with coordinator_lock(Path(config["output"])):
        return _collect(config)


def _collect(config: dict[str, Any]) -> dict[str, Any]:
    run, root = initialize(config)
    collection = discover(config, _locked=True)
    pending: queue.Queue = queue.Queue()
    for item in collection["items"]:
        destination = root / "instances" / (digest(item["execution_id"]) + ".json")
        if not destination.exists():
            pending.put(item)
    for directory in ("instances", "diagnostics", "logs"):
        (root / directory).mkdir(exist_ok=True)
    started = time.monotonic()
    lock = threading.Lock()
    failures: list[str] = []
    completed_count = len(collection["items"]) - pending.qsize()

    def progress() -> dict[str, Any]:
        done = completed_count
        value = {"expected": len(collection["items"]), "completed": done, "pending": len(collection["items"]) - done,
                 "collection_status": collection["collection_status"], "run_id": run["run_id"], "updated_at": time.time(), "worker_errors": failures}
        # Terminal instance files are durable and authoritative. This derived
        # progress view need not journal-flush or rescan thousands of filenames
        # after every completion.
        atomic_text(root / "progress.json", json.dumps(value, sort_keys=True) + "\n", durable=False)
        return value

    def loop(number: int) -> None:
        nonlocal completed_count
        worker = Worker(config, root, number + 1)
        try:
            while config["budget_seconds"] is None or time.monotonic() - started < config["budget_seconds"]:
                try:
                    item = pending.get_nowait()
                except queue.Empty:
                    break
                identity = digest(item["execution_id"])
                result_path = root / "instances" / (identity + ".json")
                temporary = worker.directory / "normalized.json"
                temporary.unlink(missing_ok=True)
                timeout = config["timeout_seconds"]
                if config["budget_seconds"] is not None:
                    timeout = min(timeout, max(0.1, config["budget_seconds"] - (time.monotonic() - started)))
                before = time.monotonic()
                try:
                    rc, timed_out = worker.execute("collect", temporary, item["execution_id"], timeout, root / "logs" / (identity + ".log"))
                    result = read_json(temporary) if temporary.exists() else {}
                    if result.get("source_test_id") not in {None, item.get("source_test_id")}:
                        result["evidence_status"] = "diagnostic"
                        result.setdefault("errors", []).append({"code": "DISCOVERY_EXECUTION_IDENTITY_MISMATCH"})
                    result.update({"execution_id": item["execution_id"], "source_test_id": item.get("source_test_id"),
                                   "snapshot_id": run["snapshot_id"], "environment_id": run["environment_id"], "process_exit_code": rc,
                                   "duration_seconds": time.monotonic() - before, "collection_scope": "test_body_only"})
                    if timed_out or rc != 0 or not result.get("outcome"):
                        result["outcome"] = "timeout" if timed_out else result.get("outcome", "error")
                        result["evidence_status"] = "diagnostic"
                    if result.get("evidence_status") != "valid":
                        write_json(root / "diagnostics" / (identity + ".json"), result)
                        result = {k: v for k, v in result.items() if k not in {"covered_functions", "production_covered_functions", "nodes", "edges", "external_boundaries", "raw_events"}}
                        result["diagnostic_path"] = "diagnostics/" + identity + ".json"
                    write_json(result_path, result)
                except Exception as exc:
                    # Infrastructure errors are explicit and never treated as empty coverage.
                    value = {"execution_id": item["execution_id"], "source_test_id": item.get("source_test_id"), "outcome": "infrastructure_error",
                             "evidence_status": "diagnostic", "error": str(exc), "snapshot_id": run["snapshot_id"], "environment_id": run["environment_id"]}
                    write_json(result_path, value)
                    worker.close()
                finally:
                    pending.task_done()
                    with lock:
                        if result_path.exists():
                            completed_count += 1
                        value = progress()
                        if value["completed"] % 25 == 0 or value["completed"] == value["expected"]:
                            print(json.dumps(value), flush=True)
        finally:
            worker.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        futures = [pool.submit(loop, number) for number in range(config["workers"])]
        for future in futures:
            future.result()
    return progress()
