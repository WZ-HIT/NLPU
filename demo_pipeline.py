"""Turn collected PRs into a dataset of (code change, natural-language) pairs.

This module consumes the records produced by the ``collector`` package and
runs a short pipeline to build a dataset ready for LLM test-case generation:

1. Filter PRs     - three-dimension hard filter (merge, code, NL quality)
2. Build dataset  - extract Python diffs, align NL descriptions, annotate
3. Quality check  - report empty/sample statistics
4. Export         - write dataset.jsonl, prompts.jsonl, quality_report.json

Each dataset sample pairs a code fragment (``diff_hunks``) with its natural
language description so a downstream LLM can generate test cases from it.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from collector import PullRequestRecord, collect_prs

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"


# ---------------------------------------------------------------------------
# NL quality thresholds (kept from the empirical analysis)
# ---------------------------------------------------------------------------
# Derived from 800 merged PRs across pandas/requests/django/sklearn:
# - title   >= 4  matches the 25th percentile.
# - body    >= 14 is mu - sigma on the log-normal fit of body_words.
# - commits >= 6  is mu - sigma on commits_words (an alternative when body is short).
_MIN_TITLE_WORDS = 4
_MIN_BODY_WORDS = 14
_MIN_COMMITS_WORDS = 6


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def is_code_file(filename: str) -> bool:
    return filename.endswith(".py")


def is_doc_file(filename: str) -> bool:
    lowered = filename.lower()
    return lowered.endswith(".md") or lowered.startswith("docs/") or "/docs/" in lowered


# Stricter than ``"test" in filename`` to avoid false matches on ``best.py``.
_TEST_PATH_RE = re.compile(r"(^|/)tests?/", re.IGNORECASE)
_TEST_FILENAME_RE = re.compile(r"(^|/)test_[^/]+\.py$|(^|/)[^/]+_test\.py$", re.IGNORECASE)


def is_test_file(filename: str) -> bool:
    return bool(_TEST_PATH_RE.search(filename) or _TEST_FILENAME_RE.search(filename))


# ---------------------------------------------------------------------------
# Text cleaning
# ---------------------------------------------------------------------------

_CHECKLIST_RE = re.compile(r"- \[[ xX]\].*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_BOILERPLATE_RE = re.compile(
    r"^\s*(lgtm|looks good to me|ship it|approved|nit[:\s]|no comments?\.?)\s*$",
    re.IGNORECASE,
)


def clean_text(text: str) -> str:
    text = _CHECKLIST_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = text.replace("###", " ")
    return _WHITESPACE_RE.sub(" ", text).strip()


def is_substantive(text: str) -> bool:
    """True when ``text`` carries real information (>= 8 words, not boilerplate)."""
    stripped = text.strip()
    return bool(stripped) and len(stripped.split()) >= 8 and not _BOILERPLATE_RE.match(stripped)


# ---------------------------------------------------------------------------
# Diff helpers
# ---------------------------------------------------------------------------


def split_patch_into_hunks(patch: str) -> list[str]:
    if not patch:
        return []
    hunks: list[str] = []
    current: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@") and current:
            hunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append("\n".join(current))
    return hunks


# ---------------------------------------------------------------------------
# Stage 1 - Filter (hard filter, three dimensions)
# ---------------------------------------------------------------------------


def filter_pr(pr: PullRequestRecord) -> tuple[bool, list[str]]:
    """Return ``(passed, reasons)``.

    A PR is kept only when all three dimensions pass:

    1. merge_quality  - merged AND CI green.
    2. code_presence  - at least one Python file changed, not docs-only.
    3. nl_quality     - title >= 4 AND (body >= 14 OR commits >= 6).
    """
    reasons: list[str] = []
    passes = 0

    if pr.merged and pr.ci_status == "success":
        reasons.append("+merge_quality: merged and CI green")
        passes += 1
    elif pr.merged:
        reasons.append(f"-merge_quality: merged but CI not green (ci_status={pr.ci_status})")
    else:
        reasons.append("-merge_quality: PR was not merged")

    code_files = [f for f in pr.changed_files if is_code_file(f["filename"])]
    all_docs = pr.changed_files and all(is_doc_file(f["filename"]) for f in pr.changed_files)
    if code_files and not all_docs:
        reasons.append(f"+code_presence: {len(code_files)} Python file(s) changed")
        passes += 1
    else:
        reasons.append("-code_presence: no Python source files changed (docs-only or empty)")

    title_words = len(pr.title.split())
    body_words = len(clean_text(pr.body).split())
    commits_words = sum(len(clean_text(m).split()) for m in pr.commit_messages)
    if title_words >= _MIN_TITLE_WORDS and (
        body_words >= _MIN_BODY_WORDS or commits_words >= _MIN_COMMITS_WORDS
    ):
        reasons.append(
            f"+nl_quality: title={title_words} words, body={body_words} words, "
            f"commits={commits_words} words"
        )
        passes += 1
    else:
        reasons.append(
            f"-nl_quality: insufficient description "
            f"(title={title_words}, body={body_words}, commits={commits_words})"
        )

    return passes == 3, reasons


def filter_prs(prs: list[PullRequestRecord]) -> list[tuple[PullRequestRecord, list[str]]]:
    """Keep only PRs that pass all three dimensions; return (record, reasons)."""
    kept: list[tuple[PullRequestRecord, list[str]]] = []
    for pr in prs:
        passed, reasons = filter_pr(pr)
        if passed:
            kept.append((pr, reasons))
    return kept


# ---------------------------------------------------------------------------
# Stage 2 - Build dataset (extract + align + annotate, one pass)
# ---------------------------------------------------------------------------


def extract_fragments(pr: PullRequestRecord) -> list[dict[str, Any]]:
    """Return one fragment per changed Python file (filename + diff hunks)."""
    return [
        {
            "filename": file["filename"],
            "hunks": split_patch_into_hunks(file.get("patch", "")),
        }
        for file in pr.changed_files
        if is_code_file(file["filename"])
    ]


def build_description(pr: PullRequestRecord) -> dict[str, str]:
    """Clean and align the PR's natural-language sources into one description."""
    title = clean_text(pr.title)
    body = clean_text(pr.body)
    comments = " | ".join(
        clean_text(c) for c in pr.comments + pr.review_comments if is_substantive(c)
    )
    commits = " | ".join(clean_text(m) for m in pr.commit_messages if is_substantive(m))
    description = f"{title}. {body}".strip(". ").strip()
    return {
        "nl_title": title,
        "nl_body": body,
        "nl_comments": comments,
        "nl_commits": commits,
        "nl_description": description,
        "nl_description_extended": " ".join(p for p in (description, commits, comments) if p),
    }


