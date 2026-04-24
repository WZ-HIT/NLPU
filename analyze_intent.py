from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"

MODEL = "claude-haiku-4-5-20251001"
INPUT_FILE = OUTPUT_DIR / "dataset.jsonl"
OUTPUT_FILE = OUTPUT_DIR / "intent_analysis.jsonl"
MAX_DIFF_CHARS = 8000
MAX_RETRIES = 4

VALID_CATEGORIES = frozenset(
    ["bug_fix", "feature_add", "refactor", "performance",
     "test", "docs", "security", "dependency_update"]
)

SYSTEM_PROMPT = """\
You are an expert software engineer specializing in code review and PR analysis.
Analyze git pull request changes and determine the intent behind the code modifications.

Always respond with ONLY a JSON object with exactly these three fields:
- "intent_category": one of ["bug_fix", "feature_add", "refactor", "performance", \
"test", "docs", "security", "dependency_update"]
- "intent_summary": 1-2 sentences describing the specific intent of this change
- "intent_confidence": one of ["high", "medium", "low"]

Classification guidance:
- bug_fix: corrects incorrect behavior, fixes crashes or runtime errors
- feature_add: introduces new functionality or capabilities
- refactor: restructures code without changing external behavior
- performance: improves speed, memory usage, or resource efficiency
- test: adds or modifies test coverage
- docs: updates documentation, docstrings, or comments only
- security: addresses security vulnerabilities or improves security posture
- dependency_update: updates library versions or changes external dependencies

Respond ONLY with the JSON object. Do not include any explanation outside the JSON.\
"""

USER_PROMPT_TEMPLATE = """\
## Repository
{repo}

## PR Title
{nl_title}

## PR Description
{nl_body}

## Commit Messages
{nl_commits}

## Review Comments
{nl_comments}

## Code Changes (unified diff)
{diff_text}
"""


