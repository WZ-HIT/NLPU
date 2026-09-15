from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from build_prompts import build_prompt_outputs

from experiment.prompts import build_method_dataset, build_method_prompts


class MethodPromptTests(unittest.TestCase):
    def raw_record(self) -> SimpleNamespace:
        return SimpleNamespace(
            repo="acme/widgets",
            pr_id=7,
            title="Normalize widget values consistently",
            body="Make normalized values lowercase after trimming whitespace.",
            merged=True,
            ci_status="success",
            comments=[],
            review_comments=[],
            commit_messages=["Normalize widget values consistently"],
            mining_status="mined",
            mining_reasons=[],
            test_changes=[],
            method_test_pairs=[
                {
                    "sample_id": "acme__widgets__7__abc",
                    "eligibility": "accepted",
                    "pair_confidence": "high",
                    "pair_evidence": ["static_call"],
                    "focal_method": {
                        "file": "widgets/core.py",
                        "qualified_name": "normalize",
                        "after_source": "def normalize(value):\n    return value.strip().lower()",
                        "before_source": "SECRET OLD FOCAL",
                    },
                    "test_change": {
                        "file": "tests/test_core.py",
                        "qualified_name": "test_normalize",
                        "change_type": "modified",
                        "old_test": "def test_normalize():\n    assert normalize(' X ') == 'X'",
                        "gold_test": "SECRET GOLD TEST",
                    },
                }
            ],
        )

    def test_method_prompt_contains_allowed_inputs_only(self) -> None:
        dataset = build_method_dataset([self.raw_record()])
        prompts = build_method_prompts(dataset)
        serialized = json.dumps(prompts)

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["prompt_type"], "focal_guided")
        self.assertTrue(prompts[0]["focal_available"])
        self.assertIn("focal_method_after", prompts[0])
        self.assertIn("old_test", prompts[0])
        self.assertIn("Post-PR focal method", prompts[0]["prompt"])
        self.assertEqual(
            prompts[0]["nl_description"],
            "Normalize widget values consistently. Make normalized values lowercase after trimming whitespace",
        )
        self.assertIn("nl_description_extended", prompts[0])
        self.assertTrue(prompts[0]["prompt"].startswith("You are"))
        self.assertNotIn("SECRET GOLD TEST", serialized)
        self.assertNotIn("SECRET OLD FOCAL", serialized)
        self.assertNotIn("gold_test", serialized)

    def test_rejected_pair_is_rendered_without_focal(self) -> None:
        record = self.raw_record()
        record.method_test_pairs[0]["eligibility"] = "rejected"
        prompts = build_method_prompts(build_method_dataset([record]))

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["prompt_type"], "test_only")
        self.assertFalse(prompts[0]["focal_available"])
        self.assertIsNone(prompts[0]["focal_method_after"])
        self.assertNotIn("Post-PR focal method", prompts[0]["prompt"])

    def test_build_prompt_outputs_writes_existing_prompt_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_dir = root / "raw_prs"
            prompt_dir = root / "prompt"
            raw_dir.mkdir()
            (raw_dir / "acme__widgets.jsonl").write_text(
                json.dumps(vars(self.raw_record())) + "\n",
                encoding="utf-8",
            )

            result = build_prompt_outputs(raw_dir, prompt_dir)

            self.assertEqual(result["prompt_count"], 1)
            prompt_text = (prompt_dir / "acme__widgets.json").read_text(
                encoding="utf-8"
            )
            self.assertNotIn("SECRET GOLD TEST", prompt_text)
            manifest = json.loads(
                (prompt_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["mode"], "method")
            self.assertEqual(
                manifest["prompt_type_counts"],
                {"focal_guided": 1, "test_only": 0},
            )

    def test_unpaired_test_change_is_rendered_without_focal(self) -> None:
        record = self.raw_record()
        test_change = dict(record.method_test_pairs[0]["test_change"])
        record.method_test_pairs = []
        record.test_changes = [test_change]
        record.mining_status = "no_eligible_pairs"
        record.mining_reasons = ["no changed focal method was extracted"]

        dataset = build_method_dataset([record])
        prompts = build_method_prompts(dataset)

        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["prompt_type"], "test_only")
        self.assertFalse(prompts[0]["focal_available"])
        self.assertIsNone(prompts[0]["focal_method_after"])
        self.assertIn("No focal method was selected", prompts[0]["prompt"])
        self.assertNotIn("SECRET GOLD TEST", json.dumps(prompts))


if __name__ == "__main__":
    unittest.main()