def annotate_pr(pr: PullRequestRecord) -> dict[str, Any]:
    """Soft quality signals attached to every kept PR (no filtering)."""
    return {
        "has_test_changes": any(is_test_file(f["filename"]) for f in pr.changed_files),
        "closes_issue_count": len(pr.closing_issue_refs),
        "title_words": len(pr.title.split()),
        "body_words": len(clean_text(pr.body).split()),
        "commits_words": sum(len(clean_text(m).split()) for m in pr.commit_messages),
    }


def build_dataset(
    kept: list[tuple[PullRequestRecord, list[str]]],
) -> list[dict[str, Any]]:
    """Combine each PR's fragments, description and annotations into samples."""
    dataset: list[dict[str, Any]] = []
    for pr, reasons in kept:
        description = build_description(pr)
        annotations = annotate_pr(pr)
        for fragment in extract_fragments(pr):
            dataset.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "filename": fragment["filename"],
                    "fragment_type": "file",
                    "filter_reasons": reasons,
                    "annotations": annotations,
                    "diff_hunks": fragment["hunks"],
                    **description,
                }
            )
    return dataset


# ---------------------------------------------------------------------------
# Stage 3 - Test-case prompt
# ---------------------------------------------------------------------------

TEST_CASE_PROMPT_TEMPLATE = """\
You are an expert Python test engineer.

Given the code change (unified diff) and its natural-language description below,
write runnable pytest test cases that verify the change.

Repository: {repo}
Changed file: {filename}

Natural-language description:
{description}

Code change (unified diff):
{diff}

Write the test cases now. Return only Python code, no explanation.
"""


