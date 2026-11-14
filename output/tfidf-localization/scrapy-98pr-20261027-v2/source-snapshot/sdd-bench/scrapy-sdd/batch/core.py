"""Build PR inventories and non-executable provision plans.

This module reads dataset artifacts and writes only inventory/plan documents. It
does not invoke Git, Docker, an SDD tool, or an Agent.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

SCHEMA_VERSION = 1
REPOSITORY = "scrapy/scrapy"
CLASSIFICATIONS = {
    "TEST_ONLY_PR",
    "MIXED_CODE_AND_TEST_PR",
    "NO_TEST_CHANGE",
    "INVALID_INPUT",
}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SAMPLE_PREFIX_RE = re.compile(r"^(?P<owner>[^_]+)__(?P<repo>[^_]+)__(?P<pr>[0-9]+)__")
FORBIDDEN_PLAN_KEYS = {
    "gold_test",
    "gold_patch",
    "old_test",
    "raw_patch",
    "patch",
    "head_sha",
    "head_source",
    "merge_commit_sha",
    "merge_source",
    "focal_method_after",
}


class BatchError(Exception):
    """Structured user-facing batch error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class InputPaths:
    prompt: Path
    raw: Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def display_path(path: Path, repository_root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(repository_root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _atomic_write(path: Path, data: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_json(path: Path, value: Any, *, refuse_overwrite: bool = False) -> None:
    if refuse_overwrite and path.exists():
        raise BatchError(
            "PLAN_ALREADY_EXISTS",
            "Refusing to overwrite an existing provision plan",
            path=str(path),
        )
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _safe_repository_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and "//" not in value


def _is_test_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return bool(parts) and parts[0] in {"test", "tests", "testing"}


def _test_key(change: dict[str, Any]) -> str:
    node_id = change.get("node_id")
    if isinstance(node_id, str) and node_id:
        return node_id
    return f"{change.get('file', '')}::{change.get('qualified_name', '')}"


def _test_only_sample_id(repo: str, pr_id: int, change: dict[str, Any]) -> str:
    identity = f"{repo}#{pr_id}#{_test_key(change)}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    return f"{repo.replace('/', '__')}__{pr_id}__test_only__{digest}"


def _minimal_sample(
    sample_id: str,
    prompt_type: str,
    file: Any,
    qualified_name: Any,
    source: str,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "prompt_type": prompt_type,
        "test_file": file if isinstance(file, str) else None,
        "test_qualified_name": (
            qualified_name if isinstance(qualified_name, str) else None
        ),
        "available_sources": [source],
    }


def raw_member_samples(record: dict[str, Any]) -> list[dict[str, Any]]:
    repo = record.get("repo")
    pr_id = record.get("pr_id")
    if not isinstance(repo, str) or not isinstance(pr_id, int):
        return []
    samples: list[dict[str, Any]] = []
    seen_tests: set[str] = set()
    for pair in record.get("method_test_pairs") or []:
        if not isinstance(pair, dict) or not isinstance(pair.get("test_change"), dict):
            continue
        change = pair["test_change"]
        if change.get("change_type") != "modified":
            continue
        key = _test_key(change)
        if key in seen_tests:
            continue
        seen_tests.add(key)
        sample_id = pair.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            sample_id = _test_only_sample_id(repo, pr_id, change)
        prompt_type = (
            "focal_guided"
            if pair.get("eligibility") == "accepted"
            else "test_only"
        )
        samples.append(
            _minimal_sample(
                sample_id,
                prompt_type,
                change.get("file"),
                change.get("qualified_name"),
                "raw",
            )
        )
    for change in record.get("test_changes") or []:
        if not isinstance(change, dict) or change.get("change_type") != "modified":
            continue
        key = _test_key(change)
        if key in seen_tests:
            continue
        seen_tests.add(key)
        samples.append(
            _minimal_sample(
                _test_only_sample_id(repo, pr_id, change),
                "test_only",
                change.get("file"),
                change.get("qualified_name"),
                "raw",
            )
        )
    return samples


def load_prompt(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [], [
            {
                "code": "INVALID_PROMPT_INPUT",
                "message": str(exc),
                "location": str(path),
            }
        ]
    if not isinstance(value, list):
        return [], [
            {
                "code": "INVALID_PROMPT_INPUT",
                "message": "Prompt input must be a JSON array",
                "location": str(path),
            }
        ]
    records: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            errors.append(
                {
                    "code": "INVALID_PROMPT_RECORD",
                    "message": "Prompt record must be an object",
                    "location": f"{path}[{index}]",
                }
            )
            continue
        records.append(item)
    return records, errors


def load_raw(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [
            {
                "code": "INVALID_RAW_INPUT",
                "message": str(exc),
                "location": str(path),
            }
        ]
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(
                {
                    "code": "INVALID_RAW_RECORD",
                    "message": str(exc),
                    "location": f"{path}:{line_number}",
                }
            )
            continue
        if not isinstance(item, dict):
            errors.append(
                {
                    "code": "INVALID_RAW_RECORD",
                    "message": "Raw record must be an object",
                    "location": f"{path}:{line_number}",
                }
            )
            continue
        item = dict(item)
        item["_line_number"] = line_number
        records.append(item)
    return records, errors


def _nl_quality(raw_records: list[dict[str, Any]], prompt_records: list[dict[str, Any]]) -> dict[str, Any]:
    title = next(
        (r.get("title", "").strip() for r in raw_records if isinstance(r.get("title"), str) and r.get("title", "").strip()),
        "",
    )
    body = next(
        (r.get("body", "").strip() for r in raw_records if isinstance(r.get("body"), str) and r.get("body", "").strip()),
        "",
    )
    prompt_description = next(
        (
            r.get("nl_description", "").strip()
            for r in prompt_records
            if isinstance(r.get("nl_description"), str)
            and r.get("nl_description", "").strip()
        ),
        "",
    )
    description = prompt_description or " ".join(part for part in (title, body) if part)
    words = description.split()
    if not description:
        status = "MISSING"
    elif len(words) < 5:
        status = "WEAK"
    else:
        status = "GOOD"
    return {
        "status": status,
        "word_count": len(words),
        "has_title": bool(title),
        "has_body": bool(body),
        "description": description,
    }


def _classification(
    raw_records: list[dict[str, Any]], issues: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    local_issues = list(issues)
    if len(raw_records) != 1:
        local_issues.append(
            {
                "code": "RAW_PR_CARDINALITY",
                "message": f"Expected exactly one raw PR record, found {len(raw_records)}",
            }
        )
        return "INVALID_INPUT", local_issues
    raw = raw_records[0]
    if not SHA_RE.fullmatch(str(raw.get("base_sha", ""))):
        local_issues.append(
            {"code": "INVALID_BASE_SHA", "message": "base_sha must be 40 lowercase hex characters"}
        )
    changed_files = raw.get("changed_files")
    if not isinstance(changed_files, list):
        local_issues.append(
            {"code": "INVALID_CHANGED_FILES", "message": "changed_files must be an array"}
        )
    else:
        for index, change in enumerate(changed_files):
            filename = change.get("filename") if isinstance(change, dict) else None
            if not _safe_repository_path(filename):
                local_issues.append(
                    {
                        "code": "INVALID_CHANGED_PATH",
                        "message": "Changed filename is not a safe repository-relative path",
                        "index": index,
                    }
                )
    if local_issues:
        return "INVALID_INPUT", local_issues
    filenames = [change["filename"] for change in changed_files]
    test_count = sum(_is_test_path(path) for path in filenames)
    if not test_count:
        return "NO_TEST_CHANGE", local_issues
    if test_count == len(filenames):
        return "TEST_ONLY_PR", local_issues
    return "MIXED_CODE_AND_TEST_PR", local_issues


def _minimal_changed_files(raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(raw_records) != 1 or not isinstance(raw_records[0].get("changed_files"), list):
        return []
    result = []
    for change in raw_records[0]["changed_files"]:
        if not isinstance(change, dict) or not isinstance(change.get("filename"), str):
            continue
        result.append(
            {
                "path": change["filename"],
                "status": change.get("status"),
                "additions": change.get("additions"),
                "deletions": change.get("deletions"),
                "changes": change.get("changes"),
                "is_test": _is_test_path(change["filename"]),
            }
        )
    return sorted(result, key=lambda item: item["path"])


def _minimal_test_changes(raw_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(raw_records) != 1 or not isinstance(raw_records[0].get("test_changes"), list):
        return []
    result = []
    for change in raw_records[0]["test_changes"]:
        if not isinstance(change, dict):
            continue
        result.append(
            {
                "path": change.get("file"),
                "qualified_name": change.get("qualified_name"),
                "change_type": change.get("change_type"),
            }
        )
    return sorted(
        result,
        key=lambda item: (str(item["path"]), str(item["qualified_name"])),
    )


def _merge_samples(
    raw_records: list[dict[str, Any]], prompt_records: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the prompt-defined sample set enriched with raw availability.

    Prompt samples are the benchmark candidate universe. Raw test changes may
    confirm and enrich those samples, but must never introduce another task or
    sample into inventory.
    """
    by_id: dict[str, dict[str, Any]] = {}
    issues: list[dict[str, Any]] = []
    prompt_candidates = []
    for prompt in prompt_records:
        sample_id = prompt.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            issues.append(
                {"code": "INVALID_SAMPLE_ID", "message": "Prompt record has no valid sample_id"}
            )
            continue
        prompt_candidates.append(
            _minimal_sample(
                sample_id,
                str(prompt.get("prompt_type") or "unknown"),
                prompt.get("old_test_file"),
                prompt.get("old_test_qualified_name"),
                "prompt",
            )
        )
    counts = Counter(sample["sample_id"] for sample in prompt_candidates)
    for sample_id, count in counts.items():
        if count > 1:
            issues.append(
                {
                    "code": "DUPLICATE_PROMPT_SAMPLE_ID",
                    "message": "sample_id occurs more than once in prompt input",
                    "sample_id": sample_id,
                    "count": count,
                }
            )
    for sample in prompt_candidates:
        sample_id = sample["sample_id"]
        existing = by_id.get(sample_id)
        if existing is None:
            by_id[sample_id] = sample
            continue
    raw_candidates = []
    for raw in raw_records:
        raw_candidates.extend(raw_member_samples(raw))
    for sample in raw_candidates:
        sample_id = sample["sample_id"]
        existing = by_id.get(sample_id)
        if existing is None:
            continue
        existing["available_sources"] = sorted(
            set(existing["available_sources"]) | set(sample["available_sources"])
        )
        for key in ("test_file", "test_qualified_name"):
            if existing.get(key) is None:
                existing[key] = sample.get(key)
            elif sample.get(key) not in {None, existing.get(key)}:
                issues.append(
                    {
                        "code": "SAMPLE_METADATA_CONFLICT",
                        "message": f"Conflicting {key} for sample",
                        "sample_id": sample_id,
                    }
                )
    return sorted(by_id.values(), key=lambda item: item["sample_id"]), issues


def build_inventory(
    inputs: InputPaths, repository_root: Path
) -> tuple[dict[str, Any], dict[str, dict[Any, list[tuple[str, int]]]]]:
    prompt_records, prompt_errors = load_prompt(inputs.prompt)
    raw_records, raw_errors = load_raw(inputs.raw)
    grouped_raw: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    grouped_prompt: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    for record in raw_records:
        grouped_raw[(record.get("repo"), record.get("pr_id"))].append(record)
    for record in prompt_records:
        grouped_prompt[(record.get("repo"), record.get("pr_id"))].append(record)

    # The leak-free prompt collection is the canonical 1,245-sample candidate
    # universe. Raw-only PRs are metadata records, not benchmark tasks.
    keys = sorted(
        set(grouped_prompt),
        key=lambda key: (str(key[0]), str(key[1])),
    )
    prs: list[dict[str, Any]] = []
    prompt_sample_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    raw_sample_index: dict[str, list[tuple[str, int]]] = defaultdict(list)
    prompt_pr_index: dict[int, list[tuple[str, int]]] = defaultdict(list)
    raw_pr_index: dict[int, list[tuple[str, int]]] = defaultdict(list)

    for repo, pr_id in keys:
        raw_group = grouped_raw[(repo, pr_id)]
        prompt_group = grouped_prompt[(repo, pr_id)]
        issues: list[dict[str, Any]] = []
        if not isinstance(repo, str) or "/" not in repo:
            issues.append({"code": "INVALID_REPOSITORY", "message": "repo must be owner/name"})
        if not isinstance(pr_id, int) or isinstance(pr_id, bool) or pr_id < 1:
            issues.append({"code": "INVALID_PR_ID", "message": "pr_id must be a positive integer"})
        samples, sample_issues = _merge_samples(raw_group, prompt_group)
        issues.extend(sample_issues)
        classification, issues = _classification(raw_group, issues)
        base_shas = sorted(
            {
                raw.get("base_sha")
                for raw in raw_group
                if isinstance(raw.get("base_sha"), str)
            }
        )
        base_sha = base_shas[0] if len(base_shas) == 1 else None
        if len(base_shas) > 1:
            classification = "INVALID_INPUT"
            issues.append(
                {
                    "code": "CONFLICTING_BASE_SHA",
                    "message": "Raw PR records disagree on base_sha",
                }
            )
        task_categories = dict(
            sorted(Counter(sample["prompt_type"] for sample in samples).items())
        )
        entry = {
            "repository": repo,
            "pr_id": pr_id,
            "classification": classification,
            "recorded_base_sha": base_sha,
            "member_sample_count": len(samples),
            "member_samples": samples,
            "test_change_count": len(_minimal_test_changes(raw_group)),
            "test_changes": _minimal_test_changes(raw_group),
            "changed_file_count": len(_minimal_changed_files(raw_group)),
            "changed_files": _minimal_changed_files(raw_group),
            "nl_quality": _nl_quality(raw_group, prompt_group),
            "task_categories": task_categories,
            "input_issues": issues,
        }
        prs.append(entry)
        if isinstance(repo, str) and isinstance(pr_id, int):
            if prompt_group:
                prompt_pr_index[pr_id].append((repo, pr_id))
            if raw_group:
                raw_pr_index[pr_id].append((repo, pr_id))
            for sample in samples:
                pair = (repo, pr_id)
                if "prompt" in sample["available_sources"]:
                    prompt_sample_index[sample["sample_id"]].append(pair)
                if "raw" in sample["available_sources"]:
                    raw_sample_index[sample["sample_id"]].append(pair)

    input_records = {
        "prompt": {
            "path": display_path(inputs.prompt, repository_root),
            "sha256": sha256_file(inputs.prompt),
            "size_bytes": inputs.prompt.stat().st_size,
            "record_count": len(prompt_records),
        },
        "raw": {
            "path": display_path(inputs.raw, repository_root),
            "sha256": sha256_file(inputs.raw),
            "size_bytes": inputs.raw.stat().st_size,
            "record_count": len(raw_records),
        },
    }
    input_set_sha = canonical_sha256(
        {name: data["sha256"] for name, data in sorted(input_records.items())}
    )
    inventory = {
        "schema_version": SCHEMA_VERSION,
        "inventory_id": f"scrapy-pr-inventory-{input_set_sha[:16]}",
        "repository_scope": REPOSITORY,
        "inputs": input_records,
        "input_set_sha256": input_set_sha,
        "summary": {
            "pr_count": len(prs),
            "sample_count": sum(pr["member_sample_count"] for pr in prs),
            "aggregation": "prompt samples grouped by repository and pr_id",
            "classification_counts": dict(
                sorted(Counter(pr["classification"] for pr in prs).items())
            ),
            "invalid_record_count": len(prompt_errors) + len(raw_errors),
        },
        "invalid_records": prompt_errors + raw_errors,
        "pull_requests": prs,
    }
    indices = {
        "prompt_pr": dict(prompt_pr_index),
        "raw_pr": dict(raw_pr_index),
        "prompt_sample": dict(prompt_sample_index),
        "raw_sample": dict(raw_sample_index),
    }
    return inventory, indices


def inventory_tsv(inventory: dict[str, Any]) -> str:
    output = io.StringIO(newline="")
    columns = [
        "repository",
        "pr_id",
        "classification",
        "recorded_base_sha",
        "member_sample_count",
        "test_change_count",
        "changed_file_count",
        "nl_quality",
        "nl_word_count",
        "task_categories",
        "member_sample_ids",
        "changed_files",
        "input_issue_codes",
    ]
    writer = csv.DictWriter(output, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for pr in inventory["pull_requests"]:
        writer.writerow(
            {
                "repository": pr["repository"],
                "pr_id": pr["pr_id"],
                "classification": pr["classification"],
                "recorded_base_sha": pr["recorded_base_sha"] or "",
                "member_sample_count": pr["member_sample_count"],
                "test_change_count": pr["test_change_count"],
                "changed_file_count": pr["changed_file_count"],
                "nl_quality": pr["nl_quality"]["status"],
                "nl_word_count": pr["nl_quality"]["word_count"],
                "task_categories": ",".join(
                    f"{key}:{value}" for key, value in pr["task_categories"].items()
                ),
                "member_sample_ids": ",".join(
                    sample["sample_id"] for sample in pr["member_samples"]
                ),
                "changed_files": ",".join(
                    item["path"] for item in pr["changed_files"]
                ),
                "input_issue_codes": ",".join(
                    issue["code"] for issue in pr["input_issues"]
                ),
            }
        )
    return output.getvalue()


def write_inventory(
    inventory: dict[str, Any], json_path: Path, tsv_path: Path
) -> None:
    write_json(json_path, inventory)
    _atomic_write(tsv_path, inventory_tsv(inventory))


def read_pr_id_files(paths: Iterable[Path]) -> tuple[list[int], list[dict[str, Any]], list[dict[str, Any]]]:
    values: list[int] = []
    records: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(
                {
                    "code": "INVALID_PR_ID_FILE",
                    "message": str(exc),
                    "path": str(path),
                }
            )
            continue
        file_values = []
        for line_number, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if not line.isascii() or not line.isdigit() or int(line) < 1:
                errors.append(
                    {
                        "code": "INVALID_PR_ID_FILE_ENTRY",
                        "message": "Expected one positive decimal PR ID per line",
                        "path": str(path),
                        "line": line_number,
                        "value": line,
                    }
                )
                continue
            value = int(line)
            values.append(value)
            file_values.append(value)
        records.append(
            {"path": str(path), "sha256": sha256_file(path), "pr_ids": file_values}
        )
    return values, records, errors


def _selection_error(code: str, message: str, **details: Any) -> dict[str, Any]:
    result = {"code": code, "message": message}
    if details:
        result["details"] = details
    return result


def resolve_selection(
    inventory: dict[str, Any],
    indices: dict[str, dict[Any, list[tuple[str, int]]]],
    *,
    source: str,
    pr_ids: list[int],
    sample_ids: list[str],
    repository: str = REPOSITORY,
) -> tuple[list[tuple[str, int]], list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    if not pr_ids and not sample_ids:
        return [], [], [
            _selection_error(
                "NO_EXPLICIT_SELECTION",
                "At least one --pr-id, --pr-id-file entry, or --sample-id is required",
            )
        ]
    pr_index = indices[f"{source}_pr"]
    sample_index = indices[f"{source}_sample"]
    for pr_id, count in Counter(pr_ids).items():
        if count > 1:
            errors.append(
                _selection_error(
                    "DUPLICATE_PR_SELECTION",
                    "PR ID was selected more than once",
                    pr_id=pr_id,
                    count=count,
                )
            )
    for sample_id, count in Counter(sample_ids).items():
        if count > 1:
            errors.append(
                _selection_error(
                    "DUPLICATE_SAMPLE_SELECTION",
                    "Sample ID was selected more than once",
                    sample_id=sample_id,
                    count=count,
                )
            )

    resolved: list[tuple[str, int]] = []
    for pr_id in pr_ids:
        matches = sorted(set(pr_index.get(pr_id, [])))
        if not matches:
            errors.append(
                _selection_error(
                    "PR_NOT_FOUND_IN_SOURCE",
                    "PR ID was not found in the selected source",
                    pr_id=pr_id,
                    source=source,
                )
            )
            continue
        repositories = sorted({match[0] for match in matches})
        if len(repositories) > 1:
            errors.append(
                _selection_error(
                    "AMBIGUOUS_PR_ID",
                    "PR ID occurs in more than one repository",
                    pr_id=pr_id,
                    repositories=repositories,
                )
            )
            continue
        if repositories[0] != repository:
            errors.append(
                _selection_error(
                    "CROSS_REPOSITORY_SELECTION",
                    "Selected PR belongs to a different repository",
                    pr_id=pr_id,
                    repository=repositories[0],
                    expected_repository=repository,
                )
            )
            continue
        resolved.append(matches[0])
        events.append(
            {"selector": "pr_id", "value": pr_id, "resolved_repository": matches[0][0], "resolved_pr_id": matches[0][1]}
        )

    for sample_id in sample_ids:
        matches = sorted(set(sample_index.get(sample_id, [])))
        if not matches:
            prefix = SAMPLE_PREFIX_RE.match(sample_id)
            if prefix and f"{prefix.group('owner')}/{prefix.group('repo')}" != repository:
                errors.append(
                    _selection_error(
                        "CROSS_REPOSITORY_SELECTION",
                        "Sample ID names a different repository",
                        sample_id=sample_id,
                        expected_repository=repository,
                    )
                )
            else:
                errors.append(
                    _selection_error(
                        "SAMPLE_NOT_FOUND_IN_SOURCE",
                        "Sample ID was not found in the selected source",
                        sample_id=sample_id,
                        source=source,
                    )
                )
            continue
        if len(matches) != 1:
            errors.append(
                _selection_error(
                    "AMBIGUOUS_SAMPLE_ID",
                    "Sample ID does not resolve uniquely",
                    sample_id=sample_id,
                    matches=[{"repository": repo, "pr_id": pr} for repo, pr in matches],
                )
            )
            continue
        repo, pr_id = matches[0]
        if repo != repository:
            errors.append(
                _selection_error(
                    "CROSS_REPOSITORY_SELECTION",
                    "Selected sample belongs to a different repository",
                    sample_id=sample_id,
                    repository=repo,
                    expected_repository=repository,
                )
            )
            continue
        resolved.append(matches[0])
        events.append(
            {"selector": "sample_id", "value": sample_id, "resolved_repository": repo, "resolved_pr_id": pr_id}
        )

    for pair, count in Counter(resolved).items():
        if count > 1:
            errors.append(
                _selection_error(
                    "DUPLICATE_PR_SELECTION",
                    "Multiple selectors resolve to the same PR-level task",
                    repository=pair[0],
                    pr_id=pair[1],
                    count=count,
                )
            )
    return sorted(set(resolved)), events, errors


def _contains_forbidden_plan_key(value: Any) -> bool:
    if isinstance(value, dict):
        return bool(FORBIDDEN_PLAN_KEYS.intersection(value)) or any(
            _contains_forbidden_plan_key(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_plan_key(item) for item in value)
    return False


def create_plan(
    *,
    plan_id: str,
    inventory: dict[str, Any],
    inventory_path: Path,
    source: str,
    requested_pr_ids: list[int],
    pr_id_files: list[dict[str, Any]],
    requested_sample_ids: list[str],
    resolved: list[tuple[str, int]],
    resolution_events: list[dict[str, Any]],
    repository_root: Path,
) -> dict[str, Any]:
    if not ID_RE.fullmatch(plan_id):
        raise BatchError(
            "INVALID_PLAN_ID",
            "plan-id must contain only lowercase letters, digits, dot, underscore, or hyphen",
            plan_id=plan_id,
        )
    by_key = {
        (pr["repository"], pr["pr_id"]): pr for pr in inventory["pull_requests"]
    }
    tasks = []
    for key in resolved:
        pr = by_key[key]
        tasks.append(
            {
                "task_id": f"{key[0].replace('/', '__')}__pr{key[1]}",
                "repository": key[0],
                "pr_id": key[1],
                "baseline": {"base_sha": pr["recorded_base_sha"]},
                "classification": pr["classification"],
                "member_sample_ids": [
                    sample["sample_id"] for sample in pr["member_samples"]
                ],
                "member_sample_count": pr["member_sample_count"],
                "test_change_count": pr["test_change_count"],
                "changed_files": [item["path"] for item in pr["changed_files"]],
                "nl_quality": pr["nl_quality"],
                "task_categories": pr["task_categories"],
            }
        )
    requested = {
        "pr_ids": requested_pr_ids,
        "pr_id_files": pr_id_files,
        "sample_ids": requested_sample_ids,
    }
    selection_result = {
        "source": source,
        "requested": requested,
        "resolution_events": resolution_events,
        "resolved_prs": [
            {"repository": repo, "pr_id": pr_id} for repo, pr_id in resolved
        ],
    }
    selection_result["sha256"] = canonical_sha256(selection_result)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "plan_type": "PROVISION_PLAN",
        "created_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "AWAITING_USER_APPROVAL",
        "executable": False,
        "repository_scope": REPOSITORY,
        "inputs": inventory["inputs"],
        "input_set_sha256": inventory["input_set_sha256"],
        "inventory": {
            "path": display_path(inventory_path, repository_root),
            "sha256": sha256_file(inventory_path),
            "inventory_id": inventory["inventory_id"],
        },
        "selection": selection_result,
        "task_scope": "one task per selected PR; sample IDs only resolve PR membership",
        "tasks": tasks,
        "approval": {
            "required": True,
            "granted": False,
            "provisioning_performed": False,
        },
    }
    if _contains_forbidden_plan_key(plan):
        raise BatchError(
            "FORBIDDEN_PLAN_CONTENT",
            "Provision plan contains an evaluation-only or source-body field",
        )
    return plan


def validate_plan_inputs(plan: dict[str, Any], repository_root: Path) -> dict[str, Any]:
    errors: list[dict[str, Any]] = []
    if plan.get("schema_version") != SCHEMA_VERSION:
        errors.append(
            _selection_error(
                "UNKNOWN_SCHEMA_VERSION",
                "Only provision plan schema_version 1 is supported",
                found=plan.get("schema_version"),
            )
        )
    inputs = plan.get("inputs")
    if not isinstance(inputs, dict) or set(inputs) != {"prompt", "raw"}:
        errors.append(
            _selection_error(
                "INVALID_PLAN_INPUTS", "Plan must pin exactly prompt and raw inputs"
            )
        )
    else:
        current: dict[str, str] = {}
        for name in ("prompt", "raw"):
            record = inputs.get(name)
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                errors.append(
                    _selection_error(
                        "INVALID_PLAN_INPUT", "Input record is malformed", input=name
                    )
                )
                continue
            path = Path(record["path"])
            if not path.is_absolute():
                path = repository_root / path
            try:
                actual = sha256_file(path)
            except OSError as exc:
                errors.append(
                    _selection_error(
                        "INPUT_UNAVAILABLE", str(exc), input=name, path=str(path)
                    )
                )
                continue
            current[name] = actual
            if actual != record.get("sha256"):
                errors.append(
                    _selection_error(
                        "INPUT_HASH_MISMATCH",
                        "Input changed after the provision plan was generated",
                        input=name,
                        expected=record.get("sha256"),
                        actual=actual,
                    )
                )
        if len(current) == 2:
            current_set = canonical_sha256(
                {name: current[name] for name in sorted(current)}
            )
            if current_set != plan.get("input_set_sha256"):
                errors.append(
                    _selection_error(
                        "INPUT_SET_HASH_MISMATCH",
                        "Current prompt/raw fingerprint differs from the plan",
                        expected=plan.get("input_set_sha256"),
                        actual=current_set,
                    )
                )
    inventory_record = plan.get("inventory")
    if not isinstance(inventory_record, dict) or not isinstance(
        inventory_record.get("path"), str
    ):
        errors.append(
            _selection_error(
                "INVALID_INVENTORY_REFERENCE",
                "Plan inventory reference is malformed",
            )
        )
    else:
        inventory_path = Path(inventory_record["path"])
        if not inventory_path.is_absolute():
            inventory_path = repository_root / inventory_path
        try:
            actual_inventory_sha = sha256_file(inventory_path)
        except OSError as exc:
            errors.append(
                _selection_error(
                    "INVENTORY_UNAVAILABLE", str(exc), path=str(inventory_path)
                )
            )
        else:
            if actual_inventory_sha != inventory_record.get("sha256"):
                errors.append(
                    _selection_error(
                        "INVENTORY_HASH_MISMATCH",
                        "Inventory changed after the provision plan was generated",
                        expected=inventory_record.get("sha256"),
                        actual=actual_inventory_sha,
                    )
                )
    selection_files = (
        plan.get("selection", {}).get("requested", {}).get("pr_id_files", [])
        if isinstance(plan.get("selection"), dict)
        else []
    )
    if not isinstance(selection_files, list):
        errors.append(
            _selection_error(
                "INVALID_SELECTION_FILES",
                "selection.requested.pr_id_files must be an array",
            )
        )
    else:
        for record in selection_files:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                errors.append(
                    _selection_error(
                        "INVALID_SELECTION_FILE",
                        "PR-ID selection file record is malformed",
                    )
                )
                continue
            selection_path = Path(record["path"])
            if not selection_path.is_absolute():
                selection_path = repository_root / selection_path
            try:
                actual_selection_sha = sha256_file(selection_path)
            except OSError as exc:
                errors.append(
                    _selection_error(
                        "SELECTION_FILE_UNAVAILABLE",
                        str(exc),
                        path=str(selection_path),
                    )
                )
                continue
            if actual_selection_sha != record.get("sha256"):
                errors.append(
                    _selection_error(
                        "SELECTION_FILE_HASH_MISMATCH",
                        "PR-ID selection file changed after plan generation",
                        path=str(selection_path),
                        expected=record.get("sha256"),
                        actual=actual_selection_sha,
                    )
                )
    return {
        "schema_version": SCHEMA_VERSION,
        "command": "validate-plan",
        "status": "VALID" if not errors else "INVALID",
        "valid": not errors,
        "plan_id": plan.get("plan_id"),
        "errors": errors,
    }
