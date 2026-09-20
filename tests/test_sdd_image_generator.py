"""Tests for the per-base image recipe generator.

The fixture copies the real recipe directory rather than synthesizing one. The
rule table is anchored on the exact line shapes that directory contains, so a
synthetic stand-in would let the generator and the test agree on a template the
bench does not actually have.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "sdd-bench/scrapy-sdd"
sys.path.insert(0, str(BENCH))

from batch import image_cli, image_recipes
from batch.image_recipes import ImageError

TEMPLATE_SHA = image_recipes.DEFAULT_TEMPLATE_SHA
TEMPLATE_DIR = BENCH / "batch/images" / TEMPLATE_SHA

SMOKE_PATH = "tests/test_toplevel.py"
SMOKE_FALLBACK_PATH = "tests/test_poet.py"


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def recipe_files() -> list[str]:
    """Every file a recipe directory holds, rules and verbatim copies together."""
    return sorted({rule.path for rule in image_recipes.RULES} | set(image_recipes.VERBATIM_FILES))


def run_cli(argv: list[str]) -> tuple[int, str]:
    """Run the CLI and keep its output; the envelope is what the assertions read."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        code = image_cli.run(argv)
    return code, buffer.getvalue()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        text=True,
    ).stdout.strip()


class BenchFixture:
    """A miniature bench holding one real recipe and one provisioned baseline."""

    def __init__(self, root: Path, template_sha: str = TEMPLATE_SHA) -> None:
        self.repository_root = root
        self.bench = root / "sdd-bench/scrapy-sdd"
        self.template_sha = template_sha
        self.template = self.bench / "batch/images" / template_sha
        self._write_template()
        self._write_raw_records()
        self.template_tree = json.loads(
            (BENCH / "batch/baselines" / template_sha / "baseline-lock.json").read_text(encoding="utf-8")
        )["tree_sha"]
        write_json(
            self.bench / "batch/baselines" / template_sha / "baseline-lock.json",
            {"base_sha": template_sha, "tree_sha": self.template_tree},
        )
        self.new_sha = self.provision("first")

    def _write_template(self) -> None:
        self.template.mkdir(parents=True)
        for source in sorted(TEMPLATE_DIR.iterdir()):
            # deployment-lock.json is the product of a build, not a recipe input.
            if source.is_file() and source.name != "deployment-lock.json":
                shutil.copy2(source, self.template / source.name)

    def _write_raw_records(
        self, paths: tuple[str, ...] = ("scrapy/downloadermiddlewares/httpcompression.py",)
    ) -> None:
        self.raw_path = self.repository_root / image_recipes.RAW_RECORDS
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "repo": "scrapy/scrapy",
                "pr_id": 7001,
                "changed_files": [{"filename": path} for path in paths],
                "test_changes": [],
            }
        ]
        self.raw_path.write_text(
            "\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8"
        )

    def provision(self, label: str) -> str:
        """Commit a baseline and cache it under its real sha, returning that sha.

        The base sha is not invented: ``select_smoke_target`` asks git for a blob
        at that revision, so a placeholder would make every candidate look absent.
        The directory is therefore named only after the commit exists, which is
        why the repository is built aside and moved into place.
        """
        staging = self.repository_root / f".staging-{label}"
        repository = staging / "repository"
        (repository / "tests").mkdir(parents=True)
        (repository / SMOKE_PATH).write_text(
            "import scrapy\n\n\ndef test_version():\n    assert isinstance(scrapy.__version__, str)\n",
            encoding="utf-8",
        )
        (repository / SMOKE_FALLBACK_PATH).write_text(
            "def test_callbacks():\n    assert True\n", encoding="utf-8"
        )
        git(repository, "init", "-q", "-b", "main")
        git(repository, "config", "user.email", "fixture@example.invalid")
        git(repository, "config", "user.name", "fixture")
        git(repository, "config", "commit.gpgsign", "false")
        git(repository, "add", "-A")
        # The label goes into the message so two baselines cannot collide on a sha
        # when they are committed within the same second.
        git(repository, "commit", "-q", "-m", f"base {label}")

        commit = git(repository, "rev-parse", "HEAD")
        target = self.bench / "batch/baselines" / commit
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(staging), str(target))
        write_json(
            target / "baseline-lock.json",
            {
                "base_sha": commit,
                "tree_sha": git(target / "repository", "rev-parse", "HEAD^{tree}"),
            },
        )
        self.last_sha = commit
        return commit

    def create(self, base_sha: str | None = None, template_sha: str | None = None) -> tuple[int, str]:
        argv = [
            "--bench-root", str(self.bench),
            "create", "--base-sha", base_sha or self.new_sha,
        ]
        if template_sha is not None:
            argv += ["--template-sha", template_sha]
        return run_cli(argv)

    def verify(self, argv: list[str]) -> tuple[int, str]:
        return run_cli(["--bench-root", str(self.bench), "verify", *argv])

    def product(self, base_sha: str | None = None) -> Path:
        return self.bench / "batch/images" / (base_sha or self.new_sha)