def build_test_case_prompt(entry: dict[str, Any]) -> str:
    """Map one dataset sample to a prompt an LLM can turn into test cases."""
    return TEST_CASE_PROMPT_TEMPLATE.format(
        repo=entry["repo"],
        filename=entry["filename"],
        description=entry["nl_description_extended"] or entry["nl_description"] or "(no description)",
        diff="\n".join(entry["diff_hunks"]) or "(no diff)",
    )


def build_prompts(dataset: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return one prompt per dataset sample, with metadata for traceability."""
    return [
        {
            "repo": entry["repo"],
            "pr_id": entry["pr_id"],
            "filename": entry["filename"],
            "prompt": build_test_case_prompt(entry),
        }
        for entry in dataset
    ]


# ---------------------------------------------------------------------------
# Stage 4 - Quality check + export
# ---------------------------------------------------------------------------


def quality_check(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sample_count": len(dataset),
        "unique_sample_count": len({(e["repo"], e["pr_id"], e["filename"]) for e in dataset}),
        "with_test_changes": sum(1 for e in dataset if e["annotations"]["has_test_changes"]),
        "with_closing_issues": sum(1 for e in dataset if e["annotations"]["closes_issue_count"] > 0),
        "empty_text_count": sum(1 for e in dataset if not e["nl_description"]),
        "empty_extended_text_count": sum(1 for e in dataset if not e["nl_description_extended"]),
        "empty_hunks_count": sum(1 for e in dataset if not e["diff_hunks"]),
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_outputs(
    dataset: list[dict[str, Any]],
    prompts: list[dict[str, Any]],
    report: dict[str, Any],
    output_dir: Path = OUTPUT_DIR,
) -> None:
    output_dir.mkdir(exist_ok=True)
    write_jsonl(output_dir / "dataset.jsonl", dataset)
    write_jsonl(output_dir / "prompts.jsonl", prompts)
    (output_dir / "quality_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a test-case dataset from GitHub PRs")
    parser.add_argument("--owner", required=True, help="GitHub repo owner")
    parser.add_argument("--repo", required=True, help="GitHub repo name")
    parser.add_argument("--limit", type=int, default=10, help="Max merged PRs to collect (default: 10)")
    parser.add_argument("--state", choices=["closed", "all"], default="closed", help="PR state to query")
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Output directory (default: output/)")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip already-collected PRs (default: True)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(f"[1/5] Collecting merged PRs from {args.owner}/{args.repo} (limit={args.limit})")
    prs = collect_prs(
        owner=args.owner,
        repo=args.repo,
        limit=args.limit,
        state=args.state,
        output_dir=args.output_dir,
        resume=args.resume,
    )

    kept = filter_prs(prs)
    print(f"[2/5] Filtered to {len(kept)} valid PRs (out of {len(prs)})")

    dataset = build_dataset(kept)
    print(f"[3/5] Built dataset with {len(dataset)} samples")

    prompts = build_prompts(dataset)

    report = quality_check(dataset)
    print(f"[4/5] Quality check: {report['sample_count']} samples, "
          f"{report['empty_hunks_count']} empty hunks")

    write_outputs(dataset, prompts, report, args.output_dir)
    print("[5/5] Wrote dataset.jsonl, prompts.jsonl, quality_report.json")


if __name__ == "__main__":
    main()
