"""PR runnable filtering demo — downstream pipeline.

Collection now lives in the ``collector`` package. This module consumes the
JSONL it produces and applies the three-dimension hard filter, code-fragment
extraction, NL description alignment, dataset building and quality checks.
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


def is_code_file(filename: str) -> bool:
    return filename.endswith(".py")


def is_doc_file(filename: str) -> bool:
    lowered = filename.lower()
    return lowered.endswith(".md") or lowered.startswith("docs/") or "/docs/" in lowered


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


def extract_runnable_parts(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fragments: list[dict[str, Any]] = []
    for item in kept:
        pr: PullRequestRecord = item["record"]
        for file in pr.changed_files:
            if not is_code_file(file["filename"]):
                continue
            hunks = split_patch_into_hunks(file.get("patch", ""))
            fragments.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "filename": file["filename"],
                    "fragment_type": "file",
                    "hunks": hunks,
                    "added_lines": file.get("additions", 0),
                    "deleted_lines": file.get("deletions", 0),
                }
            )
    print(f"[3/5] Extracted {len(fragments)} runnable code fragments")
    return fragments


CHECKLIST_RE = re.compile(r"- \[[ xX]\].*$", re.MULTILINE)
URL_RE = re.compile(r"https?://\S+")
WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    cleaned = CHECKLIST_RE.sub("", text)
    cleaned = URL_RE.sub("", cleaned)
    cleaned = cleaned.replace("###", " ")
    cleaned = WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned


_BOILERPLATE_RE = re.compile(
    r"^\s*(lgtm|looks good to me|ship it|approved|nit[:\s]|no comments?\.?)\s*$",
    re.IGNORECASE,
)


def _is_substantive(text: str) -> bool:
    """Return True when text carries genuine information (≥ 8 words, not pure boilerplate)."""
    stripped = text.strip()
    if not stripped or len(stripped.split()) < 8:
        return False
    return not _BOILERPLATE_RE.match(stripped)


# Stricter test-file detection than `"test" in filename` to avoid false matches
# on names like ``best.py`` or ``latest.py``.
_TEST_PATH_RE = re.compile(r"(^|/)tests?/", re.IGNORECASE)
_TEST_FILENAME_RE = re.compile(r"(^|/)test_[^/]+\.py$|(^|/)[^/]+_test\.py$", re.IGNORECASE)


def _is_test_file(filename: str) -> bool:
    return bool(_TEST_PATH_RE.search(filename) or _TEST_FILENAME_RE.search(filename))


def align_descriptions(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aligned: list[dict[str, Any]] = []
    for item in kept:
        pr: PullRequestRecord = item["record"]
        cleaned_title = clean_text(pr.title)
        cleaned_body = clean_text(pr.body)

        # Aggregate substantive comments and commit messages as supplementary NL context
        substantive_comments = [
            clean_text(c) for c in pr.comments + pr.review_comments if _is_substantive(c)
        ]
        substantive_commits = [
            clean_text(m) for m in pr.commit_messages if _is_substantive(m)
        ]

        nl_comments = " | ".join(substantive_comments)
        nl_commits = " | ".join(substantive_commits)

        # Primary description: title + body; extended description adds discussion context
        cleaned_description = f"{cleaned_title}. {cleaned_body}".strip(". ").strip()
        extended_description = " ".join(
            part for part in [cleaned_description, nl_commits, nl_comments] if part
        )

        aligned.append(
            {
                "repo": pr.repo,
                "pr_id": pr.pr_id,
                "nl_title": cleaned_title,
                "nl_body": cleaned_body,
                "nl_comments": nl_comments,
                "nl_commits": nl_commits,
                "nl_description": cleaned_description,
                "nl_description_extended": extended_description,
            }
        )
    print(f"[4/5] Cleaned and aligned {len(aligned)} natural language descriptions")
    return aligned


# ---------------------------------------------------------------------------
# Layer A — hard filter (3 dimensions)
# Layer B — annotations (soft signals, no filtering)
# ---------------------------------------------------------------------------
# to do: 判断是否相关不需过滤，应重新考虑
# to do： 判断相关需重新考虑新方法

# Word-count thresholds derived empirically from 800 merged PRs across
# pandas/requests/django/sklearn (see NL_THRESHOLD_ANALYSIS.md):
# - title >= 4  matches the 25th percentile.
# - body  >= 14 is mu - sigma on the log-normal fit of body_words.
# - commits >= 6 is mu - sigma on commits_words (an alternative when body is short).
_MIN_TITLE_WORDS = 4
_MIN_BODY_WORDS = 14
_MIN_COMMITS_WORDS = 6


def filter_pr(pr: PullRequestRecord) -> tuple[bool, list[str]]:
    """Three-dimension hard filter for NL↔code dataset construction.

    A PR is kept only when *all three* dimensions pass:

    1. **merge_quality**  — merged AND CI green.
    2. **code_presence**  — at least one Python file changed AND not all-docs.
    3. **nl_quality**     — title >= _MIN_TITLE_WORDS AND
                            (body >= _MIN_BODY_WORDS OR commits >= _MIN_COMMITS_WORDS).

    Returns ``(passed, reasons)``. ``reasons`` lists every check that was run,
    prefixed with ``+`` (pass) or ``-`` (fail) for easy debugging.
    """
    reasons: list[str] = []
    passes = 0

    # --- 1. merge_quality ---
    if pr.merged and pr.ci_status == "success":
        reasons.append("+merge_quality: merged and CI green")
        passes += 1
    elif pr.merged:
        reasons.append(f"-merge_quality: merged but CI not green (ci_status={pr.ci_status})")
    else:
        reasons.append("-merge_quality: PR was not merged")

    # --- 2. code_presence ---
    code_files = [f for f in pr.changed_files if is_code_file(f["filename"])]
    all_docs = pr.changed_files and all(is_doc_file(f["filename"]) for f in pr.changed_files)
    if code_files and not all_docs:
        reasons.append(f"+code_presence: {len(code_files)} Python file(s) changed")
        passes += 1
    else:
        reasons.append("-code_presence: no Python source files changed (docs-only or empty)")

    # --- 3. nl_quality ---
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


def filter_prs(prs: list[PullRequestRecord]) -> list[dict[str, Any]]:
    """Apply Layer A to every PR; only keep those that pass all three dimensions."""
    kept: list[dict[str, Any]] = []
    for pr in prs:
        passed, reasons = filter_pr(pr)
        if passed:
            kept.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "filter_reasons": reasons,
                    "record": pr,
                }
            )
    print(f"[2/5] Filtered to {len(kept)} valid PRs (out of {len(prs)})")
    return kept


def annotate_pr(pr: PullRequestRecord) -> dict[str, Any]:
    """Layer B — soft quality signals attached to every kept PR.

    Pure annotation, no filtering. Downstream consumers can sub-select samples
    using these fields without re-running the pipeline.
    """
    title_words = len(pr.title.split())
    body_words = len(clean_text(pr.body).split())
    commits_words = sum(len(clean_text(m).split()) for m in pr.commit_messages)
    return {
        "has_test_changes": any(_is_test_file(f["filename"]) for f in pr.changed_files),
        "closes_issue_count": len(pr.closing_issue_refs),
        "title_words": title_words,
        "body_words": body_words,
        "commits_words": commits_words,
    }


def build_dataset(
    kept: list[dict[str, Any]],
    fragments: list[dict[str, Any]],
    descriptions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    description_index = {(item["repo"], item["pr_id"]): item for item in descriptions}
    kept_index = {(item["repo"], item["pr_id"]): item for item in kept}
    annotation_index = {
        (item["repo"], item["pr_id"]): annotate_pr(item["record"]) for item in kept
    }

    dataset: list[dict[str, Any]] = []
    for fragment in fragments:
        key = (fragment["repo"], fragment["pr_id"])
        description = description_index[key]
        kept_item = kept_index[key]
        dataset.append(
            {
                "repo": fragment["repo"],
                "pr_id": fragment["pr_id"],
                "filename": fragment["filename"],
                "fragment_type": fragment["fragment_type"],
                "filter_reasons": kept_item["filter_reasons"],
                "annotations": annotation_index[key],
                "diff_hunks": fragment["hunks"],
                "nl_title": description["nl_title"],
                "nl_body": description["nl_body"],
                "nl_comments": description["nl_comments"],
                "nl_commits": description["nl_commits"],
                "nl_description": description["nl_description"],
                "nl_description_extended": description["nl_description_extended"],
            }
        )
    print(f"[5/5] Built dataset with {len(dataset)} final samples")
    return dataset


def quality_check(dataset: list[dict[str, Any]]) -> dict[str, Any]:
    empty_text = sum(1 for item in dataset if not item["nl_description"])
    empty_extended = sum(1 for item in dataset if not item["nl_description_extended"])
    empty_hunks = sum(1 for item in dataset if not item["diff_hunks"])
    unique_keys = {(item["repo"], item["pr_id"], item["filename"]) for item in dataset}
    with_test = sum(1 for item in dataset if item["annotations"]["has_test_changes"])
    with_closing = sum(1 for item in dataset if item["annotations"]["closes_issue_count"] > 0)

    return {
        "sample_count": len(dataset),
        "unique_sample_count": len(unique_keys),
        "with_test_changes": with_test,
        "with_closing_issues": with_closing,
        "empty_text_count": empty_text,
        "empty_extended_text_count": empty_extended,
        "empty_hunks_count": empty_hunks,
    }


def write_outputs(
    dataset: list[dict[str, Any]], report: dict[str, Any], output_dir: Path = OUTPUT_DIR
) -> None:
    output_dir.mkdir(exist_ok=True)

    jsonl_path = output_dir / "dataset.jsonl"
    report_path = output_dir / "quality_report.json"

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in dataset:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Wrote dataset to {jsonl_path}")
    print(f"Wrote quality report to {report_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demo pipeline for PR filtering and NL description extraction"
    )
    parser.add_argument("--owner", required=True, help="GitHub repo owner")
    parser.add_argument("--repo", required=True, help="GitHub repo name")
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of merged PRs to collect (default: 10)",
    )
    parser.add_argument(
        "--state",
        choices=["closed", "all"],
        default="closed",
        help="PR state to query from GitHub before filtering merged PRs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for outputs (default: output/)",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip PRs already collected (default: True)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    print(
        f"[1/5] Collecting merged PRs from {args.owner}/{args.repo} "
        f"(limit={args.limit})"
    )
    prs = collect_prs(
        owner=args.owner,
        repo=args.repo,
        limit=args.limit,
        state=args.state,
        output_dir=args.output_dir,
        resume=args.resume,
    )

    kept = filter_prs(prs)
    fragments = extract_runnable_parts(kept)
    descriptions = align_descriptions(kept)
    dataset = build_dataset(kept, fragments, descriptions)
    report = quality_check(dataset)
    write_outputs(dataset, report, args.output_dir)


if __name__ == "__main__":
    main()
