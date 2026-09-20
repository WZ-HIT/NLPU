from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.checkpoint import (
    capture_pr,
    capture_shared,
    covered_targets,
    restore_pr,
    verify_pr,
    verify_shared,
)
from batch.checkpoint.capture import capture_pr_all
from batch.checkpoint.layout import (
    CHECKPOINT_ROOT,
    DEFAULT_BATCH_RUNS,
    DEFAULT_BASELINES,
    DEFAULT_IMAGES,
    FILES_SUFFIX,
    GOLD_DIRNAME,
    PAYLOAD_DIRNAME,
    TASKS_DIRNAME,
    excluded_reason,
    payload_path,
)
from batch.core import BatchError, write_json
from batch.orchestrator import Ledger, orchestrate

METHODS = ("openspec", "speckit", "cc-sdd")
BATCH_ID = "fixture-batch-v1"
TASK_ID = "scrapy__scrapy__pr42"
LEDGER_SCHEMA = "schemas/batch-ledger-event-v1.schema.json"
TRACKED_CONFIG = (
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-flash.config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/deepseek-v4-pro.config.toml",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-flash/models.json",
    "environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/config-templates/model-catalogs/deepseek-v4-pro/models.json",
    "environments/network/haproxy-3.2.23/deepseek-tls-egress.cfg",
)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class CheckpointFixture:
    """A miniature bench: real Git workspaces, a real ledger, no Docker."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.repository_root = root
        self.bench = root / "sdd-bench/scrapy-sdd"
        self.bench.mkdir(parents=True)
        (self.bench / "schemas").mkdir()
        for name in (
            "batch-ledger-event-v1.schema.json",
            "checkpoint-shared-v1.schema.json",
            "checkpoint-pr-v1.schema.json",
        ):
            (self.bench / "schemas" / name).write_text(
                (BENCH / "schemas" / name).read_text(encoding="utf-8"), encoding="utf-8"
            )
        self._build_source()
        self._build_bench_repository()
        self._build_task()
        self._build_ledger()
        self._build_shared_state()

    # -- Git --------------------------------------------------------------
    def _build_source(self) -> None:
        self.source = self.root / "source"
        self.source.mkdir()
        git(self.source, "init", "--quiet")
        git(self.source, "config", "user.name", "Fixture")
        git(self.source, "config", "user.email", "fixture@example.invalid")
        (self.source / "scrapy").mkdir()
        (self.source / "tests").mkdir()
        (self.source / "scrapy/core.py").write_text("BASE = True\n", encoding="utf-8")
        (self.source / "tests/test_core.py").write_text("def test_base(): pass\n", encoding="utf-8")
        git(self.source, "add", ".")
        git(self.source, "commit", "--quiet", "-m", "base")
        self.base_sha = git(self.source, "rev-parse", "HEAD")
        self.tree_sha = git(self.source, "rev-parse", "HEAD^{tree}")

    def workspace(self, destination: Path) -> Path:
        """A checkout whose HEAD is exactly base_sha, with no remotes."""
        subprocess.run(
            ["git", "clone", "--quiet", "--no-hardlinks", str(self.source), str(destination)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        git(destination, "checkout", "--quiet", "--detach", self.base_sha)
        git(destination, "remote", "remove", "origin")
        return destination

    # -- Layout -----------------------------------------------------------
    def _build_bench_repository(self) -> None:
        git(self.repository_root, "init", "--quiet")
        git(self.repository_root, "config", "user.name", "Fixture")
        git(self.repository_root, "config", "user.email", "fixture@example.invalid")
        (self.repository_root / "output/prompt").mkdir(parents=True)
        (self.repository_root / "output/raw_prs").mkdir(parents=True)
        (self.repository_root / "output/prompt/scrapy__scrapy.json").write_text(
            '{"prs": []}\n', encoding="utf-8"
        )
        (self.repository_root / "output/raw_prs/scrapy__scrapy.jsonl").write_text(
            '{"repo": "scrapy/scrapy", "pr_id": 42}\n', encoding="utf-8"
        )
        # The deployment config lives inside the bench, the dataset inputs at the
        # repository root; the two bases genuinely differ, and a fixture that puts
        # both at the repository root hides that.
        for relative in TRACKED_CONFIG:
            path = self.bench / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# {Path(relative).name}\n", encoding="utf-8")
        git(self.repository_root, "add", ".")
        git(self.repository_root, "commit", "--quiet", "-m", "fixture inputs")

    def _build_shared_state(self) -> None:
        cache = self.bench / DEFAULT_BASELINES / self.base_sha
        self.workspace(cache / "repository")
        write_json(
            cache / "baseline-lock.json",
            {
                "base_sha": self.base_sha,
                "tree_sha": self.tree_sha,
                "checkout_file_count": 3,
                "checkout_manifest_sha256": "0" * 64,
                "source_repository": {"path": str(self.source), "base_object_verified": True},
            },
        )
        write_json(
            self.bench / DEFAULT_IMAGES / self.base_sha / "deployment-lock.json",
            {
                "base_sha": self.base_sha,
                "images": {
                    "agent": {
                        "tag": f"fixture-agent:{self.base_sha[:12]}",
                        "image_id": "sha256:" + "a" * 64,
                    }
                },
            },
        )
        (self.bench / DEFAULT_IMAGES / self.base_sha / "Dockerfile.agent").write_text(
            "FROM fixture\n", encoding="utf-8"
        )

    def _build_task(self) -> None:
        self.task = self.bench / TASKS_DIRNAME / TASK_ID
        write_json(
            self.task / "task.json",
            {"task_id": TASK_ID, "pr_id": 42, "baseline": {"base_sha": self.base_sha}},
        )
        (self.task / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        for method in METHODS:
            init = self.task / "initialization" / method / "files"
            (init / f".{method}").mkdir(parents=True)
            (init / f".{method}/config.yaml").write_text(f"{method}\n", encoding="utf-8")
            detect = self.workspace(self.task / "runs" / method / "detect/workspace")
            (detect / f".{method}").mkdir()
            (detect / f".{method}/config.yaml").write_text(f"{method}\n", encoding="utf-8")

            run_id = f"{method}-sealed-001"
            mode = self.task / "runs" / method / "update/executions" / run_id / "attempt-1/mode-sealed-detect"
            update = self.workspace(mode / "workspace")
            (update / f".{method}").mkdir()
            (update / f".{method}/config.yaml").write_text(f"{method}\n", encoding="utf-8")
            (update / "tests/test_core.py").write_text(
                "def test_base():\n    assert True\n", encoding="utf-8"
            )
            (mode / "artifacts").mkdir()
            (mode / "artifacts/candidate.patch").write_text(
                "diff --git a/tests/test_core.py b/tests/test_core.py\n"
                "--- a/tests/test_core.py\n"
                "+++ b/tests/test_core.py\n"
                "@@ -1 +1,2 @@\n"
                "-def test_base(): pass\n"
                "+def test_base():\n"
                "+    assert True\n",
                encoding="utf-8",
            )
            manifest = b'{"task_id": "scrapy__scrapy__pr42", "method": "%s"}\n' % method.encode()
            sealed = self.task / "runs" / method / "update/sealed-input"
            sealed.mkdir(parents=True)
            (sealed / "detection-manifest.json").write_bytes(manifest)
            detect_attempt = (
                self.task / "runs" / method / "detect/executions" / f"{method}-detect-001/attempt-1"
            )
            detect_attempt.mkdir(parents=True)
            (detect_attempt / "detection-manifest.json").write_bytes(manifest)
        write_json(
            self.bench / GOLD_DIRNAME / TASK_ID / "gold-store.json",
            {"store_type": "HOST_ONLY_GOLD", "task_id": TASK_ID},
        )

    def _build_ledger(self) -> None:
        run_root = self.bench / DEFAULT_BATCH_RUNS / BATCH_ID
        run_root.mkdir(parents=True)
        (run_root / "ledger.lock").write_text("", encoding="utf-8")
        ledger = Ledger(
            run_root / "ledger.jsonl", BATCH_ID, self.bench / LEDGER_SCHEMA
        )
        for method in METHODS:
            for stage, run_id, mode in (
                ("detect", f"{method}-detect-001", None),
                ("update", f"{method}-sealed-001", "sealed-detect"),
            ):
                ledger.append(
                    stage,
                    {"task_id": TASK_ID, "method": method, "stage": stage, "run_id": run_id, "mode": mode},
                    "DETECT_SEALED" if stage == "detect" else "UPDATE_SEALED",
                    1,
                    {"stage": stage},
                )

    # -- Helpers ----------------------------------------------------------
    def pr_layer(self) -> Path:
        return self.bench / CHECKPOINT_ROOT / "pr" / TASK_ID

    def shared_layer(self) -> Path:
        return self.bench / CHECKPOINT_ROOT / "shared"

    def payload_members(self, layer: Path, name: str) -> list[str]:
        with tarfile.open(payload_path(layer, name), "r:gz") as archive:
            return archive.getnames()


class CheckpointCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = CheckpointFixture(Path(self.temporary.name))
        self.bench = self.fixture.bench

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def capture(self, **kwargs):
        return capture_pr(
            bench=self.bench,
            repository_root=self.fixture.repository_root,
            task_id=TASK_ID,
            **kwargs,
        )

    def test_capture_packages_evidence_and_excludes_workspaces(self) -> None:
        result = self.capture()
        self.assertEqual(result["status"], "CAPTURED")
        layer = self.fixture.pr_layer()
        members = self.fixture.payload_members(layer, "task.tar.gz")
        self.assertFalse([name for name in members if name.endswith("/workspace")])
        self.assertFalse([name for name in members if "/.git/" in name])
        self.assertIn(f"{TASKS_DIRNAME}/{TASK_ID}/task.json", members)
        self.assertIn(f"{TASKS_DIRNAME}/{TASK_ID}/runs/openspec/update/sealed-input/detection-manifest.json", members)

        document = json.loads((layer / "checkpoint.json").read_text(encoding="utf-8"))
        self.assertEqual(len(document["excluded_regenerable"]), 2 * len(METHODS))
        self.assertTrue(all(item["assertion"] for item in document["excluded_regenerable"]))
        self.assertGreater(document["excluded_regenerable"][0]["size_bytes"], 0)
        self.assertFalse(document["contains_api_secret"])
        self.assertEqual(len(document["covered_targets"]), 2 * len(METHODS))
        self.assertEqual(document["gold_store_sha256"] is not None, True)

    def test_capture_is_idempotent_over_unchanged_evidence(self) -> None:
        self.capture()
        again = self.capture()
        self.assertEqual(again["status"], "UNCHANGED")

    def test_capture_refuses_changed_evidence_without_refresh(self) -> None:
        self.capture()
        extra = self.task_file("runs/openspec/detect/extra-evidence.json")
        extra.write_text('{"late": true}\n', encoding="utf-8")
        with self.assertRaises(BatchError) as caught:
            self.capture()
        self.assertEqual(caught.exception.code, "CHECKPOINT_ALREADY_EXISTS")
        refreshed = self.capture(refresh=True)
        self.assertEqual(refreshed["status"], "CAPTURED")
        replaced = self.bench / CHECKPOINT_ROOT / "restore-backups"
        kept = list(replaced.rglob(f"replaced/{TASK_ID}/checkpoint.json"))
        self.assertEqual(len(kept), 1, "the replaced checkpoint must be moved aside, never deleted")
        document = json.loads((self.fixture.pr_layer() / "checkpoint.json").read_text(encoding="utf-8"))
        self.assertNotEqual(document["content_sha256"], "0" * 64)
        verify_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )

    def test_unexplained_detect_workspace_file_fails_capture(self) -> None:
        stray = self.fixture.task / "runs/speckit/detect/workspace/agent-output.txt"
        stray.write_text("not explained by initialization\n", encoding="utf-8")
        with self.assertRaises(BatchError) as caught:
            self.capture()
        self.assertEqual(caught.exception.code, "WORKSPACE_NOT_REGENERABLE")
        self.assertIn(
            "runs/speckit/detect/workspace/agent-output.txt",
            json.dumps(caught.exception.details),
        )

    def test_detect_workspace_on_a_foreign_commit_fails_capture(self) -> None:
        workspace = self.fixture.task / "runs/cc-sdd/detect/workspace"
        (workspace / "scrapy/core.py").write_text("BASE = False\n", encoding="utf-8")
        with self.assertRaises(BatchError) as caught:
            self.capture()
        self.assertEqual(caught.exception.code, "WORKSPACE_NOT_REGENERABLE")
        self.assertIn("tracked file was modified", json.dumps(caught.exception.details))

    def test_update_workspace_change_absent_from_candidate_patch_fails_capture(self) -> None:
        workspace = (
            self.fixture.task / "runs/openspec/update/executions/openspec-sealed-001"
            "/attempt-1/mode-sealed-detect/workspace"
        )
        (workspace / "scrapy/core.py").write_text("BASE = False\n", encoding="utf-8")
        with self.assertRaises(BatchError) as caught:
            self.capture()
        self.assertEqual(caught.exception.code, "WORKSPACE_NOT_REGENERABLE")
        self.assertIn("absent from artifacts/candidate.patch", json.dumps(caught.exception.details))

    def test_new_evidence_outside_the_deny_list_is_packaged_not_dropped(self) -> None:
        fresh = self.fixture.task / "runs/openspec/detect/executions/openspec-detect-001/attempt-2"
        fresh.mkdir(parents=True)
        (fresh / "agent.jsonl").write_text('{"type": "item.completed"}\n', encoding="utf-8")
        self.capture()
        members = self.fixture.payload_members(self.fixture.pr_layer(), "task.tar.gz")
        self.assertIn(
            f"{TASKS_DIRNAME}/{TASK_ID}/runs/openspec/detect/executions/openspec-detect-001/attempt-2/agent.jsonl",
            members,
        )

    def test_capture_pr_all_covers_every_task_directory(self) -> None:
        results = capture_pr_all(bench=self.bench, repository_root=self.fixture.repository_root)
        self.assertEqual([item["status"] for item in results], ["CAPTURED"])
        self.assertEqual(
            [item["path"] for item in results], [str(self.fixture.pr_layer())]
        )

    def test_capture_shared_records_tracked_inputs_without_packaging_them(self) -> None:
        result = capture_shared(
            bench=self.bench, repository_root=self.fixture.repository_root, with_images=False
        )
        self.assertEqual(result["status"], "CAPTURED")
        layer = self.fixture.shared_layer()
        document = json.loads((layer / "checkpoint.json").read_text(encoding="utf-8"))
        self.assertEqual(len(document["raw_inputs"]), 2)
        self.assertTrue(all(item["worktree_matches_head"] for item in document["raw_inputs"]))
        self.assertEqual(len(document["deployment_config"]), len(TRACKED_CONFIG))
        # The deployment config is recorded repository-relative, so it carries the
        # bench prefix rather than the bare bench-relative path.
        bench_prefix = self.fixture.bench.relative_to(self.fixture.repository_root).as_posix()
        for item in document["deployment_config"]:
            self.assertTrue(item["path"].startswith(f"{bench_prefix}/"), item["path"])
            self.assertTrue(item["tracked"], item["path"])
            self.assertTrue(item["worktree_matches_head"], item["path"])
        self.assertEqual(
            sorted(item["path"] for item in document["deployment_config"]),
            sorted(f"{bench_prefix}/{relative}" for relative in TRACKED_CONFIG),
        )
        self.assertEqual(document["images"], [])
        self.assertEqual(len(document["baselines"]), 1)
        self.assertEqual(document["batch_runs"][0]["ledger_event_count"], 2 * len(METHODS))
        names = {item["name"] for item in document["payloads"]}
        self.assertEqual(names, {"baselines.tar.gz", "batch-images.tar.gz", "batch-runs.tar.gz"})
        members = self.fixture.payload_members(layer, "batch-runs.tar.gz")
        self.assertIn(f"{DEFAULT_BATCH_RUNS}/{BATCH_ID}/ledger.jsonl", members)
        self.assertFalse([name for name in members if name.endswith(".lock")])
        self.assertNotIn("output/prompt/scrapy__scrapy.json", members)

    def test_excluded_reason_covers_only_workspaces_and_git(self) -> None:
        self.assertEqual(
            excluded_reason(("runs", "openspec", "detect", "workspace")), "detect-workspace"
        )
        self.assertEqual(
            excluded_reason(
                ("runs", "cc-sdd", "update", "executions", "r", "attempt-1", "mode-sealed-detect", "workspace")
            ),
            "update-workspace",
        )
        self.assertEqual(excluded_reason(("runs", "cc-sdd", "detect", "output")), None)
        self.assertEqual(excluded_reason(("runs", "cc-sdd", "detect", "workspace", ".git")), "git-metadata")
        self.assertEqual(
            excluded_reason(("runs", "cc-sdd", "detect", "executions", "r", "attempt-1", "workspace")),
            None,
        )

    def task_file(self, relative: str) -> Path:
        path = self.fixture.task / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        return path


class CheckpointVerifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = CheckpointFixture(Path(self.temporary.name))
        self.bench = self.fixture.bench
        capture_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )
        capture_shared(
            bench=self.bench, repository_root=self.fixture.repository_root, with_images=False
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_verify_passes_for_freshly_captured_layers(self) -> None:
        pr = verify_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )
        shared = verify_shared(bench=self.bench, repository_root=self.fixture.repository_root)
        self.assertEqual(pr["status"], "PASS", pr["checks"])
        self.assertEqual(shared["status"], "PASS", shared["checks"])
        names = {item["check"] for item in pr["checks"]}
        self.assertIn("covered-targets", names)
        self.assertIn("sealed-input:openspec", names)
        self.assertIn("gold-store", names)
        self.assertIn("payload:task.tar.gz", names)
        self.assertIn(
            f"batch-runs:{BATCH_ID}", {item["check"] for item in shared["checks"]}
        )

    def test_tampered_payload_fails_verification(self) -> None:
        layer = self.fixture.pr_layer()
        path = payload_path(layer, "task.tar.gz")
        path.write_bytes(path.read_bytes() + b"trailing-junk")
        result = verify_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "payload:task.tar.gz",
            [item["check"] for item in result["checks"] if item["status"] == "FAIL"],
        )

    def test_sums_that_do_not_cover_the_recorded_payloads_raise(self) -> None:
        layer = self.fixture.pr_layer()
        sums = layer / "SHA256SUMS"
        sums.write_text(
            "\n".join(sums.read_text(encoding="utf-8").splitlines()[:-1]) + "\n", encoding="utf-8"
        )
        with self.assertRaises(BatchError) as caught:
            verify_pr(bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID)
        self.assertEqual(caught.exception.code, "SUMS_MISMATCH")

    def test_sealed_input_that_stops_mirroring_detect_fails_verification(self) -> None:
        sealed = self.fixture.task / "runs/speckit/update/sealed-input/detection-manifest.json"
        sealed.write_bytes(sealed.read_bytes().replace(b"speckit", b"other!!"))
        result = verify_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )
        self.assertEqual(result["status"], "FAIL")
        failed = [item["check"] for item in result["checks"] if item["status"] == "FAIL"]
        self.assertIn("sealed-input:speckit", failed)

    def test_baseline_cache_loss_is_reported(self) -> None:
        import shutil

        shutil.rmtree(self.bench / DEFAULT_BASELINES / self.fixture.base_sha / "repository")
        result = verify_shared(bench=self.bench, repository_root=self.fixture.repository_root)
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            f"baseline:{self.fixture.base_sha}",
            [item["check"] for item in result["checks"] if item["status"] == "FAIL"],
        )

    def test_tracked_input_drift_is_reported(self) -> None:
        (self.fixture.repository_root / "output/prompt/scrapy__scrapy.json").write_text(
            '{"prs": ["drift"]}\n', encoding="utf-8"
        )
        result = verify_shared(bench=self.bench, repository_root=self.fixture.repository_root)
        self.assertEqual(result["status"], "FAIL")

    def test_payload_file_manifest_detects_an_archive_that_hashes_correctly(self) -> None:
        layer = self.fixture.pr_layer()
        sidecar = layer / PAYLOAD_DIRNAME / ("task.tar.gz" + FILES_SUFFIX)
        lines = sidecar.read_text(encoding="utf-8").splitlines()
        lines[0] = "0" * 64 + lines[0][64:]
        sidecar.write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = verify_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("task.tar.gz", json.dumps(result["checks"]))


class CheckpointRestoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = CheckpointFixture(Path(self.temporary.name))
        self.bench = self.fixture.bench
        capture_pr(
            bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_restore_requires_explicit_confirmation(self) -> None:
        with self.assertRaises(BatchError) as caught:
            restore_pr(
                bench=self.bench, repository_root=self.fixture.repository_root, task_id=TASK_ID
            )
        self.assertEqual(caught.exception.code, "RESTORE_CONFIRMATION_REQUIRED")

    def test_restore_round_trips_a_destroyed_task(self) -> None:
        import shutil

        shutil.rmtree(self.fixture.task)
        result = restore_pr(
            bench=self.bench,
            repository_root=self.fixture.repository_root,
            task_id=TASK_ID,
            yes=True,
        )
        self.assertEqual(result["status"], "PASS", result["verification"]["checks"])
        self.assertTrue((self.fixture.task / "task.json").is_file())
        # Workspaces are excluded by design, so a restore leaves them to be
        # rebuilt by `sdd-batch provision` + `scaffold` rather than restoring a
        # stale copy the capture never proved regenerable.
        self.assertFalse((self.fixture.task / "runs/openspec/detect/workspace").exists())
        self.assertEqual(
            covered_targets(self.bench, TASK_ID),
            json.loads(
                (self.fixture.pr_layer() / "checkpoint.json").read_text(encoding="utf-8")
            )["covered_targets"],
        )

    def test_restore_moves_replaced_state_into_backups(self) -> None:
        marker = self.fixture.task / "runs/openspec/detect/hand-written.json"
        marker.write_text('{"live": true}\n', encoding="utf-8")
        result = restore_pr(
            bench=self.bench,
            repository_root=self.fixture.repository_root,
            task_id=TASK_ID,
            yes=True,
        )
        self.assertFalse(marker.exists())
        backups = list((self.bench / CHECKPOINT_ROOT / "restore-backups").rglob("hand-written.json"))
        self.assertEqual(len(backups), 1)
        self.assertTrue(result["backup_root"].startswith(str(self.bench)))

    def test_restore_refuses_while_the_batch_run_lock_is_held(self) -> None:
        lock = self.bench / DEFAULT_BATCH_RUNS / BATCH_ID / "run.lock"
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(BatchError) as caught:
                restore_pr(
                    bench=self.bench,
                    repository_root=self.fixture.repository_root,
                    task_id=TASK_ID,
                    yes=True,
                )
            self.assertEqual(caught.exception.code, "BATCH_RUN_ACTIVE")
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        restore_pr(
            bench=self.bench,
            repository_root=self.fixture.repository_root,
            task_id=TASK_ID,
            yes=True,
        )

    def test_restore_refuses_when_a_payload_was_corrupted(self) -> None:
        path = payload_path(self.fixture.pr_layer(), "task.tar.gz")
        path.write_bytes(path.read_bytes()[:-16] + b"corrupted-payload")
        with self.assertRaises(BatchError) as caught:
            restore_pr(
                bench=self.bench,
                repository_root=self.fixture.repository_root,
                task_id=TASK_ID,
                yes=True,
            )
        self.assertEqual(caught.exception.code, "PAYLOAD_VERIFICATION_FAILED")


class OrchestrateRunLockTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.bench = Path(self.temporary.name) / "sdd-bench/scrapy-sdd"
        (self.bench / "schemas").mkdir(parents=True)
        # A real batch-run schema makes the post-lock failure a structured
        # BatchError rather than a FileNotFoundError, so the assertions below
        # can distinguish "refused by the lock" from "refused by the config".
        (self.bench / "schemas/batch-run-v1.schema.json").write_text(
            (BENCH / "schemas/batch-run-v1.schema.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.config = self.bench / "batch/pilot/fixture.json"
        write_json(self.config, {"batch_id": BATCH_ID})

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def call(self) -> dict:
        return orchestrate(
            command="detect",
            config_path=self.config,
            bench=self.bench,
            repository_root=self.bench.parents[1],
            dry_run=False,
            resume=False,
            retries=set(),
            task_ids=set(),
            methods=set(),
            modes=set(),
        )

    def test_a_second_concurrent_run_is_refused(self) -> None:
        lock = self.bench / DEFAULT_BATCH_RUNS / BATCH_ID / "run.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(BatchError) as caught:
                self.call()
            self.assertEqual(caught.exception.code, "BATCH_RUN_ACTIVE")
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        # With the lock free the call proceeds past it and fails on the config
        # instead, which proves the refusal above came from the lock.
        with self.assertRaises(BatchError) as caught:
            self.call()
        self.assertNotEqual(caught.exception.code, "BATCH_RUN_ACTIVE")

    def test_read_only_commands_do_not_take_the_lock(self) -> None:
        lock = self.bench / DEFAULT_BATCH_RUNS / BATCH_ID / "run.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a+") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(BatchError) as caught:
                orchestrate(
                    command="status",
                    config_path=self.config,
                    bench=self.bench,
                    repository_root=self.bench.parents[1],
                    dry_run=False,
                    resume=False,
                    retries=set(),
                    task_ids=set(),
                    methods=set(),
                    modes=set(),
                )
            self.assertNotEqual(caught.exception.code, "BATCH_RUN_ACTIVE")
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    unittest.main()
