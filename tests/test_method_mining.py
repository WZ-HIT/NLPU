from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiment.ast_extract import extract_changed_definitions, extract_definitions
from experiment.mine_samples import _candidate_reasons, mine_raw_directory
from experiment.pair_tests import pair_changed_tests


class AstExtractionTests(unittest.TestCase):
    def test_extracts_decorated_test_and_changed_focal_method(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "base"
            head = root / "head"
            for checkout in (base, head):
                (checkout / "pkg").mkdir(parents=True)
                (checkout / "tests").mkdir(parents=True)

            (base / "pkg/core.py").write_text(
                "def normalize(value):\n"
                "    return value.strip()\n\n"
                "def public(value):\n"
                "    return normalize(value)\n",
                encoding="utf-8",
            )
            (head / "pkg/core.py").write_text(
                "def normalize(value):\n"
                "    return value.strip().lower()\n\n"
                "def public(value):\n"
                "    return normalize(value)\n",
                encoding="utf-8",
            )
            (base / "tests/test_core.py").write_text(
                "import pytest\n"
                "from pkg.core import public\n\n"
                "@pytest.mark.parametrize('value', [' X '])\n"
                "def test_public(value):\n"
                "    assert public(value) == 'X'\n",
                encoding="utf-8",
            )
            (head / "tests/test_core.py").write_text(
                "import pytest\n"
                "from pkg.core import public\n\n"
                "@pytest.mark.parametrize('value', [' X '])\n"
                "def test_public(value):\n"
                "    assert public(value) == 'x'\n",
                encoding="utf-8",
            )
            changed_files = [
                {"filename": "pkg/core.py"},
                {"filename": "tests/test_core.py"},
            ]

            extracted = extract_changed_definitions(base, head, changed_files)

            self.assertEqual(
                [item["qualified_name"] for item in extracted["focal_methods"]],
                ["normalize"],
            )
            self.assertEqual(len(extracted["test_changes"]), 1)
            test_change = extracted["test_changes"][0]
            self.assertTrue(test_change["old_test"].startswith("@pytest.mark.parametrize"))
            self.assertIn("== 'x'", test_change["gold_test"])
            self.assertNotIn("before_source", test_change)
            self.assertNotIn("after_source", test_change)

            pairs = pair_changed_tests(
                "acme/widgets",
                7,
                extracted["focal_methods"],
                extracted["test_changes"],
                extracted["supporting_definitions"],
                changed_files,
                ci_status="success",
            )
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]["eligibility"], "accepted")
            self.assertIn("static_call_path", pairs[0]["pair_evidence"])
            self.assertEqual(pairs[0]["gold_validation"]["gold_on_head"], "pass")

    def test_extracts_async_class_method_with_qualified_name(self) -> None:
        definitions = extract_definitions(
            "class Client:\n"
            "    @staticmethod\n"
            "    async def fetch(url):\n"
            "        return await request(url)\n",
            "pkg/client.py",
        )

        self.assertEqual(definitions[0].qualified_name, "Client.fetch")
        self.assertEqual(definitions[0].kind, "async_method")
        self.assertEqual(definitions[0].decorators, ("staticmethod",))
        self.assertIn("request", definitions[0].calls)


class MiningProgressTests(unittest.TestCase):
    def test_test_only_pr_is_not_blocked_by_missing_production_file(self) -> None:
        reasons = _candidate_reasons(
            {
                "merged": True,
                "ci_status": "success",
                "changed_files": [{"filename": "tests/test_only.py"}],
            }
        )
        self.assertEqual(reasons, [])

    def test_reports_selected_start_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_dir = root / "raw_prs"
            raw_dir.mkdir()
            record = {
                "repo": "acme/widgets",
                "pr_id": 7,
                "merged": True,
                "ci_status": "success",
                "changed_files": [],
            }
            (raw_dir / "acme__widgets.jsonl").write_text(
                json.dumps(record) + "\n",
                encoding="utf-8",
            )
            messages: list[str] = []

            mine_raw_directory(
                raw_dir,
                object(),  # type: ignore[arg-type]
                backfill_metadata=False,
                progress=messages.append,
            )

            self.assertEqual(
                messages[0], "[mine] Selected 1 PR record(s) for method mining"
            )
            self.assertEqual(messages[1], "[mine 1/1] acme/widgets#7: starting")
            self.assertIn("[mine 1/1] acme/widgets#7: skipped", messages[2])


if __name__ == "__main__":
    unittest.main()
