from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch.core import (
    InputPaths,
    build_inventory,
    create_plan,
    read_pr_id_files,
    resolve_selection,
    validate_plan_inputs,
    write_inventory,
)


class SddBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.prompt = self.root / "prompt.json"
        self.raw = self.root / "raw.jsonl"
        self.inventory_json = self.root / "inventory.json"
        self.inventory_tsv = self.root / "inventory.tsv"
        self.raw_record = {
            "repo": "scrapy/scrapy",
            "pr_id": 8073,
            "base_sha": "1" * 40,
            "title": "Re-enable skipped tests",
            "body": "Check whether the reactor problem still applies.",
            "changed_files": [
                {
                    "filename": "tests/test_one.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 2,
                    "changes": 3,
                    "patch": "SECRET RAW PATCH",
                }
            ],
            "test_changes": [
                {
                    "node_id": "tests/test_one.py::test_one",
                    "file": "tests/test_one.py",
                    "qualified_name": "test_one",
                    "change_type": "modified",
                    "old_test": "SECRET OLD TEST",
                    "gold_test": "SECRET GOLD TEST",
                }
            ],
            "method_test_pairs": [],
        }
        self.sample_id = (
            "scrapy__scrapy__8073__test_only__"
            "5e3c308b532d055d"
        )
        # Use the implementation's generated ID instead of coupling the fixture
        # to a hand-computed digest.
        from batch.core import raw_member_samples

        self.sample_id = raw_member_samples(self.raw_record)[0]["sample_id"]
        self.prompt_record = {
            "repo": "scrapy/scrapy",
            "pr_id": 8073,
            "sample_id": self.sample_id,
            "prompt_type": "test_only",
            "old_test_file": "tests/test_one.py",
            "old_test_qualified_name": "test_one",
            "old_test": "SECRET OLD TEST",
            "prompt": "SECRET RENDERED PROMPT",
            "nl_description": "Re-enable skipped tests and check the reactor problem.",
        }
        self._write_inputs([self.prompt_record], [self.raw_record])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_inputs(self, prompts, raws) -> None:
        self.prompt.write_text(json.dumps(prompts), encoding="utf-8")
        self.raw.write_text(
            "".join(json.dumps(item) + "\n" for item in raws),
            encoding="utf-8",
        )

    def _inventory(self):
        inventory, indices = build_inventory(
            InputPaths(self.prompt, self.raw), self.root
        )
        write_inventory(inventory, self.inventory_json, self.inventory_tsv)
        return inventory, indices

    def test_inventory_aggregates_without_source_bodies(self) -> None:
        inventory, _ = self._inventory()
        pr = inventory["pull_requests"][0]
        self.assertEqual(pr["classification"], "TEST_ONLY_PR")
        self.assertEqual(pr["member_sample_count"], 1)
        self.assertEqual(pr["recorded_base_sha"], "1" * 40)
        serialized = json.dumps(inventory)
        self.assertNotIn("SECRET GOLD TEST", serialized)
        self.assertNotIn("SECRET OLD TEST", serialized)
        self.assertNotIn("SECRET RAW PATCH", serialized)
        self.assertNotIn("SECRET RENDERED PROMPT", serialized)

    def test_sample_selection_resolves_whole_pr(self) -> None:
        inventory, indices = self._inventory()
        resolved, events, errors = resolve_selection(
            inventory,
            indices,
            source="prompt",
            pr_ids=[],
            sample_ids=[self.sample_id],
        )
        self.assertFalse(errors)
        self.assertEqual(resolved, [("scrapy/scrapy", 8073)])
        plan = create_plan(
            plan_id="fixture-8073",
            inventory=inventory,
            inventory_path=self.inventory_json,
            source="prompt",
            requested_pr_ids=[],
            pr_id_files=[],
            requested_sample_ids=[self.sample_id],
            resolved=resolved,
            resolution_events=events,
            repository_root=self.root,
        )
        self.assertEqual(len(plan["tasks"]), 1)
        self.assertEqual(plan["tasks"][0]["member_sample_ids"], [self.sample_id])
        self.assertFalse(plan["executable"])

    def test_no_default_all_and_duplicate_and_missing_are_structured(self) -> None:
        inventory, indices = self._inventory()
        _, _, no_selection = resolve_selection(
            inventory, indices, source="prompt", pr_ids=[], sample_ids=[]
        )
        self.assertEqual(no_selection[0]["code"], "NO_EXPLICIT_SELECTION")
        _, _, duplicate = resolve_selection(
            inventory, indices, source="prompt", pr_ids=[8073, 8073], sample_ids=[]
        )
        self.assertIn("DUPLICATE_PR_SELECTION", {item["code"] for item in duplicate})
        _, _, missing = resolve_selection(
            inventory, indices, source="prompt", pr_ids=[999999], sample_ids=[]
        )
        self.assertEqual(missing[0]["code"], "PR_NOT_FOUND_IN_SOURCE")

    def test_cross_repository_and_nonunique_sample_are_structured(self) -> None:
        inventory, indices = self._inventory()
        _, _, cross = resolve_selection(
            inventory,
            indices,
            source="prompt",
            pr_ids=[],
            sample_ids=["other__repo__7__test_only__abc"],
        )
        self.assertEqual(cross[0]["code"], "CROSS_REPOSITORY_SELECTION")
        altered = copy.deepcopy(indices)
        altered["prompt_sample"][self.sample_id] = [
            ("scrapy/scrapy", 8073),
            ("other/repo", 8073),
        ]
        _, _, ambiguous = resolve_selection(
            inventory,
            altered,
            source="prompt",
            pr_ids=[],
            sample_ids=[self.sample_id],
        )
        self.assertEqual(ambiguous[0]["code"], "AMBIGUOUS_SAMPLE_ID")

    def test_plan_invalidates_when_prompt_hash_changes(self) -> None:
        inventory, indices = self._inventory()
        resolved, events, errors = resolve_selection(
            inventory, indices, source="raw", pr_ids=[8073], sample_ids=[]
        )
        self.assertFalse(errors)
        plan = create_plan(
            plan_id="hash-check",
            inventory=inventory,
            inventory_path=self.inventory_json,
            source="raw",
            requested_pr_ids=[8073],
            pr_id_files=[],
            requested_sample_ids=[],
            resolved=resolved,
            resolution_events=events,
            repository_root=self.root,
        )
        self.assertTrue(validate_plan_inputs(plan, self.root)["valid"])
        self.prompt.write_text("[]\n", encoding="utf-8")
        result = validate_plan_inputs(plan, self.root)
        self.assertFalse(result["valid"])
        self.assertIn("INPUT_HASH_MISMATCH", {e["code"] for e in result["errors"]})

    def test_plan_invalidates_when_pr_id_file_changes(self) -> None:
        inventory, indices = self._inventory()
        selector = self.root / "pr-ids.txt"
        selector.write_text("8073\n", encoding="utf-8")
        file_pr_ids, file_records, file_errors = read_pr_id_files([selector])
        self.assertFalse(file_errors)
        resolved, events, errors = resolve_selection(
            inventory,
            indices,
            source="prompt",
            pr_ids=file_pr_ids,
            sample_ids=[],
        )
        self.assertFalse(errors)
        plan = create_plan(
            plan_id="selector-hash-check",
            inventory=inventory,
            inventory_path=self.inventory_json,
            source="prompt",
            requested_pr_ids=file_pr_ids,
            pr_id_files=file_records,
            requested_sample_ids=[],
            resolved=resolved,
            resolution_events=events,
            repository_root=self.root,
        )
        self.assertTrue(validate_plan_inputs(plan, self.root)["valid"])
        selector.write_text("8074\n", encoding="utf-8")
        result = validate_plan_inputs(plan, self.root)
        self.assertFalse(result["valid"])
        self.assertIn(
            "SELECTION_FILE_HASH_MISMATCH",
            {error["code"] for error in result["errors"]},
        )

    def test_all_four_classifications(self) -> None:
        mixed = copy.deepcopy(self.raw_record)
        mixed["pr_id"] = 8074
        mixed["base_sha"] = "2" * 40
        mixed["changed_files"].append({"filename": "scrapy/core.py"})
        no_test = copy.deepcopy(self.raw_record)
        no_test["pr_id"] = 8075
        no_test["base_sha"] = "3" * 40
        no_test["changed_files"] = [{"filename": "docs/index.rst"}]
        invalid = copy.deepcopy(self.raw_record)
        invalid["pr_id"] = 8076
        invalid["base_sha"] = "bad"
        prompts = [self.prompt_record]
        for pr_id in (8074, 8075, 8076):
            prompt = copy.deepcopy(self.prompt_record)
            prompt["pr_id"] = pr_id
            prompt["sample_id"] = f"scrapy__scrapy__{pr_id}__test_only__fixture"
            prompts.append(prompt)
        self._write_inputs(prompts, [self.raw_record, mixed, no_test, invalid])
        inventory, _ = build_inventory(
            InputPaths(self.prompt, self.raw), self.root
        )
        classifications = {
            pr["pr_id"]: pr["classification"]
            for pr in inventory["pull_requests"]
        }
        self.assertEqual(classifications[8073], "TEST_ONLY_PR")
        self.assertEqual(classifications[8074], "MIXED_CODE_AND_TEST_PR")
        self.assertEqual(classifications[8075], "NO_TEST_CHANGE")
        self.assertEqual(classifications[8076], "INVALID_INPUT")

    def test_raw_pr_without_prompt_sample_is_not_an_inventory_task(self) -> None:
        raw_only = copy.deepcopy(self.raw_record)
        raw_only["pr_id"] = 9999
        raw_only["base_sha"] = "9" * 40
        self._write_inputs([self.prompt_record], [self.raw_record, raw_only])
        inventory, indices = build_inventory(
            InputPaths(self.prompt, self.raw), self.root
        )
        self.assertEqual(
            [(pr["repository"], pr["pr_id"]) for pr in inventory["pull_requests"]],
            [("scrapy/scrapy", 8073)],
        )
        self.assertNotIn(9999, indices["raw_pr"])


class CurrentPr8073IntegrationTests(unittest.TestCase):
    def test_current_inputs_resolve_all_three_samples_to_one_pr_task(self) -> None:
        prompt = ROOT / "output/prompt/scrapy__scrapy.json"
        raw = ROOT / "output/raw_prs/scrapy__scrapy.jsonl"
        inventory, indices = build_inventory(InputPaths(prompt, raw), ROOT)
        pr = next(
            item
            for item in inventory["pull_requests"]
            if item["repository"] == "scrapy/scrapy" and item["pr_id"] == 8073
        )
        self.assertEqual(pr["classification"], "TEST_ONLY_PR")
        self.assertEqual(pr["member_sample_count"], 3)
        resolved, _, errors = resolve_selection(
            inventory, indices, source="prompt", pr_ids=[8073], sample_ids=[]
        )
        self.assertFalse(errors)
        self.assertEqual(resolved, [("scrapy/scrapy", 8073)])


if __name__ == "__main__":
    unittest.main()