_CHECKLIST_RE = re.compile(r"- \[[ xX]\].*$", re.MULTILINE)
_URL_RE = re.compile(r"https?://\S+")
_WHITESPACE_RE = re.compile(r"\s+")
_BOILERPLATE_RE = re.compile(
    r"^\s*(lgtm|looks good to me|ship it|approved|nit[:\s]|no comments?\.?)\s*$",
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    cleaned = _CHECKLIST_RE.sub("", text)
    cleaned = _URL_RE.sub("", cleaned)
    cleaned = cleaned.replace("###", " ")
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def _is_substantive(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and len(stripped.split()) >= 8 and not _BOILERPLATE_RE.match(stripped)


def _split_patch_into_hunks(patch: str) -> list[str]:
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


def _normalize_raw_pr(pr: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a raw PullRequestRecord dict into file-level records matching dataset.jsonl layout."""
    nl_title = _clean_text(pr.get("title") or "")
    nl_body = _clean_text(pr.get("body") or "")

    substantive_comments = [
        _clean_text(c)
        for c in pr.get("comments", []) + pr.get("review_comments", [])
        if _is_substantive(c)
    ]
    substantive_commits = [
        _clean_text(m) for m in pr.get("commit_messages", []) if _is_substantive(m)
    ]

    nl_comments = " | ".join(substantive_comments)
    nl_commits = " | ".join(substantive_commits)
    nl_description = f"{nl_title}. {nl_body}".strip(". ").strip()
    nl_description_extended = " ".join(
        p for p in [nl_description, nl_commits, nl_comments] if p
    )

    records: list[dict[str, Any]] = []
    for file in pr.get("changed_files", []):
        records.append(
            {
                "repo": pr["repo"],
                "pr_id": pr["pr_id"],
                "filename": file["filename"],
                "diff_hunks": _split_patch_into_hunks(file.get("patch", "")),
                "nl_title": nl_title,
                "nl_body": nl_body,
                "nl_comments": nl_comments,
                "nl_commits": nl_commits,
                "nl_description": nl_description,
                "nl_description_extended": nl_description_extended,
                # raw records don't carry pr_valid; treat as True (pre-filtered by user)
                "pr_valid": True,
                "pr_validity_reasons": ["sourced from raw_prs file"],
            }
        )
    return records


def load_dataset(path: Path) -> list[dict[str, Any]]:
    """Load dataset.jsonl (JSONL) or raw_prs_*.json (JSON array), auto-detected."""
    text = path.read_text(encoding="utf-8").lstrip()
    if text.startswith("["):
        # Raw JSON array of PullRequestRecord dicts
        raw_prs: list[dict[str, Any]] = json.loads(text)
        records: list[dict[str, Any]] = []
        for pr in raw_prs:
            records.extend(_normalize_raw_pr(pr))
        print(f"Loaded {len(raw_prs)} PR(s) from raw JSON → {len(records)} file-level record(s)")
        return records
    # JSONL format
    records = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    print(f"Loaded {len(records)} record(s) from JSONL dataset")
    return records


def load_processed_pr_ids(path: Path) -> set[tuple[str, int]]:
    if not path.exists():
        return set()
    processed: set[tuple[str, int]] = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                processed.add((item["repo"], item["pr_id"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return processed


def group_records_by_pr(
    records: list[dict[str, Any]],
) -> dict[tuple[str, int], list[dict[str, Any]]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        key = (record["repo"], record["pr_id"])
        grouped[key].append(record)
    return dict(grouped)


def build_user_prompt(pr_records: list[dict[str, Any]]) -> str:
    first = pr_records[0]

    hunk_parts: list[str] = []
    for record in pr_records:
        filename = record["filename"]
        for hunk in record.get("diff_hunks", []):
            hunk_parts.append(f"### {filename}\n{hunk}")

    diff_text = "\n---\n".join(hunk_parts)
    if len(diff_text) > MAX_DIFF_CHARS:
        diff_text = diff_text[:MAX_DIFF_CHARS] + "\n[... diff truncated for brevity ...]"

    return USER_PROMPT_TEMPLATE.format(
        repo=first["repo"],
        nl_title=first.get("nl_title") or "(no title)",
        nl_body=first.get("nl_body") or "(no description)",
        nl_commits=first.get("nl_commits") or "(none)",
        nl_comments=first.get("nl_comments") or "(none)",
        diff_text=diff_text or "(no diff available)",
    )


def call_claude_with_retry(
    client: anthropic.Anthropic,
    system_blocks: str | list[dict[str, Any]],
    user_prompt: str,
    model: str = MODEL,
) -> tuple[str, Any]:
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.messages.create(
                model=model,
                max_tokens=512,
                system=system_blocks,
                messages=[{"role": "user", "content": user_prompt}],
            )
            text = next(
                (block.text for block in response.content if block.type == "text"), ""
            )
            return text, response.usage
        except anthropic.RateLimitError as exc:
            last_exc = exc
            retry_after = 10 * attempt
            try:
                retry_after = int(exc.response.headers.get("retry-after", retry_after))
            except Exception:
                pass
            print(f"  Rate limited. Waiting {retry_after}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(retry_after)
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                last_exc = exc
                wait = attempt * 3
                print(f"  Server error {exc.status_code}, retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(wait)
            else:
                raise
        except anthropic.APIConnectionError as exc:
            last_exc = exc
            wait = attempt * 2
            print(f"  Network error, retrying in {wait}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait)

    raise RuntimeError(f"Claude API call failed after {MAX_RETRIES} attempts") from last_exc


def parse_intent_response(text: str) -> dict[str, Any]:
    fallback = {
        "intent_category": "unknown",
        "intent_summary": f"Parse error: {text[:120]}",
        "intent_confidence": "low",
    }

    stripped = text.strip()

    # Remove optional markdown code fences
    stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
    stripped = re.sub(r"\s*```$", "", stripped)

    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            return fallback
        try:
            parsed = json.loads(match.group())
        except json.JSONDecodeError:
            return fallback

    if not isinstance(parsed, dict):
        return fallback

    category = parsed.get("intent_category", "unknown")
    if category not in VALID_CATEGORIES:
        category = "unknown"

    confidence = parsed.get("intent_confidence", "low")
    if confidence not in {"high", "medium", "low"}:
        confidence = "low"

    return {
        "intent_category": category,
        "intent_summary": str(parsed.get("intent_summary", "")),
        "intent_confidence": confidence,
    }


def analyze_pr_intent(
    client: anthropic.Anthropic,
    pr_key: tuple[str, int],
    pr_records: list[dict[str, Any]],
    system_blocks: str | list[dict[str, Any]],
    delay: float,
    model: str = MODEL,
) -> dict[str, Any]:
    repo, pr_id = pr_key
    first = pr_records[0]

    user_prompt = build_user_prompt(pr_records)

    intent_fields: dict[str, Any] = {
        "intent_category": "unknown",
        "intent_summary": "",
        "intent_confidence": "low",
    }
    analysis_skipped = False
    analysis_error = None

    try:
        response_text, _ = call_claude_with_retry(client, system_blocks, user_prompt, model=model)
        intent_fields = parse_intent_response(response_text)
    except Exception as exc:
        analysis_error = str(exc)
        analysis_skipped = True
        print(f"  ERROR analyzing {repo}#{pr_id}: {exc}")

    time.sleep(delay)

    return {
        "repo": repo,
        "pr_id": pr_id,
        "pr_valid": first.get("pr_valid", False),
        "pr_validity_reasons": first.get("pr_validity_reasons", []),
        "nl_title": first.get("nl_title", ""),
        "nl_body": first.get("nl_body", ""),
        "nl_comments": first.get("nl_comments", ""),
        "nl_commits": first.get("nl_commits", ""),
        "nl_description": first.get("nl_description", ""),
        "nl_description_extended": first.get("nl_description_extended", ""),
        "filenames": [r["filename"] for r in pr_records],
        **intent_fields,
        "analyzed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL,
        "analysis_skipped": analysis_skipped,
        "analysis_error": analysis_error,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze PR code change intent using Claude API."
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all PRs including pr_valid=False (default: only pr_valid=True)",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=INPUT_FILE,
        help="Path to input dataset.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_FILE,
        help="Path to output intent_analysis.jsonl",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="Seconds to wait between API calls (default: 0.5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print prompts and skip API calls",
    )
    parser.add_argument(
        "--model",
        default=MODEL,
        help=f"Claude model ID to use (default: {MODEL})",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key and not args.dry_run:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Please export your Anthropic API key first.")

    records = load_dataset(args.input)
    all_groups = group_records_by_pr(records)

    if args.all:
        target_groups = all_groups
    else:
        target_groups = {
            k: v for k, v in all_groups.items() if v[0].get("pr_valid", False)
        }

    processed_ids = load_processed_pr_ids(args.output)
    remaining = {k: v for k, v in target_groups.items() if k not in processed_ids}

    total = len(target_groups)
    already_done = len(processed_ids & target_groups.keys())
    print(f"Total target PRs: {total} | Already processed: {already_done} | To analyze: {len(remaining)}")

    if args.dry_run:
        for pr_key, pr_records in list(remaining.items())[:2]:
            repo, pr_id = pr_key
            prompt_preview = build_user_prompt(pr_records)[:600].encode(
                sys.stdout.encoding or "utf-8", errors="replace"
            ).decode(sys.stdout.encoding or "utf-8", errors="replace")
            print(f"\n{'='*60}")
            print(f"DRY RUN -- {repo}#{pr_id}")
            print(f"{'='*60}")
            print(prompt_preview)
            print("...")
        return

    system_blocks = SYSTEM_PROMPT

    base_url = os.getenv("ANTHROPIC_BASE_URL")
    client = anthropic.Anthropic(
        api_key=api_key,
        **({"base_url": base_url} if base_url else {}),
    )

    args.output.parent.mkdir(exist_ok=True)
    processed = 0
    errors = 0

    with args.output.open("a", encoding="utf-8") as out_handle:
        for idx, (pr_key, pr_records) in enumerate(remaining.items(), start=1):
            repo, pr_id = pr_key
            print(f"[{idx}/{len(remaining)}] Analyzing {repo}#{pr_id} ({len(pr_records)} file(s))...")

            result = analyze_pr_intent(client, pr_key, pr_records, system_blocks, args.delay, model=args.model)
            out_handle.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_handle.flush()

            if result["analysis_skipped"]:
                errors += 1
            else:
                processed += 1
                print(f"  -> [{result['intent_category']}] ({result['intent_confidence']}) {result['intent_summary'][:80]}")

    print(f"\nDone. Analyzed: {processed}, Errors: {errors}, Skipped (already done): {already_done}")
    print(f"Results written to {args.output}")


if __name__ == "__main__":
    main()
