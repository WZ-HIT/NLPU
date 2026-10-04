"""Generate and verify the per-base image build recipes under ``batch/images/``.

Every base a batch pins needs its own ``batch/images/<base_sha>/`` directory,
because ``scaffold`` refuses to build a task whose deployment lock is not READY
and ``gold-check`` additionally refuses one whose image audit is not PASS. Both
documents are written by the recipe in that directory. Until this module existed
the directory was produced by copying a sibling and editing the SHA labels by
hand, which is a five-edit operation per base whose failure mode -- a mismatched
label -- surfaces two stages later as a Docker image id mismatch.

The recipe is a fixed set of files with the base identity substituted in eight
places. That is the whole transform, so the generator asserts it rather than
re-deriving it: any line the rule table does not cover is copied verbatim, and
``verify`` re-checks that no hex identifier other than the base, its tree, and
the two cross-base images survives.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


BENCH_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = BENCH_ROOT.parents[1]

RAW_RECORDS = Path("output/raw_prs/scrapy__scrapy.jsonl")
INVENTORY = Path("batch/inventories/scrapy-pr-inventory.json")

# The canonical recipe. Chosen explicitly rather than by directory mtime: the
# root base below also has a directory here, it sorts first, and it is a
# different (older) recipe that lacks the purebase build context.
DEFAULT_TEMPLATE_SHA = "3857c6906b2da51e12ca6005434512b7704fd659"

# The one base that is not generated from another: it predates the ``purebase``
# build context, and it is the FROM of the shared source baseline image. Its
# directory is the ancestor of every recipe rather than an instance of one.
ROOT_BASE_SHA = "11079cb1c85b9e75a39a7269943c69d1a975d485"

# Five frozen recipes predate the per-base installed-Scrapy audit. Their recipe
# bytes are historical evidence, so verify their masked template against this
# pinned digest instead of comparing them with the newer generated cohort.
HISTORICAL_RECIPE_BASES = frozenset({
    "1420418c813ed01af78da62bc4a6e60bb4a7403b",
    "916039ca4ca79ea4ed38e74d71e25c2584c1925e",
    "e01783a493b7224ee616a97a310da8d19da11966",
    "da7c2fc59e286e796d0f8cfe01d4363d6fa3729f",
    "4f0b5fa5c3a275b068bc4e028dfd09dd2f878bc0",
})
HISTORICAL_MASKED_RECIPE_SHA256 = "108ffb285d726a75b1c2aa5860bd419f1c83b1f6985c291164da83ce6fe0f158"

# A pinned audit revision used by new bases whose gold excerpt already exists
# unchanged in the frozen baseline tree. The historical recipe remains byte-for-byte frozen.
BASELINE_NATIVE_AUDIT_SHA256 = "197fefc70ab171a1b18977af2bbc254be8eb6e49a3b5ef9b16f48616b3e8c26c"

# Images shared by every base. Their names embed the root base sha, so a naive
# ``s/11079cb1c85b/<new>/`` corrupts them and ``build-images.sh`` later aborts
# with "immutable source baseline ID mismatch", far from the edit.
SHARED_IMAGES = (
    "scrapy-sdd-scrapy:base-11079cb1c85b-py311",
    "sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa",
    "scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate",
    "sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9",
)

# 12-hex tokens that are a base sha neither of the directory nor of its tree.
# Enumerated from the template: the root base inside the shared image names, and
# the speckit artifact directory hash. A new one appearing means a recipe grew a
# reference the rule table does not know about, which is what this set detects.
SHARED_HEX_12 = frozenset({"11079cb1c85b", "cb610277fdea"})

# Copied byte for byte. The self-check re-reads them from the template rather
# than trusting the copy, so a truncated or partially-written file fails here
# instead of inside a Docker build.
VERBATIM_FILES = (
    "record-deployment.py",
    "verify-inputs.py",
    "entrypoint.sh",
    "sitecustomize.py",
    ".dockerignore",
)

# Written by ``create``, not copied. Optional on disk because the directories
# frozen before this generator existed do not have one and fall back to the
# adapter's smoke target. ``deployment-lock.json`` is deliberately absent from
# both lists: only ``build-images.sh`` may write it, because its READY status
# means the audit actually ran.
OPTIONAL_FILES = ("smoke-test.json",)

# Hex identifiers are matched with lookarounds so a 64-hex sha256 cannot yield a
# 40-hex or 12-hex substring, and so a 40-hex sha cannot yield a 12-hex one.
HEX_40 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{40}(?![0-9a-fA-F])")
HEX_12 = re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{12}(?![0-9a-fA-F])")


class ImageError(Exception):
    """A refusal, with a code the CLI turns into a JSON error envelope."""

    def __init__(self, code: str, message: str, **detail: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail


@dataclass(frozen=True)
class Rule:
    """One line to rewrite, anchored on its shape and not on the old value.

    Anchoring on shape rather than on the template's literal sha is what makes
    ``run-stage.sh`` self-correcting. That file was copied from the root base and
    never parameterized, so its ``image=`` line named the root base's agent image
    inside *every* directory, including the one whose audit then executed it. A
    literal-value rule would have silently skipped the stale line it was written
    to replace.
    """

    path: str
    pattern: str
    value: str
    expected: int
    why: str

    def compiled(self) -> re.Pattern[str]:
        return re.compile(self.pattern, re.MULTILINE)


RULES: tuple[Rule, ...] = (
    Rule(
        "build-images.sh",
        r"^BASE_SHA=(?P<value>[0-9a-f]{40})$",
        "base",
        1,
        "The base this recipe builds; also the purebase build context path",
    ),
    Rule(
        "Dockerfile.baseline",
        r'^(?P<lead>\s*bench\.base-sha=")(?P<value>[0-9a-f]{40})(?P<tail>".*)$',
        "base",
        1,
        "Image provenance label, read back as a build-time assertion",
    ),
    Rule(
        "Dockerfile.baseline",
        r'^(?P<lead>\s*bench\.tree-sha=")(?P<value>[0-9a-f]{40})(?P<tail>".*)$',
        "tree",
        1,
        "Tree label; verify-inputs.py compares it to git rev-parse HEAD^{tree}",
    ),
    Rule(
        "Dockerfile.agent",
        r"^ARG BASELINE_IMAGE=scrapy-sdd-batch-baseline:(?P<value>[0-9a-f]{40})$",
        "base",
        1,
        "Default for the FROM of the agent stage",
    ),
    Rule(
        "Dockerfile.agent",
        r'^(?P<lead>\s*bench\.base-sha=")(?P<value>[0-9a-f]{40})(?P<tail>".*)$',
        "base",
        1,
        "Must equal the label record-deployment.py asserts against",
    ),
    Rule(
        "Dockerfile.agent",
        r'^(?P<lead>\s*bench\.tree-sha=")(?P<value>[0-9a-f]{40})(?P<tail>".*)$',
        "tree",
        1,
        "The same tree the baseline image carries",
    ),
    Rule(
        "run-stage.sh",
        r"^(?P<lead>image='scrapy-sdd-batch-agent:)(?P<value>[0-9a-f]{40})(?P<tail>'.*)$",
        "base",
        1,
        "The agent image an audited stage actually runs",
    ),
    Rule(
        "run-stage.sh",
        r'^(?P<lead>run_id=")(?P<value>[0-9a-f]{12})(?P<tail>-)',
        "base12",
        1,
        "Container name prefix; cosmetic, but it is a base identity too",
    ),
)

# The image audit runs a disposable pytest inside the baseline image. The target
# is frozen per base and its argv is embedded in the audit, which gold-check then
# hashes into every task's isolation-audit. A target that some pull request
# edits would make that permanent, per-base artifact depend on a candidate's
# gold -- so selection requires the path to be absent from every file any raw
# record ever touched, across all 354 of them rather than the 98 in inventory.
#
# Both candidates were checked against all 75 candidate bases: present in all 75,
# one distinct blob each, and named by zero raw records.
SMOKE_CANDIDATES: tuple[str, ...] = (
    "tests/test_toplevel.py::test_version",
    "tests/test_poet.py::test_callbacks",
)

SMOKE_PYTEST_FLAGS: tuple[str, ...] = ("-q", "-p", "no:cacheprovider", "--basetemp=/tmp/pytest-smoke")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_set_sha256(values: set[str] | frozenset[str]) -> str:
    """Hash a set of paths so the evidence is reproducible, not just asserted."""
    return sha256_bytes(("\n".join(sorted(values)) + "\n").encode())


def display_path(path: Path, repository_root: Path) -> str:
    """Report paths relative to the repository when they live inside it.

    The bench root is overridable, so a caller can point at a tree that is not
    under the repository this module was imported from.
    """
    try:
        return path.relative_to(repository_root).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_placeholders(base_sha: str, tree_sha: str) -> dict[str, str]:
    return {"base": base_sha, "tree": tree_sha, "base12": base_sha[:12]}


def read_tree_sha(bench: Path, base_sha: str) -> str:
    """Read the tree from the provisioned baseline lock; never accept it as input.

    ``verify-inputs.py`` compares this value against ``git rev-parse HEAD^{tree}``
    in the baseline cache. Taking it from a human would reintroduce exactly the
    transcription failure this generator exists to remove.
    """
    lock_path = bench / "batch/baselines" / base_sha / "baseline-lock.json"
    if not lock_path.is_file():
        raise ImageError(
            "BASELINE_NOT_PROVISIONED",
            "The baseline cache for this base is absent; run sdd-batch provision first",
            base_sha=base_sha,
            expected=lock_path.as_posix(),
        )
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("base_sha") != base_sha:
        raise ImageError(
            "BASELINE_LOCK_MISMATCH",
            "Baseline lock records a different base",
            recorded=lock.get("base_sha"),
            requested=base_sha,
        )
    tree_sha = lock.get("tree_sha")
    if not isinstance(tree_sha, str) or not HEX_40.fullmatch(tree_sha):
        raise ImageError("BASELINE_LOCK_MALFORMED", "Baseline lock has no tree sha", base_sha=base_sha)
    return tree_sha


def substitute(text: str, rule: Rule, replacement: str) -> str:
    """Replace only the captured value, leaving the rest of the line alone."""
    def replace(match: re.Match[str]) -> str:
        start, end = match.span("value")
        line = match.group(0)
        return line[: start - match.start()] + replacement + line[end - match.start() :]

    return rule.compiled().sub(replace, text)


def apply_rules(text: str, rules: tuple[Rule, ...], values: dict[str, str]) -> tuple[str, int]:
    """Rewrite every line the rules cover, and report how many matched.

    A rule whose pattern matches zero lines is a template that drifted -- the
    edit would silently not happen. A rule matching more lines than it declares
    is an ambiguous anchor. Both refuse.
    """
    matched = 0
    for rule in rules:
        hits = len(rule.compiled().findall(text))
        if hits != rule.expected:
            raise ImageError(
                "RULE_ANCHOR_MISMATCH",
                f"Rule for {rule.path} matched {hits} lines, expected {rule.expected}",
                path=rule.path,
                pattern=rule.pattern,
                expected=rule.expected,
                matched=hits,
                why=rule.why,
            )
        matched += hits
        text = substitute(text, rule, values[rule.value])
    return text, matched


def hex_tokens(text: str) -> tuple[set[str], set[str]]:
    return set(HEX_40.findall(text)), set(HEX_12.findall(text))


def check_shared_images(before: str, after: str) -> None:
    """Assert the cross-base images survived the rewrite untouched.

    This is the forward half of the check whose reverse half is
    :func:`check_no_foreign_hex`. Replacing one of these tags does not fail here
    -- it fails much later, inside ``build-images.sh``, as an image id mismatch
    with no mention of the recipe.
    """
    for constant in SHARED_IMAGES:
        original = before.count(constant)
        copied = after.count(constant)
        if original == 0:
            raise ImageError(
                "TEMPLATE_MISSING_SHARED_IMAGE",
                "Template does not carry a cross-base image this generator must preserve",
                constant=constant,
            )
        if copied != original:
            raise ImageError(
                "SHARED_IMAGE_REWRITTEN",
                "A cross-base image reference was rewritten; these are shared by every base",
                constant=constant,
                before=original,
                after=copied,
            )


def check_no_foreign_hex(text: str, values: dict[str, str]) -> None:
    """Assert no hex identifier other than the new base, tree, and shared set remains.

    This is what catches a stale base identity in a line the rule table does not
    cover -- including the ``run-stage.sh`` line that a literal-value rule would
    have missed, and any future line a recipe edit adds.
    """
    allowed_40 = {values["base"], values["tree"]}
    allowed_12 = {values["base12"]} | SHARED_HEX_12
    found_40, found_12 = hex_tokens(text)
    stray_40 = sorted(found_40 - allowed_40)
    stray_12 = sorted(found_12 - allowed_12)
    if stray_40 or stray_12:
        raise ImageError(
            "FOREIGN_HEX_IDENTIFIER",
            "The recipe carries a hex identifier that is neither this base nor a shared image",
            base_sha=values["base"],
            stray_40=stray_40,
            stray_12=stray_12,
        )


def select_smoke_target(bench: Path, repository_root: Path, base_sha: str) -> dict[str, Any]:
    """Pick a per-base smoke target that no pull request has ever touched."""
    raw_path = repository_root / RAW_RECORDS
    if not raw_path.is_file():
        raise ImageError("RAW_RECORDS_MISSING", "Raw pull request records are absent", path=raw_path.as_posix())
    records = [json.loads(line) for line in raw_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    touched: set[str] = set()
    for record in records:
        for change in record.get("changed_files") or []:
            if isinstance(change, dict) and isinstance(change.get("filename"), str):
                touched.add(change["filename"])
        for change in record.get("test_changes") or []:
            if isinstance(change, dict) and isinstance(change.get("file"), str):
                touched.add(change["file"])

    inventory_path = bench / INVENTORY
    if inventory_path.is_file():
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        for pull in inventory.get("pull_requests") or []:
            for change in pull.get("test_changes") or []:
                # The inventory spells this key differently from the raw record.
                if isinstance(change, dict) and isinstance(change.get("path"), str):
                    touched.add(change["path"])

    repository = bench / "batch/baselines" / base_sha / "repository"
    if not repository.is_dir():
        raise ImageError(
            "BASELINE_NOT_PROVISIONED",
            "The baseline repository for this base is absent",
            base_sha=base_sha,
        )

    failures: list[dict[str, str]] = []
    for rank, node_id in enumerate(SMOKE_CANDIDATES):
        path, _, _ = node_id.partition("::")
        if path in touched:
            failures.append({"node_id": node_id, "reason": "named by a raw pull request record"})
            continue
        blob = subprocess.run(
            ["git", "-C", str(repository), "show", f"{base_sha}:{path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if blob.returncode:
            failures.append({"node_id": node_id, "reason": "absent at this base"})
            continue
        body = blob.stdout
        if not re.search(rb"(?m)^def test_", body):
            failures.append({"node_id": node_id, "reason": "collects no module-level tests"})
            continue
        return {
            "schema_version": 1,
            "path": path,
            "node_id": node_id,
            "argv": ["python", "-m", "pytest", *SMOKE_PYTEST_FLAGS, node_id],
            "selected_rank": rank,
            "selection_rule": (
                "present at the base, named by no raw pull request record, and collects "
                "at least one module-level test"
            ),
            "gold_blindness": {
                "raw_record_count": len(records),
                "touched_file_count": len(touched),
                "touched_files_sha256": canonical_set_sha256(touched),
                "path_in_touched_files": False,
            },
            "base_evidence": {
                "present_at_base": True,
                "blob_sha256": sha256_bytes(body),
            },
            "rejected": failures,
        }

    raise ImageError(
        "SMOKE_TARGET_UNAVAILABLE",
        "No smoke target candidate is usable at this base",
        base_sha=base_sha,
        rejected=failures,
    )


def render_recipe(
    template: Path, values: dict[str, str], smoke: dict[str, Any]
) -> dict[str, str]:
    """Produce every file of a recipe directory, refusing before anything is written."""
    # Every required file is checked before any is read, so a template missing
    # one reports that rather than surfacing as a bare read error.
    required = sorted({rule.path for rule in RULES} | set(VERBATIM_FILES))
    for path in required:
        if not (template / path).is_file():
            raise ImageError("TEMPLATE_FILE_MISSING", "Template lacks a required file", path=path)

    # The baseline spans everything the product will contain, verbatim files
    # included, and each file is read once even when several rules target it:
    # counting a file once per rule, or omitting the verbatim copies, would make
    # the forward check compare two different file sets and pass on a rewrite it
    # was written to catch.
    before = "".join((template / path).read_text(encoding="utf-8") for path in required)

    per_file: dict[str, tuple[Rule, ...]] = {}
    for rule in RULES:
        per_file.setdefault(rule.path, ())
        per_file[rule.path] += (rule,)

    products: dict[str, str] = {}

    total = 0
    for path, rules in per_file.items():
        text, matched = apply_rules((template / path).read_text(encoding="utf-8"), rules, values)
        total += matched
        products[path] = text

    for name in VERBATIM_FILES:
        products[name] = (template / name).read_text(encoding="utf-8")

    for name in OPTIONAL_FILES:
        if name == "smoke-test.json":
            products[name] = json.dumps(smoke, indent=2, ensure_ascii=False) + "\n"

    after = "".join(products.values())
    check_shared_images(before, after)
    check_no_foreign_hex(after, values)
    for name in VERBATIM_FILES:
        if products[name] != (template / name).read_text(encoding="utf-8"):
            raise ImageError("VERBATIM_COPY_DAMAGED", "A verbatim file did not survive the copy", path=name)
    return products


def commit(products: dict[str, str], temporary: Path, target: Path) -> None:
    """Stage into a sibling directory, then move it into place atomically."""
    temporary.mkdir(parents=True)
    for name, content in sorted(products.items()):
        path = temporary / name
        path.write_text(content, encoding="utf-8")
        if name.endswith(".sh"):
            path.chmod(0o755)
    os.replace(temporary, target)


def create(
    bench: Path,
    repository_root: Path,
    base_sha: str,
    template_sha: str = DEFAULT_TEMPLATE_SHA,
) -> dict[str, Any]:
    if not HEX_40.fullmatch(base_sha):
        raise ImageError("BASE_SHA_INVALID", "base sha must be 40 lowercase hex digits", base_sha=base_sha)
    if base_sha == ROOT_BASE_SHA:
        raise ImageError(
            "ROOT_BASE_NOT_GENERATED",
            "The root base is the ancestor of every recipe, not an instance of one",
            base_sha=base_sha,
        )
    if base_sha == template_sha:
        raise ImageError("TEMPLATE_IS_TARGET", "Refusing to use the target as its own template", base_sha=base_sha)

    template = bench / "batch/images" / template_sha
    if not template.is_dir():
        raise ImageError("TEMPLATE_MISSING", "Template recipe directory is absent", path=template.as_posix())

    target = bench / "batch/images" / base_sha
    audit_path = bench / "batch/audits/images" / f"{base_sha}-image-audit.json"
    if audit_path.exists():
        raise ImageError(
            "IMAGE_AUDIT_EXISTS",
            "An image audit already exists for this base; it records a build this would replace",
            path=audit_path.as_posix(),
        )
    if target.exists():
        # An empty directory is residue from an interrupted create; real content
        # is a recipe that already exists.
        if target.is_dir() and not any(target.iterdir()):
            target.rmdir()
        else:
            raise ImageError(
                "IMAGE_DIR_EXISTS",
                "Refusing to overwrite an existing recipe directory",
                path=target.as_posix(),
            )

    tree_sha = read_tree_sha(bench, base_sha)
    values = resolve_placeholders(base_sha, tree_sha)
    smoke = select_smoke_target(bench, repository_root, base_sha)
    products = render_recipe(template, values, smoke)
    commit(products, bench / "batch/images" / f".{base_sha}.tmp", target)
    return {
        "base_sha": base_sha,
        "tree_sha": tree_sha,
        "template_sha": template_sha,
        "directory": display_path(target, repository_root),
        "files": sorted(products),
        "smoke_node_id": smoke["node_id"],
        "next": f"{display_path(target, repository_root)}/build-images.sh",
    }


def verify_directory(bench: Path, base_sha: str, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Re-derive every create-time check against a recipe on disk."""
    directory = bench / "batch/images" / base_sha
    if not directory.is_dir():
        raise ImageError("IMAGE_DIR_MISSING", "Recipe directory is absent", path=directory.as_posix())
    tree_sha = read_tree_sha(bench, base_sha)
    values = resolve_placeholders(base_sha, tree_sha)

    # Checked against the bytes on disk, never against a rewritten copy of them.
    # Substituting the rules first would normalize away exactly the defect this
    # looks for: a stale base identity in a rule-covered line is replaced by the
    # current base before the identifier scan ever sees it, so a recipe whose
    # run-stage.sh names some other base would report PASS.
    texts: dict[str, str] = {}
    for rule in RULES:
        path = directory / rule.path
        if not path.is_file():
            raise ImageError("RECIPE_FILE_MISSING", "Recipe lacks a file a rule needs", path=rule.path)
        texts.setdefault(rule.path, path.read_text(encoding="utf-8"))
    for rule in RULES:
        hits = len(rule.compiled().findall(texts[rule.path]))
        if hits != rule.expected:
            raise ImageError(
                "RULE_ANCHOR_MISMATCH",
                f"Rule for {rule.path} matched {hits} lines, expected {rule.expected}",
                path=rule.path,
                pattern=rule.pattern,
                expected=rule.expected,
                matched=hits,
                why=rule.why,
            )

    for name in VERBATIM_FILES:
        path = directory / name
        if not path.is_file():
            raise ImageError("RECIPE_FILE_MISSING", "Recipe lacks a required file", path=name)
        texts[name] = path.read_text(encoding="utf-8")

    # Optional: a recipe without it falls back to the adapter's smoke target,
    # which is how the directories frozen before this generator existed behave.
    # Whether a directory *should* carry one is a cross-directory question, and
    # verify_all answers it by comparing recipes after masking.
    smoke_path = directory / "smoke-test.json"
    if smoke_path.is_file():
        texts["smoke-test.json"] = smoke_path.read_text(encoding="utf-8")

    joined = "".join(texts.values())
    check_no_foreign_hex(joined, values)
    for constant in SHARED_IMAGES:
        if constant not in joined:
            raise ImageError(
                "SHARED_IMAGE_ABSENT",
                "Recipe does not carry a cross-base image reference",
                constant=constant,
            )
    return {
        "base_sha": base_sha,
        "tree_sha": tree_sha,
        "directory": display_path(directory, repository_root),
        "rule_count": len(RULES),
        "smoke_target_source": "image-dir" if smoke_path.is_file() else "adapter",
        "status": "PASS",
    }


