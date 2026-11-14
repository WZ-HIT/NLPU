"""Build recipes must handle equal and different Scrapy distribution versions."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from batch.image_recipes import (
    DEFAULT_TEMPLATE_SHA,
    ImageError,
    METADATA_RENAME_LEGACY,
    METADATA_RENAME_SAFE,
    protect_metadata_rename,
    render_recipe,
    resolve_placeholders,
)


BENCH = Path(__file__).resolve().parents[2]


class MetadataRenameTests(unittest.TestCase):
    def exercise_rename(self, installed_version, baseline_version):
        with tempfile.TemporaryDirectory() as temporary:
            packages = Path(temporary) / "site-packages"
            original = packages / f"scrapy-{installed_version}.dist-info"
            original.mkdir(parents=True)
            metadata = b"Name: Scrapy\nVersion: baseline\n"
            (original / "METADATA").write_bytes(metadata)
            command = protect_metadata_rename(METADATA_RENAME_LEGACY)
            command = command.replace("/usr/local/lib/python3.11/site-packages", str(packages))
            command = command.replace("\\\n", "\n")
            environment = dict(os.environ, info=str(original), version=baseline_version)
            result = subprocess.run(["/bin/sh", "-eu", "-c", command], env=environment, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            expected = packages / f"scrapy-{baseline_version}.dist-info"
            self.assertEqual((expected / "METADATA").read_bytes(), metadata)
            self.assertEqual(list(packages.iterdir()), [expected])
            self.assertEqual(list(expected.iterdir()), [expected / "METADATA"])

    def test_same_version_preserves_directory_without_nested_move(self):
        self.exercise_rename("2.18.0", "2.18.0")

    def test_different_version_renames_directory_without_losing_metadata(self):
        self.exercise_rename("2.18.0", "2.17.0")

    def test_new_recipe_generated_from_frozen_template_contains_guard(self):
        products = render_recipe(
            BENCH / "batch/images" / DEFAULT_TEMPLATE_SHA,
            resolve_placeholders("a" * 40, "b" * 40),
            {"node_id": "tests/example.py::test_example"},
        )
        self.assertIn(METADATA_RENAME_SAFE, products["Dockerfile.baseline"])
        self.assertNotIn(METADATA_RENAME_LEGACY, products["Dockerfile.baseline"])

    def test_unrecognized_or_duplicate_rename_operation_is_rejected(self):
        for text in ("", METADATA_RENAME_LEGACY * 2, METADATA_RENAME_LEGACY + METADATA_RENAME_SAFE):
            with self.subTest(text=text), self.assertRaises(ImageError):
                protect_metadata_rename(text)


if __name__ == "__main__":
    unittest.main()