class RunAssertions(unittest.TestCase):
    """Shared helper only; it defines no tests of its own."""

    def assertRun(self, result: tuple[int, str], expected: int) -> str:
        """Assert the exit code and return the envelope the caller wants to read.

        The message is the output rather than a bare code: a refusal that prints
        the wrong reason is a different bug from one that refuses at all.
        """
        code, output = result
        self.assertEqual(code, expected, output)
        return output


class RecipeGeneratorTests(RunAssertions):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory(prefix="sdd-image-test-")
        self.addCleanup(self._temporary.cleanup)
        self.root = Path(self._temporary.name)
        self.fixture = BenchFixture(self.root)

    # -- 1. the happy path -------------------------------------------------

    def test_create_writes_a_recipe(self) -> None:
        self.assertRun(self.fixture.create(), 0)

        directory = self.fixture.product()
        self.assertTrue(directory.is_dir())
        # A recipe is written all at once or not at all, so no staging survives.
        self.assertFalse(any(
            path.name.startswith(".") and path.name.endswith(".tmp")
            for path in (self.fixture.bench / "batch/images").iterdir()
        ))
        for name in image_recipes.VERBATIM_FILES:
            self.assertEqual(
                (directory / name).read_bytes(),
                (self.fixture.template / name).read_bytes(),
                f"{name} must be copied verbatim",
            )
        # Only build-images.sh may write it: its READY status means the audit ran.
        self.assertFalse((directory / "deployment-lock.json").exists())
        self.assertRun(self.fixture.verify(["--base-sha", self.fixture.new_sha]), 0)

    def test_every_rule_matches_its_declared_line_count(self) -> None:
        # create() refuses otherwise, so reaching a product proves the anchors
        # held; this asserts the count directly for the failure message's sake.
        self.assertRun(self.fixture.create(), 0)
        directory = self.fixture.product()
        for rule in image_recipes.RULES:
            text = (directory / rule.path).read_text(encoding="utf-8")
            self.assertEqual(
                len(rule.compiled().findall(text)),
                rule.expected,
                f"{rule.path}: {rule.why}",
            )

    # -- 2. the cross-base images are not collateral -----------------------

    def test_shared_images_are_copied_unchanged(self) -> None:
        self.assertRun(self.fixture.create(), 0)
        directory = self.fixture.product()
        for constant in image_recipes.SHARED_IMAGES:
            expected = sum(
                (self.fixture.template / name).read_text(encoding="utf-8").count(constant)
                for name in recipe_files()
            )
            actual = sum(
                (directory / name).read_text(encoding="utf-8").count(constant)
                for name in recipe_files()
            )
            self.assertEqual(actual, expected, constant)
            self.assertGreater(expected, 0, f"{constant} should be in the template at all")

    def test_shared_image_rewrite_is_refused(self) -> None:
        """Replacing a cross-base tag fails at the generator, not at docker build."""
        text = "a scrapy-sdd-scrapy:base-11079cb1c85b-py311 b"
        with self.assertRaises(ImageError) as caught:
            image_recipes.check_shared_images(text, text.replace("11079cb1c85b", self.fixture.new_sha[:12]))
        self.assertEqual(caught.exception.code, "SHARED_IMAGE_REWRITTEN")

    # -- 3. no stale identity survives -------------------------------------

    def test_no_template_identity_survives(self) -> None:
        self.assertRun(self.fixture.create(), 0)
        joined = "".join(
            (self.fixture.product() / path.name).read_text(encoding="utf-8")
            for path in sorted(self.fixture.product().iterdir())
            if path.is_file()
        )
        self.assertNotIn(TEMPLATE_SHA, joined)
        self.assertNotIn(self.fixture.template_tree, joined)

    def test_stale_identity_is_reported(self) -> None:
        """The check separately names the 40-hex and 12-hex forms it rejected."""
        with self.assertRaises(ImageError) as caught:
            image_recipes.check_no_foreign_hex(
                f"image='x:{'b' * 40}' run_id=\"{'c' * 12}-a\"",
                {"base": self.fixture.new_sha, "tree": "d" * 40, "base12": self.fixture.new_sha[:12]},
            )
        self.assertEqual(caught.exception.code, "FOREIGN_HEX_IDENTIFIER")
        self.assertEqual(caught.exception.detail["stray_40"], ["b" * 40])
        self.assertEqual(caught.exception.detail["stray_12"], ["c" * 12])

    def test_identifiers_inside_a_sha256_are_not_reported(self) -> None:
        # A 64-hex digest must not yield a 40-hex or 12-hex token, or every
        # sha256 in the recipe would be a false positive.
        digest = "sha256:" + "ab" * 32
        found_40, found_12 = image_recipes.hex_tokens(digest)
        self.assertEqual((found_40, found_12), (set(), set()))

    # -- 4. run-stage.sh is parameterized (R1) -----------------------------

    def test_run_stage_is_parameterized(self) -> None:
        """A recipe whose run-stage.sh names another base runs the wrong image.

        record-deployment.py executes this file to collect the stage-isolation
        evidence, so a stale image tag makes the audit prove isolation of an
        image it does not describe.
        """
        self.assertRun(self.fixture.create(), 0)
        text = (self.fixture.product() / "run-stage.sh").read_text(encoding="utf-8")

        image_line = next(line for line in text.splitlines() if line.startswith("image="))
        self.assertEqual(image_line, f"image='scrapy-sdd-batch-agent:{self.fixture.new_sha}'")

        run_id_line = next(line for line in text.splitlines() if line.startswith("run_id="))
        self.assertTrue(run_id_line.startswith(f'run_id="{self.fixture.new_sha[:12]}-'))

    def test_verify_rejects_a_stale_run_stage(self) -> None:
        """verify() must read the bytes on disk, not a rewritten copy of them."""
        self.assertRun(self.fixture.create(), 0)
        run_stage = self.fixture.product() / "run-stage.sh"
        run_stage.write_text(
            run_stage.read_text(encoding="utf-8").replace(self.fixture.new_sha, TEMPLATE_SHA),
            encoding="utf-8",
        )
        output = self.assertRun(self.fixture.verify(["--base-sha", self.fixture.new_sha]), 2)
        document = json.loads(output)
        self.assertEqual(document["errors"][0]["code"], "FOREIGN_HEX_IDENTIFIER")

    # -- 5/7. refusals -----------------------------------------------------

    def test_refuses_to_overwrite_a_recipe(self) -> None:
        self.assertRun(self.fixture.create(), 0)
        marker = self.fixture.product() / "build-images.sh"
        before = marker.read_bytes()

        output = self.assertRun(self.fixture.create(), 2)
        self.assertEqual(json.loads(output)["errors"][0]["code"], "IMAGE_DIR_EXISTS")
        self.assertEqual(marker.read_bytes(), before)

    def test_refuses_to_overwrite_an_image_audit(self) -> None:
        audit = self.fixture.bench / "batch/audits/images" / f"{self.fixture.new_sha}-image-audit.json"
        write_json(audit, {"status": "PASS"})

        output = self.assertRun(self.fixture.create(), 2)
        self.assertEqual(json.loads(output)["errors"][0]["code"], "IMAGE_AUDIT_EXISTS")
        self.assertFalse(self.fixture.product().exists())

    def test_refuses_a_base_without_a_baseline(self) -> None:
        missing = "b" * 40
        output = self.assertRun(self.fixture.create(missing), 2)
        self.assertEqual(
            json.loads(output)["errors"][0]["code"], "BASELINE_NOT_PROVISIONED"
        )
        self.assertFalse(self.fixture.product(missing).exists())

    def test_refuses_the_root_base(self) -> None:
        output = self.assertRun(self.fixture.create(image_recipes.ROOT_BASE_SHA), 2)
        self.assertEqual(
            json.loads(output)["errors"][0]["code"], "ROOT_BASE_NOT_GENERATED"
        )

    # -- 6. template drift -------------------------------------------------

    def test_refuses_a_drifted_template(self) -> None:
        """An anchor that no longer matches would silently skip its edit."""
        drifted = self.fixture.template / "build-images.sh"
        drifted.write_text(
            drifted.read_text(encoding="utf-8").replace("BASE_SHA=", "BASE_COMMIT="),
            encoding="utf-8",
        )
        output = self.assertRun(self.fixture.create(), 2)
        self.assertEqual(json.loads(output)["errors"][0]["code"], "RULE_ANCHOR_MISMATCH")
        self.assertFalse(self.fixture.product().exists())

    def test_refuses_an_ambiguous_anchor(self) -> None:
        """A duplicated label line would make the edit land twice or not at all."""
        drifted = self.fixture.template / "Dockerfile.baseline"
        drifted.write_text(
            drifted.read_text(encoding="utf-8").replace(
                '      bench.base-sha="',
                '      bench.base-sha="' + "f" * 40 + '"\n      bench.base-sha="',
                1,
            ),
            encoding="utf-8",
        )
        output = self.assertRun(self.fixture.create(), 2)
        self.assertEqual(json.loads(output)["errors"][0]["code"], "RULE_ANCHOR_MISMATCH")

    def test_refuses_a_missing_template_file(self) -> None:
        (self.fixture.template / "verify-inputs.py").unlink()
        output = self.assertRun(self.fixture.create(), 2)
        self.assertEqual(
            json.loads(output)["errors"][0]["code"], "TEMPLATE_FILE_MISSING"
        )

    # -- 8. smoke target selection -----------------------------------------

    def test_smoke_target_is_gold_blind(self) -> None:
        chosen = image_recipes.select_smoke_target(
            self.fixture.bench, self.fixture.repository_root, self.fixture.new_sha
        )
        self.assertEqual(chosen["path"], SMOKE_PATH)
        self.assertEqual(chosen["node_id"], f"{SMOKE_PATH}::test_version")
        self.assertEqual(chosen["argv"][-1], chosen["node_id"])
        self.assertFalse(chosen["gold_blindness"]["path_in_touched_files"])
        self.assertTrue(chosen["base_evidence"]["present_at_base"])
        self.assertEqual(chosen["rejected"], [])

    def test_smoke_target_falls_back_when_the_first_is_touched(self) -> None:
        self.fixture._write_raw_records((SMOKE_PATH,))
        chosen = image_recipes.select_smoke_target(
            self.fixture.bench, self.fixture.repository_root, self.fixture.new_sha
        )
        self.assertEqual(chosen["path"], SMOKE_FALLBACK_PATH)
        self.assertEqual(chosen["selected_rank"], 1)
        self.assertEqual(
            [item["node_id"] for item in chosen["rejected"]], [f"{SMOKE_PATH}::test_version"]
        )

    def test_smoke_target_refuses_when_every_candidate_is_touched(self) -> None:
        self.fixture._write_raw_records((SMOKE_PATH, SMOKE_FALLBACK_PATH))
        with self.assertRaises(ImageError) as caught:
            image_recipes.select_smoke_target(
                self.fixture.bench, self.fixture.repository_root, self.fixture.new_sha
            )
        self.assertEqual(caught.exception.code, "SMOKE_TARGET_UNAVAILABLE")

    def test_smoke_selection_is_reproducible(self) -> None:
        """The record is evidence, so it must not carry a timestamp or a pid."""
        first = image_recipes.select_smoke_target(
            self.fixture.bench, self.fixture.repository_root, self.fixture.new_sha
        )
        second = image_recipes.select_smoke_target(
            self.fixture.bench, self.fixture.repository_root, self.fixture.new_sha
        )
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    # -- 9. the cross-directory invariant ----------------------------------

    def test_all_accepts_recipes_that_differ_only_where_rules_allow(self) -> None:
        self.assertRun(self.fixture.create(), 0)
        second = self.fixture.provision("second")
        self.assertRun(self.fixture.create(second), 0)

        self.assertRun(self.fixture.verify(["--all"]), 0)

    def test_all_rejects_recipes_that_diverge_elsewhere(self) -> None:
        self.assertRun(self.fixture.create(), 0)
        second = self.fixture.provision("second")
        self.assertRun(self.fixture.create(second), 0)

        entrypoint = self.fixture.product(second) / "entrypoint.sh"
        entrypoint.write_text(
            entrypoint.read_text(encoding="utf-8") + "\n# hand edit\n", encoding="utf-8"
        )
        output = self.assertRun(self.fixture.verify(["--all"]), 2)
        document = json.loads(output)
        self.assertEqual(document["errors"][0]["code"], "RECIPES_DIVERGE")
        self.assertEqual(document["errors"][0]["differing"], ["entrypoint.sh"])

    def test_all_skips_the_root_base(self) -> None:
        """The root base is the ancestor of every recipe, not an instance of one."""
        self.assertRun(self.fixture.create(), 0)
        root = self.fixture.bench / "batch/images" / image_recipes.ROOT_BASE_SHA
        root.mkdir(parents=True)
        (root / "build-images.sh").write_text("#!/bin/sh\n", encoding="utf-8")

        output = self.assertRun(self.fixture.verify(["--all"]), 0)
        self.assertEqual(
            json.loads(output)["root_skipped"], image_recipes.ROOT_BASE_SHA
        )


class ShippedRecipeTests(RunAssertions):
    """The recipes actually in the bench, checked without a fixture."""

    def test_shipped_recipes_verify(self) -> None:
        output = self.assertRun(run_cli(["--bench-root", str(BENCH), "verify", "--all"]), 0)
        document = json.loads(output)
        self.assertEqual(document["status"], "PASS")
        self.assertIn(TEMPLATE_SHA, [item["base_sha"] for item in document["verified"]])

    def test_shipped_template_headers_are_not_gold_bearing(self) -> None:
        """The recipe is shipped to a build context, so its names must stay clean."""
        forbidden = ("raw_prs", "gold_patch", "gold_test")
        for name in ("Dockerfile.baseline", "Dockerfile.agent"):
            text = (TEMPLATE_DIR / name).read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{name} carries {token}")


if __name__ == "__main__":
    unittest.main()
