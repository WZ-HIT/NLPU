from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import BatchError, canonical_sha256, sha256_file
from batch.orchestrator import Ledger, _latest
from batch.stages import (
    _capture_update_sdd_artifacts,
    _codex_catalog_override,
    _prepare_codex_mountpoint,
    enforce_update_scope,
    validate_update_policy,
)
from batch.update_policy import select_update_policy


class Prompt8ScopeTests(unittest.TestCase):
    def test_sealed_detect_is_limited_to_candidate_paths(self) -> None:
        self.assertEqual(
            enforce_update_scope(
                "sealed-detect",
                ["tests/test_allowed.py", "tests/test_other.py"],
                ["tests/test_allowed.py"],
            ),
            ["tests/test_other.py"],
        )

    def test_self_directed_may_choose_any_test_but_never_production(self) -> None:
        self.assertEqual(
            enforce_update_scope(
                "self-directed",
                ["tests/test_new.py", "scrapy/core/engine.py"],
                [],
            ),
            ["scrapy/core/engine.py"],
        )


class Prompt8ComposeOverrideTests(unittest.TestCase):
    def test_codex_sandbox_mountpoint_is_isolated_tmpfs(self) -> None:
        runtime = Path("/runtime/config-templates")
        rendered = _codex_catalog_override("openspec", "detect", runtime)
        self.assertIn(
            "- /workspace/.codex:rw,nosuid,nodev,noexec,mode=0700,uid=1007,gid=1007,size=1m",
            rendered,
        )
        self.assertIn(
            "target: /home/bench/.codex/model-catalogs/deepseek-flash/models.json",
            rendered,
        )
        self.assertIn("read_only: true", rendered)

    def test_update_workspace_has_codex_tmpfs_mountpoint(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-codex-mountpoint-") as temporary:
            workspace = Path(temporary)
            _prepare_codex_mountpoint(workspace)
            self.assertTrue((workspace / ".codex").is_dir())

    def test_codex_tmpfs_mountpoint_rejects_symlink(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-codex-mountpoint-") as temporary:
            workspace = Path(temporary)
            target = workspace / "elsewhere"
            target.mkdir()
            (workspace / ".codex").symlink_to(target, target_is_directory=True)
            with self.assertRaises(BatchError) as caught:
                _prepare_codex_mountpoint(workspace)
            self.assertEqual(caught.exception.code, "INVALID_CODEX_MOUNTPOINT")


class Prompt8UpdateArtifactCaptureTests(unittest.TestCase):
    def _capture(self, root: Path, method: str = "speckit") -> tuple[Path, dict]:
        workspace = root / "workspace"
        execution = root / "execution"
        workspace.mkdir()
        execution.mkdir()
        planning = workspace / {
            "openspec": "openspec/changes",
            "speckit": "specs",
            "cc-sdd": ".kiro/specs",
        }[method]
        planning.mkdir(parents=True)
        return _capture_update_sdd_artifacts(
            workspace=workspace,
            execution=execution,
            task={"task_id": "scrapy__scrapy__pr8073"},
            method=method,
            run_id="future-update-001",
            mode="self-directed",
            bench=BENCH,
        )

    def test_captures_empty_planning_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-update-artifacts-") as temporary:
            manifest_path, manifest = self._capture(Path(temporary))
            self.assertEqual(manifest["status"], "CAPTURED_EMPTY")
            self.assertEqual(manifest["files"], [])
            self.assertEqual(manifest["file_count"], 0)
            payload = dict(manifest)
            self.assertEqual(payload.pop("manifest_sha256"), canonical_sha256(payload))
            self.assertEqual(
                json.loads(manifest_path.read_text(encoding="utf-8")),
                manifest,
            )

    def test_captures_nonempty_planning_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-update-artifacts-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            planning = workspace / "openspec/changes"
            planning.mkdir(parents=True)
            (planning / "proposal.md").write_text("proposal\n", encoding="utf-8")
            execution = root / "execution"
            execution.mkdir()
            _, manifest = _capture_update_sdd_artifacts(
                workspace=workspace,
                execution=execution,
                task={"task_id": "scrapy__scrapy__pr8073"},
                method="openspec",
                run_id="future-update-001",
                mode="sealed-detect",
                bench=BENCH,
            )
            self.assertEqual(manifest["status"], "CAPTURED_NONEMPTY")
            self.assertEqual(manifest["file_count"], 1)
            self.assertEqual(manifest["files"][0]["path"], "proposal.md")
            self.assertEqual(
                sha256_file(execution / "sdd-artifacts/proposal.md"),
                manifest["files"][0]["sha256"],
            )

    def test_rejects_symlink_in_planning_tree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-update-artifacts-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            planning = workspace / "specs"
            planning.mkdir(parents=True)
            outside = root / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            (planning / "escape").symlink_to(outside)
            execution = root / "execution"
            execution.mkdir()
            with self.assertRaises(BatchError) as caught:
                _capture_update_sdd_artifacts(
                    workspace=workspace,
                    execution=execution,
                    task={"task_id": "scrapy__scrapy__pr8073"},
                    method="speckit",
                    run_id="future-update-001",
                    mode="self-directed",
                    bench=BENCH,
                )
            self.assertEqual(caught.exception.code, "SDD_ARTIFACT_SYMLINK")


class Prompt8PolicyValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sdd-prompt8-")
        self.root = Path(self.temporary.name)
        self.bench = self.root / "sdd-bench/scrapy-sdd"
        (self.bench / "schemas").mkdir(parents=True)
        for name in ("task-v1.schema.json", "update-policy-v1.schema.json"):
            shutil.copyfile(BENCH / "schemas" / name, self.bench / "schemas" / name)
        source_task = BENCH / "tasks/scrapy__scrapy__pr8073/task.json"
        task_data = json.loads(source_task.read_text(encoding="utf-8"))
        self.task = self.bench / "tasks" / task_data["task_id"]
        self.task.mkdir(parents=True)
        shutil.copyfile(source_task, self.task / "task.json")
        (self.task / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
        base = task_data["baseline"]["base_sha"]
        lock = self.bench / "batch/baselines" / base / "baseline-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"base_sha": base}) + "\n", encoding="utf-8")
        result = select_update_policy(
            task=self.task,
            bench=self.bench,
            repository_root=self.root,
            method="openspec",
            mode="sealed-detect",
            run_id="sealed-unit-001",
        )
        self.policy = self.root / result["policy"]
        self.policy_sha = result["policy_sha256"]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_policy_hash_task_method_and_run_are_bound(self) -> None:
        policy, _, _, actual_sha = validate_update_policy(
            task_manifest=self.task / "task.json",
            policy_path=self.policy,
            bench=self.bench,
            method="openspec",
            run_id="sealed-unit-001",
            expected_file_sha256=self.policy_sha,
        )
        self.assertEqual(policy["mode"], "sealed-detect")
        self.assertEqual(actual_sha, self.policy_sha)

        cases = (
            ({"method": "speckit"}, "UPDATE_POLICY_CONTEXT_MISMATCH"),
            ({"run_id": "another-run"}, "UPDATE_POLICY_CONTEXT_MISMATCH"),
            ({"expected_file_sha256": "0" * 64}, "BATCH_POLICY_HASH_MISMATCH"),
        )
        for values, code in cases:
            kwargs = {
                "task_manifest": self.task / "task.json",
                "policy_path": self.policy,
                "bench": self.bench,
                "method": "openspec",
                "run_id": "sealed-unit-001",
                "expected_file_sha256": self.policy_sha,
            }
            kwargs.update(values)
            with self.subTest(values=values), self.assertRaises(BatchError) as caught:
                validate_update_policy(**kwargs)
            self.assertEqual(caught.exception.code, code)

    def test_policy_cannot_be_reused_from_noncanonical_path(self) -> None:
        copied = self.task / "runs/openspec/update/policies/cross-task-copy"
        copied.mkdir(parents=True)
        shutil.copyfile(self.policy, copied / "update-policy.json")
        shutil.copyfile(self.policy.with_name("update-policy.sha256"), copied / "update-policy.sha256")
        with self.assertRaises(BatchError) as caught:
            validate_update_policy(
                task_manifest=self.task / "task.json",
                policy_path=copied / "update-policy.json",
                bench=self.bench,
            )
        self.assertEqual(caught.exception.code, "CROSS_TASK_POLICY_PATH")


class Prompt8SchemaAndLedgerTests(unittest.TestCase):
    def test_batch_schema_rejects_unknown_missing_sha_and_path_escape(self) -> None:
        schema = json.loads((BENCH / "schemas/batch-run-v1.schema.json").read_text())
        validator = Draft202012Validator(schema)
        valid = {
            "schema_version": 1,
            "batch_id": "unit-batch",
            "approved_plan": {
                "plan_id": "unit-plan",
                "path": "batch/plans/plan.json",
                "sha256": "1" * 64,
                "provision_report_path": "batch/reports/report.json",
                "provision_report_sha256": "2" * 64,
            },
            "tasks": [{
                "task_id": "scrapy__scrapy__pr8073",
                "task_manifest": {"path": "tasks/pr8073/task.json", "sha256": "3" * 64},
                "methods": [{
                    "method": "openspec",
                    "detect": {"run_id": "detect-001"},
                    "updates": [{
                        "run_id": "self-001",
                        "mode": "self-directed",
                        "policy": {"path": "tasks/pr8073/policy.json", "sha256": "4" * 64},
                    }],
                }],
            }],
        }
        self.assertFalse(list(validator.iter_errors(valid)))
        invalid = []
        value = copy.deepcopy(valid)
        value["unexpected"] = True
        invalid.append(value)
        value = copy.deepcopy(valid)
        del value["tasks"][0]["task_manifest"]["sha256"]
        invalid.append(value)
        value = copy.deepcopy(valid)
        value["approved_plan"]["path"] = "../plan.json"
        invalid.append(value)
        value = copy.deepcopy(valid)
        value["approved_plan"]["sha256"] = "not-a-sha"
        invalid.append(value)
        for index, value in enumerate(invalid):
            self.assertTrue(list(validator.iter_errors(value)), index)

    def test_ledger_is_hash_chained_and_resume_skip_preserves_terminal_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sdd-ledger-") as temporary:
            path = Path(temporary) / "ledger.jsonl"
            ledger = Ledger(path, "unit-batch", BENCH / "schemas/batch-ledger-event-v1.schema.json")
            target = {
                "task_id": "scrapy__scrapy__pr8073",
                "method": "openspec",
                "stage": "update",
                "run_id": "self-001",
                "mode": "self-directed",
            }
            terminal = ledger.append("update", target, "UPDATE_SEALED", 1, {"status": "SEALED"})
            ledger.append("update", target, "SKIPPED_RESUME", 1, {"previous": terminal["event_sha256"]})
            latest = _latest(ledger.read())
            self.assertEqual(next(iter(latest.values()))["state"], "UPDATE_SEALED")

            lines = path.read_text(encoding="utf-8").splitlines()
            tampered = json.loads(lines[0])
            tampered["attempt"] = 2
            lines[0] = json.dumps(tampered, sort_keys=True, separators=(",", ":"))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            with self.assertRaises(BatchError) as caught:
                ledger.read()
            self.assertEqual(caught.exception.code, "LEDGER_CHAIN_INVALID")


if __name__ == "__main__":
    unittest.main()
