"""Build leak-free test-case prompts from enriched raw PR records."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any, Iterable

from demo_pipeline import build_description

FOCAL_GUIDED_PROMPT_TEMPLATE = """\
You are an expert Python test engineer.

Update the old pytest test case so that it verifies the observable behavior of
the post-PR focal method. Preserve useful setup and project conventions.
Do not modify production code. Return only the updated Python test code.

Repository: {repo}

Natural-language change description:
{description}

Focal file: {focal_file}
Focal method: {focal_qualified_name}

Post-PR focal method:
{focal_method_after}

Old test file: {old_test_file}
Old test: {old_test_qualified_name}

Old test code:
{old_test}
"""

TEST_ONLY_PROMPT_TEMPLATE = """\
You are an expert Python test engineer.

Update the old pytest test case according to the natural-language change
description. No focal method was selected reliably for this sample. Preserve
useful setup and project conventions. Do not modify production code. Return
only the updated Python test code.

Repository: {repo}

Natural-language change description:
{description}

Old test file: {old_test_file}
Old test: {old_test_qualified_name}

Old test code:
{old_test}
"""

METHOD_DEFAULT_PROMPT_FIELDS = (
    "repo",
    "pr_id",
    "sample_id",
    "prompt_type",
    "focal_available",
    "focal_file",
    "focal_qualified_name",
    "focal_method_after",
    "old_test_file",
    "old_test_qualified_name",
    "old_test",
    "pair_confidence",
    "pair_evidence",
    "mining_status",
    "mining_reasons",
    "nl_description",
    "nl_description_extended",
    "prompt",
)

_FORBIDDEN_KEYS = {
    "gold_test",
    "gold_patch",
    "focal_method_before",
    "before_source",
    "test_diff",
}


def _as_mapping(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    if isinstance(record, SimpleNamespace):
        return vars(record)
    return vars(record)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(_FORBIDDEN_KEYS.intersection(value)) or any(
            _contains_forbidden_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    return False


def _test_key(test_change: dict[str, Any]) -> str:
    return test_change.get("node_id") or (
        f"{test_change.get('file', '')}::{test_change.get('qualified_name', '')}"
    )


def _test_only_sample_id(
    repo: str, pr_id: int, test_change: dict[str, Any]
) -> str:
    identity = f"{repo}#{pr_id}#{_test_key(test_change)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{repo.replace('/', '__')}__{pr_id}__test_only__{digest}"


def _dataset_entry(
    record: dict[str, Any],
    test_change: dict[str, Any],
    description: dict[str, str],
    *,
    pair: dict[str, Any] | None,
    focal: dict[str, Any] | None,
) -> dict[str, Any]:
    focal_available = focal is not None
    return {
        "repo": record["repo"],
        "pr_id": record["pr_id"],
        "sample_id": (
            pair["sample_id"]
            if pair is not None
            else _test_only_sample_id(record["repo"], record["pr_id"], test_change)
        ),
        "prompt_type": "focal_guided" if focal_available else "test_only",
        "focal_available": focal_available,
        "focal_file": focal["file"] if focal_available else None,
        "focal_qualified_name": (
            focal["qualified_name"] if focal_available else None
        ),
        "focal_method_after": focal["after_source"] if focal_available else None,
        "old_test_file": test_change["file"],
        "old_test_qualified_name": test_change["qualified_name"],
        "old_test": test_change["old_test"],
        "pair_confidence": (
            pair.get("pair_confidence", "unavailable")
            if pair is not None
            else "unavailable"
        ),
        "pair_evidence": pair.get("pair_evidence", []) if pair is not None else [],
        "mining_status": record.get("mining_status", "not_mined"),
        "mining_reasons": list(record.get("mining_reasons") or []),
        **description,
    }


def build_method_dataset(records: Iterable[Any]) -> list[dict[str, Any]]:
    """Build one sample per extracted modified test, with focal context when reliable."""
    dataset: list[dict[str, Any]] = []
    for raw_record in records:
        record = _as_mapping(raw_record)
        if not record.get("merged") or record.get("ci_status") != "success":
            continue

        description = build_description(SimpleNamespace(**record))
        seen_tests: set[str] = set()

        for pair in record.get("method_test_pairs", []):
            test_change = pair["test_change"]
            if test_change.get("change_type") != "modified":
                continue
            test_key = _test_key(test_change)
            if test_key in seen_tests:
                continue
            seen_tests.add(test_key)

            focal = (
                pair.get("focal_method")
                if pair.get("eligibility") == "accepted"
                else None
            )
            entry = _dataset_entry(
                record,
                test_change,
                description,
                pair=pair,
                focal=focal,
            )
            if _contains_forbidden_key(entry):
                raise ValueError(
                    f"Forbidden gold field leaked into sample {entry['sample_id']}"
                )
            dataset.append(entry)

        for test_change in record.get("test_changes", []):
            if test_change.get("change_type") != "modified":
                continue
            test_key = _test_key(test_change)
            if test_key in seen_tests:
                continue
            seen_tests.add(test_key)
            entry = _dataset_entry(
                record,
                test_change,
                description,
                pair=None,
                focal=None,
            )
            if _contains_forbidden_key(entry):
                raise ValueError(
                    f"Forbidden gold field leaked into sample {entry['sample_id']}"
                )
            dataset.append(entry)
    return dataset


def build_method_prompt(entry: dict[str, Any]) -> str:
    description = (
        entry["nl_description_extended"]
        or entry["nl_description"]
        or "(no description)"
    )
    template = (
        FOCAL_GUIDED_PROMPT_TEMPLATE
        if entry["focal_available"]
        else TEST_ONLY_PROMPT_TEMPLATE
    )
    return template.format(**entry, description=description)


def build_method_prompts(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Render the fixed, leak-free prompt schema."""
    prompts: list[dict[str, Any]] = []
    for entry in dataset:
        complete = {**entry, "prompt": build_method_prompt(entry)}
        rendered = {
            field: complete[field] for field in METHOD_DEFAULT_PROMPT_FIELDS
        }
        if _contains_forbidden_key(rendered):
            raise ValueError(
                f"Forbidden gold field leaked into prompt {entry['sample_id']}"
            )
        prompts.append(rendered)
    return prompts
