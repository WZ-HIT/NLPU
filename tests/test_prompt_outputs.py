from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_prompts import (
    group_prompts_by_repo,
    prompt_file_name,
    write_prompt_collection,
)


class PromptOutputTests(unittest.TestCase):
    def test_grouping_does_not_require_repo_in_rendered_prompt(self) -> None:
        dataset = [
            {"repo": "acme/widgets", "prompt": "first"},
            {"repo": "other/project", "prompt": "second"},
            {"repo": "acme/widgets", "prompt": "third"},
        ]
        prompts = [
            {"prompt": "first"},
            {"prompt": "second"},
            {"prompt": "third"},
        ]

        grouped = group_prompts_by_repo(dataset, prompts)

        self.assertEqual(
            grouped,
            {
                "acme/widgets": [{"prompt": "first"}, {"prompt": "third"}],
                "other/project": [{"prompt": "second"}],
            },
        )

    def test_repository_file_name(self) -> None:
        self.assertEqual(prompt_file_name("scrapy/scrapy"), "scrapy__scrapy.json")
        with self.assertRaises(ValueError):
            prompt_file_name("missing-separator")

    def test_writer_migrates_aggregate_file_and_removes_stale_repo_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            output_dir = Path(temporary_dir)
            (output_dir / "prompts.json").write_text("[]\n", encoding="utf-8")
            (output_dir / "manifest.json").write_text(
                json.dumps({"schema_version": 1, "prompts_file": "prompts.json"}),
                encoding="utf-8",
            )
            groups = {
                "acme/widgets": [{"prompt": "a"}],
                "other/project": [{"prompt": "b"}, {"prompt": "c"}],
            }

            files = write_prompt_collection(
                output_dir,
                groups,
                keep_fields=("prompt",),
                source_paths=[Path("output/raw_prs/acme__widgets.jsonl")],
                raw_count=2,
                kept_pr_count=2,
            )

            self.assertEqual(
                files,
                {
                    "acme/widgets": "acme__widgets.json",
                    "other/project": "other__project.json",
                },
            )
            self.assertFalse((output_dir / "prompts.json").exists())
            self.assertEqual(
                json.loads((output_dir / "other__project.json").read_text()),
                [{"prompt": "b"}, {"prompt": "c"}],
            )
            manifest = json.loads((output_dir / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["prompt_count"], 3)
            self.assertEqual(
                manifest["prompt_counts"],
                {"acme/widgets": 1, "other/project": 2},
            )

            write_prompt_collection(
                output_dir,
                {"acme/widgets": [{"prompt": "new"}]},
                keep_fields=("prompt",),
                source_paths=[],
                raw_count=1,
                kept_pr_count=1,
            )
            self.assertFalse((output_dir / "other__project.json").exists())


if __name__ == "__main__":
    unittest.main()
