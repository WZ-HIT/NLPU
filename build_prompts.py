"""Build configurable prompt JSON from already-collected raw PR records."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from demo_pipeline import (
    DEFAULT_PROMPT_FIELDS,
    PROMPT_FIELDS,
    build_dataset,
    build_prompts,
    filter_prs,
)

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT_DIR = ROOT / "output" / "raw_prs"
DEFAULT_OUTPUT_DIR = ROOT / "output" / "prompt"


def parse_keep_fields(value: str) -> tuple[str, ...]:
    fields = tuple(field.strip() for field in value.split(",") if field.strip())
    if not fields:
        raise argparse.ArgumentTypeError("keep-fields cannot be empty")
    if len(fields) != len(set(fields)):
        raise argparse.ArgumentTypeError("keep-fields cannot contain duplicates")
    unknown = set(fields) - set(PROMPT_FIELDS)
    if unknown:
        choices = ", ".join(PROMPT_FIELDS)
        raise argparse.ArgumentTypeError(
            f"unknown field(s): {', '.join(sorted(unknown))}; choices: {choices}"
        )
    return fields


def load_raw_records(input_dir: Path, repos: set[str] | None = None) -> tuple[list[Any], list[Path]]:
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
                    raise ValueError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
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
    keep_fields: tuple[str, ...],
    source_paths: list[Path],
    raw_count: int,
    kept_pr_count: int,
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
        repo: len(prompts)
        for repo, prompts in sorted(prompts_by_repo.items())
    }
    manifest = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_files": [str(path) for path in source_paths],
        "raw_pr_count": raw_count,
        "kept_pr_count": kept_pr_count,
        "prompt_count": sum(prompt_counts.values()),
        "keep_fields": list(keep_fields),
        "prompt_files": prompt_files,
        "prompt_counts": prompt_counts,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return prompt_files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build prompt JSON from existing output/raw_prs records"
    )
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--repo",
        action="append",
        help="Only include this owner/repo; repeat to include multiple repositories",
    )
    parser.add_argument(
        "--keep-fields",
        type=parse_keep_fields,
        default=DEFAULT_PROMPT_FIELDS,
        metavar="FIELD,...",
        help="Comma-separated fields retained in each prompt entry",
    )
    parser.add_argument(
        "--list-fields",
        action="store_true",
        help="Print available fields and exit",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.list_fields:
        print("\n".join(PROMPT_FIELDS))
        return

    records, source_paths = load_raw_records(
        args.input_dir,
        repos=set(args.repo) if args.repo else None,
    )
    if not records:
        requested = ", ".join(args.repo or [])
        raise RuntimeError(f"No raw PR records matched: {requested}")

    kept = filter_prs(records)
    dataset = build_dataset(kept)
    prompts = build_prompts(dataset, keep_fields=args.keep_fields)
    prompts_by_repo = group_prompts_by_repo(dataset, prompts)
    prompt_files = write_prompt_collection(
        args.output_dir,
        prompts_by_repo,
        keep_fields=args.keep_fields,
        source_paths=source_paths,
        raw_count=len(records),
        kept_pr_count=len(kept),
    )
    print(
        f"Built {len(prompts)} prompt(s) from {len(records)} raw PR(s); "
        f"{len(kept)} PR(s) passed the existing thresholds."
    )
    print(f"Fields: {', '.join(args.keep_fields)}")
    for repo, file_name in sorted(prompt_files.items()):
        print(f"Output [{repo}]: {args.output_dir / file_name}")


if __name__ == "__main__":
    main()