def masked_recipe(directory: Path) -> dict[str, str]:
    """The recipe with every rule-covered value replaced by its placeholder.

    Two recipes for different bases must be equal after this, because that is
    the only way they are allowed to differ.
    """
    values = {"base": "<base>", "tree": "<tree>", "base12": "<base12>"}
    masked: dict[str, str] = {}
    for path in sorted({rule.path for rule in RULES}):
        text = (directory / path).read_text(encoding="utf-8")
        for rule in RULES:
            if rule.path == path:
                text = substitute(text, rule, values[rule.value])
        masked[path] = text
    for name in VERBATIM_FILES:
        masked[name] = (directory / name).read_text(encoding="utf-8")
    for name in OPTIONAL_FILES:
        # Carried for the smoke-target comparison below, not for the byte
        # comparison: a recipe built before the file existed has none, and its
        # absence is not a divergence.
        path = directory / name
        masked[name] = path.read_text(encoding="utf-8") if path.is_file() else ""
    return masked


def smoke_node_id(masked: dict[str, str]) -> str | None:
    name = OPTIONAL_FILES[0]
    if not masked.get(name):
        return None
    try:
        value = json.loads(masked[name]).get("node_id")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, str) else None


def verify_all(bench: Path, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    """Verify every generated recipe, and that they differ only where they may."""
    images = bench / "batch/images"
    directories = sorted(path for path in images.iterdir() if path.is_dir())
    generated = [path.name for path in directories if path.name != ROOT_BASE_SHA]
    if not generated:
        raise ImageError("NO_RECIPES", "No generated recipe directories found", path=images.as_posix())

    verified = [verify_directory(bench, name, repository_root) for name in sorted(generated)]

    current = sorted(set(generated) - HISTORICAL_RECIPE_BASES)
    reference_name = current[0] if current else sorted(generated)[0]
    reference = masked_recipe(images / reference_name)
    comparable = set(reference) - set(OPTIONAL_FILES)
    reference_smoke = smoke_node_id(reference)
    for name in sorted(generated):
        candidate = masked_recipe(images / name)
        if name in HISTORICAL_RECIPE_BASES:
            payload = {key: value for key, value in candidate.items() if key not in OPTIONAL_FILES}
            digest = sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            if digest != HISTORICAL_MASKED_RECIPE_SHA256:
                raise ImageError(
                    "RECIPES_DIVERGE", "Frozen historical recipe differs from its template",
                    reference="historical-template", other=name, differing=["historical-template-sha256"],
                )
        elif name != reference_name:
            differing = sorted(
                key
                for key in comparable | (set(candidate) - set(OPTIONAL_FILES))
                if reference.get(key) != candidate.get(key)
            )
            if differing == ["record-deployment.py"] and sha256_file(images / name / "record-deployment.py") == BASELINE_NATIVE_AUDIT_SHA256:
                differing = []
            if differing:
                raise ImageError(
                    "RECIPES_DIVERGE",
                    "Two recipes differ outside the lines the rule table covers",
                    reference=reference_name,
                    other=name,
                    differing=differing,
                )
        # The smoke target is frozen into a per-base artifact, so two recipes
        # agreeing on everything else while auditing against different tests is
        # a difference the byte comparison above deliberately does not see.
        candidate_smoke = smoke_node_id(candidate)
        if reference_smoke and candidate_smoke and reference_smoke != candidate_smoke:
            raise ImageError(
                "SMOKE_TARGET_DIVERGE",
                "Two recipes pin different smoke targets",
                reference=reference_name,
                other=name,
                reference_node_id=reference_smoke,
                other_node_id=candidate_smoke,
            )
    return {"status": "PASS", "verified": verified, "reference": reference_name, "root_skipped": ROOT_BASE_SHA}
