from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import BatchError, canonical_sha256, sha256_file, write_json
from batch.provision import checkout_manifest, git_topology, provision_plan


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout.strip()


class ProvisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.bench = self.root / "sdd-bench/scrapy-sdd"
        self.bench.mkdir(parents=True)
        self.source = self.root / "source"
        self.source.mkdir()
        git(self.source, "init", "--quiet")
        git(self.source, "config", "user.name", "Fixture")
        git(self.source, "config", "user.email", "fixture@example.invalid")
        (self.source / "scrapy").mkdir()
        (self.source / "tests").mkdir()
        (self.source / "scrapy/core.py").write_text("BASE = True\n")
        (self.source / "tests/test_core.py").write_text("def test_base(): pass\n")
        git(self.source, "add", ".")
        git(self.source, "commit", "--quiet", "-m", "base")
        self.base = git(self.source, "rev-parse", "HEAD")
        (self.source / "scrapy/core.py").write_text("TARGET = True\n")
        git(self.source, "commit", "--quiet", "-am", "head")
        self.head = git(self.source, "rev-parse", "HEAD")
        self.raw = self.root / "raw.jsonl"
        self.raw.write_text(
            json.dumps(
                {
                    "repo": "scrapy/scrapy",
                    "pr_id": 7,
                    "base_sha": self.base,
                    "head_sha": self.head,
                    "merge_commit_sha": None,
                }
            )
            + "\n"
        )
        self.prompt = self.root / "prompt.json"
        self.prompt.write_text("[]\n")
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text("{}\n")
        inputs = {
            "prompt": {
                "path": str(self.prompt),
                "sha256": sha256_file(self.prompt),
                "size_bytes": self.prompt.stat().st_size,
                "record_count": 0,
            },
            "raw": {
                "path": str(self.raw),
                "sha256": sha256_file(self.raw),
                "size_bytes": self.raw.stat().st_size,
                "record_count": 1,
            },
        }
        self.plan = {
            "schema_version": 1,
            "plan_id": "fixture-plan",
            "plan_type": "PROVISION_PLAN",
            "created_at_utc": "2026-09-15T00:00:00Z",
            "status": "AWAITING_USER_APPROVAL",
            "executable": False,
            "repository_scope": "scrapy/scrapy",
            "inputs": inputs,
            "input_set_sha256": canonical_sha256(
                {name: value["sha256"] for name, value in sorted(inputs.items())}
            ),
            "inventory": {
                "path": str(self.inventory),
                "sha256": sha256_file(self.inventory),
                "inventory_id": "fixture-inventory",
            },
            "selection": {
                "source": "raw",
                "requested": {"pr_ids": [7], "pr_id_files": [], "sample_ids": []},
                "resolution_events": [],
                "resolved_prs": [{"repository": "scrapy/scrapy", "pr_id": 7}],
                "sha256": "0" * 64,
            },
            "task_scope": "one task per selected PR; sample IDs only resolve PR membership",
            "tasks": [
                {
                    "task_id": "scrapy__scrapy__pr7",
                    "repository": "scrapy/scrapy",
                    "pr_id": 7,
                    "baseline": {"base_sha": self.base},
                    "classification": "MIXED_CODE_AND_TEST_PR",
                    "member_sample_ids": ["fixture-sample"],
                    "member_sample_count": 1,
                    "test_change_count": 1,
                    "changed_files": ["scrapy/core.py", "tests/test_core.py"],
                    "nl_quality": {
                        "status": "GOOD",
                        "word_count": 4,
                        "has_title": True,
                        "has_body": True,
                        "description": "fixture description",
                    },
                    "task_categories": {"focal_guided": 1},
                }
            ],
            "approval": {
                "required": True,
                "granted": False,
                "provisioning_performed": False,
            },
        }
        self.plan_path = self.root / "plan.json"
        write_json(self.plan_path, self.plan)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _provision(self, plan=None):
        return provision_plan(
            plan=plan or self.plan,
            plan_path=self.plan_path,
            approved_plan_id=(plan or self.plan)["plan_id"],
            bench_root=self.bench,
            repository_root=self.root,
            source_repository=self.source,
        )

    def test_plan_fields_and_task_path_fail_closed(self) -> None:
        unknown = json.loads(json.dumps(self.plan))
        unknown["unexpected"] = True
        with self.assertRaises(BatchError) as context:
            self._provision(unknown)
        self.assertEqual(context.exception.code, "INVALID_PLAN_FIELDS")

        escaped = json.loads(json.dumps(self.plan))
        escaped["tasks"][0]["task_id"] = "../escape"
        with self.assertRaises(BatchError) as context:
            self._provision(escaped)
        self.assertEqual(context.exception.code, "INVALID_TASK_ID")

    def test_same_base_cache_is_reused_identically_by_second_task(self) -> None:
        second_raw = {
            "repo": "scrapy/scrapy",
            "pr_id": 8,
            "base_sha": self.base,
            "head_sha": self.head,
            "merge_commit_sha": None,
        }
        with self.raw.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(second_raw) + "\n")
        plan = json.loads(json.dumps(self.plan))
        plan["plan_id"] = "fixture-reuse"
        plan["inputs"]["raw"]["sha256"] = sha256_file(self.raw)
        plan["inputs"]["raw"]["size_bytes"] = self.raw.stat().st_size
        plan["inputs"]["raw"]["record_count"] = 2
        plan["input_set_sha256"] = canonical_sha256(
            {
                name: value["sha256"]
                for name, value in sorted(plan["inputs"].items())
            }
        )
        second_task = json.loads(json.dumps(plan["tasks"][0]))
        second_task["task_id"] = "scrapy__scrapy__pr8"
        second_task["pr_id"] = 8
        plan["tasks"].append(second_task)
        plan["selection"]["requested"]["pr_ids"].append(8)
        plan["selection"]["resolved_prs"].append(
            {"repository": "scrapy/scrapy", "pr_id": 8}
        )
        write_json(self.plan_path, plan)
        report = self._provision(plan)
        first, second = report["tasks"]
        self.assertFalse(first["baseline_cache_reused"])
        self.assertTrue(second["baseline_cache_reused"])
        self.assertEqual(first["tree_sha"], second["tree_sha"])
        lock = json.loads(
            (
                self.bench
                / "batch/baselines"
                / self.base
                / "baseline-lock.json"
            ).read_text()
        )
        _, repeated_manifest = checkout_manifest(
            self.bench / "batch/baselines" / self.base / "repository"
        )
        self.assertEqual(repeated_manifest, lock["checkout_manifest_sha256"])


    def test_pure_cache_and_three_independent_workspaces(self) -> None:
        report = provision_plan(
            plan=self.plan,
            plan_path=self.plan_path,
            approved_plan_id="fixture-plan",
            bench_root=self.bench,
            repository_root=self.root,
            source_repository=self.source,
        )
        self.assertEqual(report["status"], "TOPOLOGY_WARNING")
        cache = self.bench / "batch/baselines" / self.base / "repository"
        lock = json.loads(
            (cache.parent / "baseline-lock.json").read_text()
        )
        self.assertEqual(git(cache, "rev-parse", "HEAD"), self.base)
        self.assertFalse(
            subprocess.run(
                ["git", "-C", str(cache), "cat-file", "-e", self.head],
                check=False,
            ).returncode
            == 0
        )
        _, manifest = checkout_manifest(cache)
        self.assertEqual(manifest, lock["checkout_manifest_sha256"])
        for variant in ("openspec", "speckit", "cc-sdd"):
            workspace = (
                self.bench
                / "batch/workspaces/scrapy__scrapy__pr7"
                / variant
                / "repository"
            )
            audit = git_topology(
                workspace,
                base_sha=self.base,
                head_sha=self.head,
                merge_sha=None,
            )
            self.assertEqual(audit["status"], "PASS")
            self.assertEqual(git(workspace, "rev-parse", "HEAD"), self.base)


if __name__ == "__main__":
    unittest.main()
