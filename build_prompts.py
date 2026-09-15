"""Build leak-free method-level prompt JSON from method-mined raw PR records."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from experiment.prompts import (
    METHOD_DEFAULT_PROMPT_FIELDS,
    build_method_dataset,
    build_method_prompts,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = ROOT / "output" / "raw_prs"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "prompt"


def load_raw_records(
    input_dir: Path, repos: set[str] | None = None
) -> tuple[list[Any], list[Path]]:
    paths = sorted(input_dir.glob("*.jsonl"))
    if not paths:
        raise FileNotFoundError(f"No raw PR JSONL files found in {input_dir}")

    records: list[Any] = []
    used_paths: list[Path] = []
    for path in paths:
        path_used = False
        with path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Invalid JSON in {path}:{line_number}: {exc}"
                    ) from exc
                if repos and data.get("repo") not in repos:
                    continue
                records.append(SimpleNamespace(**data))
                path_used = True
        if path_used:
            used_paths.append(path)
    return records, used_paths


def group_prompts_by_repo(
    dataset: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Group rendered prompts using the source dataset's repository field."""
    if len(dataset) != len(prompts):
        raise ValueError("Dataset and prompt counts do not match")

    grouped: dict[str, list[dict[str, Any]]] = {}
    for dataset_entry, prompt in zip(dataset, prompts, strict=True):
        repo = dataset_entry["repo"]
        grouped.setdefault(repo, []).append(prompt)
    return grouped


def prompt_file_name(repo: str) -> str:
    owner, separator, name = repo.partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ValueError(f"Expected repository as owner/repo, got: {repo}")
    return f"{owner}__{name}.json"


def write_prompt_collection(
    output_dir: Path,
    prompts_by_repo: dict[str, list[dict[str, Any]]],
    *,
    source_paths: list[Path],
    raw_count: int,
    kept_pr_count: int,
    mining_status_counts: dict[str, int] | None = None,
    unpromptable_pr_count: int = 0,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous_files: set[str] = set()
    if manifest_path.exists():
        previous_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        previous_files.update((previous_manifest.get("prompt_files") or {}).values())
        if previous_manifest.get("prompts_file"):
            previous_files.add(previous_manifest["prompts_file"])

    prompt_files: dict[str, str] = {}
    for repo, prompts in sorted(prompts_by_repo.items()):
        file_name = prompt_file_name(repo)
        (output_dir / file_name).write_text(
            json.dumps(prompts, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        prompt_files[repo] = file_name

    for stale_file in previous_files - set(prompt_files.values()):
        (output_dir / stale_file).unlink(missing_ok=True)

    prompt_counts = {
        repo: len(prompts) for repo, prompts in sorted(prompts_by_repo.items())
    }
    prompt_type_counts = {"focal_guided": 0, "test_only": 0}
    for prompts in prompts_by_repo.values():
        for prompt in prompts:
            prompt_type = prompt.get("prompt_type")
            if prompt_type in prompt_type_counts:
                prompt_type_counts[prompt_type] += 1
    manifest = {
        "schema_version": 3,
        "mode": "method",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [str(path) for path in source_paths],
        "raw_pr_count": raw_count,
        "raw_mining_status_counts": mining_status_counts or {},
        "unpromptable_pr_count": unpromptable_pr_count,
        "kept_pr_count": kept_pr_count,
        "prompt_count": sum(prompt_counts.values()),
        "prompt_type_counts": prompt_type_counts,
        "keep_fields": list(METHOD_DEFAULT_PROMPT_FIELDS),
        "prompt_files": prompt_files,
        "prompt_counts": prompt_counts,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return prompt_files


def build_prompt_outputs(
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    repos: set[str] | None = None,
) -> dict[str, Any]:
    """Build the fixed method-prompt collection and return output counts."""
    records, source_paths = load_raw_records(input_dir, repos=repos)
    if not records:
        requested = ", ".join(sorted(repos or set()))
        raise RuntimeError(f"No raw PR records matched: {requested}")


    dataset = build_method_dataset(records)
    mining_status_counts = dict(
        sorted(Counter(getattr(record, "mining_status", "not_mined") for record in records).items())
    )
    prompts = build_method_prompts(dataset)
    prompt_type_counts = {
        "focal_guided": sum(item["prompt_type"] == "focal_guided" for item in prompts),
        "test_only": sum(item["prompt_type"] == "test_only" for item in prompts),
    }
    kept_pr_count = len({(item["repo"], item["pr_id"]) for item in dataset})
    contributing_prs = {(item["repo"], item["pr_id"]) for item in dataset}
    eligible_prs = {
        (record.repo, record.pr_id)
        for record in records
        if getattr(record, "merged", False)
        and getattr(record, "ci_status", "unknown") == "success"
    }
    unpromptable_pr_count = len(eligible_prs - contributing_prs)
    prompts_by_repo = group_prompts_by_repo(dataset, prompts)
    prompt_files = write_prompt_collection(
        output_dir,
        prompts_by_repo,
        source_paths=source_paths,
        raw_count=len(records),
        kept_pr_count=kept_pr_count,
        mining_status_counts=mining_status_counts,
        unpromptable_pr_count=unpromptable_pr_count,
    )
    return {
        "raw_count": len(records),
        "kept_pr_count": kept_pr_count,
        "prompt_count": len(prompts),
        "raw_mining_status_counts": mining_status_counts,
        "unpromptable_pr_count": unpromptable_pr_count,
        "prompt_type_counts": prompt_type_counts,
        "keep_fields": METHOD_DEFAULT_PROMPT_FIELDS,
        "prompt_files": prompt_files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build leak-free method prompts from method-mined raw PR records"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--repo",
        action="append",
        help="Only include this owner/repo; repeat to include multiple repositories",
    )
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print the fixed method-prompt fields and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_fields:
        print("\n".join(METHOD_DEFAULT_PROMPT_FIELDS))
        return

    result = build_prompt_outputs(
        args.input_dir,
        args.output_dir,
        repos=set(args.repo) if args.repo else None,
    )
    print(
        f"Built {result['prompt_count']} prompt(s) from {result['raw_count']} raw PR(s); "
        f"{result['kept_pr_count']} PR(s) contributed method prompt(s)."
    )
    print(
        "Prompt types: "
        f"focal_guided={result['prompt_type_counts']['focal_guided']}, "
        f"test_only={result['prompt_type_counts']['test_only']}"
    )
    print(
        "Raw mining statuses: "
        + ", ".join(
            f"{status}={count}"
            for status, count in result["raw_mining_status_counts"].items()
        )
        + f"; unpromptable={result['unpromptable_pr_count']}"
    )
    print(f"Fields: {', '.join(result['keep_fields'])}")
    for repo, file_name in sorted(result["prompt_files"].items()):
        print(f"Output [{repo}]: {args.output_dir / file_name}")


if __name__ == "__main__":
    main()
