"""Empirically derive NL-quality thresholds for the PR dataset pipeline.

Motivation
----------
`demo_pipeline.is_valid_pr` currently uses two hand-picked constants:
    - title_words >= 4
    - body_words  >= 10  (or a substantive supplementary message)

These numbers have no scientific justification.  This script collects a
large pool of merged PR records, measures the natural-language length
distribution (title / body / comments / commits), and proposes
statistically grounded cut-offs.

Method
------
1. Load every cached ``output/raw_prs/<owner>__<repo>.jsonl`` produced by
   the collector and, optionally, fetch additional PRs from GitHub via
   ``--fetch owner/repo``.
2. For each PR compute four length features (word counts).
3. Summarise each feature with:
     - mean / stdev / median / min / max
     - percentiles (5, 10, 25, 50, 75, 90, 95)
     - Shapiro-ish sanity check via a normality heuristic (skewness).
4. Because word-count distributions are typically right-skewed,
   the script also fits a log-normal (stats on log(1+x)) and maps
   mu - k*sigma back to the original scale.  This is usually a
   tighter, more meaningful lower bound than raw mean - sigma.
5. Emit recommended thresholds for title_words and body_words using
   both methods, and produce an ASCII histogram so the user can
   eyeball the shape.

Only the Python standard library is used (no numpy / scipy /
matplotlib) so the script runs in the same environment as
``demo_pipeline.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from pathlib import Path
from typing import Any

from collector import PullRequestRecord, collect_prs, load_records, raw_prs_dir
from demo_pipeline import OUTPUT_DIR, clean_text


REPORT_PATH = OUTPUT_DIR / "nl_threshold_report.json"
TEXT_REPORT_PATH = OUTPUT_DIR / "nl_threshold_report.txt"


# ---------------------------------------------------------------------------
# Loading raw PR records
# ---------------------------------------------------------------------------


def load_cached_records(output_dir: Path) -> list[PullRequestRecord]:
    """Load every ``raw_prs/<owner>__<repo>.jsonl`` produced by the collector."""
    records: list[PullRequestRecord] = []
    for path in sorted(raw_prs_dir(output_dir).glob("*.jsonl")):
        records.extend(load_records(path))
    return records


def fetch_additional_records(
    specs: list[str], limit_per_repo: int, state: str
) -> list[PullRequestRecord]:
    """Fetch merged PRs from GitHub for each ``owner/repo`` spec."""
    token = os.getenv("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set; cannot use --fetch. "
            "Drop the flag to analyse cached records only."
        )

    all_records: list[PullRequestRecord] = []
    for spec in specs:
        if "/" not in spec:
            raise ValueError(f"--fetch expects owner/repo, got {spec!r}")
        owner, repo = spec.split("/", 1)
        print(f"[fetch] pulling up to {limit_per_repo} merged PRs from {spec} ...")

        repo_records = collect_prs(
            owner=owner,
            repo=repo,
            limit=limit_per_repo,
            state=state,
            output_dir=OUTPUT_DIR,
            resume=True,
        )
        print(f"[fetch] cached {len(repo_records)} records for {spec}")
        all_records.extend(repo_records)

    return all_records


# ---------------------------------------------------------------------------
# Feature extraction
# ---------------------------------------------------------------------------


def extract_features(records: list[PullRequestRecord]) -> list[dict[str, Any]]:
    """Turn each PR into a dict of integer length features."""
    rows: list[dict[str, Any]] = []
    for pr in records:
        title_words = len(pr.title.split())
        body_words = len(clean_text(pr.body).split())
        comments_words = sum(len(clean_text(c).split()) for c in pr.comments + pr.review_comments)
        commits_words = sum(len(clean_text(m).split()) for m in pr.commit_messages)
        rows.append(
            {
                "repo": pr.repo,
                "pr_id": pr.pr_id,
                "title_words": title_words,
                "body_words": body_words,
                "comments_words": comments_words,
                "commits_words": commits_words,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[float], pct: float) -> float:
    """Linear-interpolated percentile.  ``pct`` is in [0, 100]."""
    if not sorted_values:
        return math.nan
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(sorted_values[low])
    frac = rank - low
    return sorted_values[low] * (1 - frac) + sorted_values[high] * frac


def skewness(values: list[float], mean: float, stdev: float) -> float:
    """Population skewness (Fisher-Pearson).  Returns 0 when stdev ~ 0."""
    if stdev <= 1e-12 or len(values) < 2:
        return 0.0
    n = len(values)
    cubed = sum(((v - mean) / stdev) ** 3 for v in values)
    return cubed / n


def summarise(values: list[int]) -> dict[str, Any]:
    """Descriptive stats + log-normal parameters + threshold suggestions."""
    if not values:
        return {"count": 0}

    sorted_vals = sorted(values)
    mean = statistics.fmean(values)
    stdev = statistics.pstdev(values)
    skew = skewness(values, mean, stdev)

    log_values = [math.log1p(v) for v in values]
    log_mean = statistics.fmean(log_values)
    log_stdev = statistics.pstdev(log_values)

    def back(k: float) -> float:
        """mu - k*sigma on log scale, mapped back to original scale."""
        return math.expm1(log_mean - k * log_stdev)

    pcts = {f"p{p}": percentile(sorted_vals, p) for p in (5, 10, 25, 50, 75, 90, 95)}

    return {
        "count": len(values),
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "mean": round(mean, 3),
        "stdev": round(stdev, 3),
        "skewness": round(skew, 3),
        "percentiles": {k: round(v, 3) for k, v in pcts.items()},
        "lognormal": {
            "log_mean": round(log_mean, 3),
            "log_stdev": round(log_stdev, 3),
            "lower_mu_minus_1sigma": round(back(1.0), 3),
            "lower_mu_minus_2sigma": round(back(2.0), 3),
        },
        "threshold_suggestions": {
            "p10": int(math.ceil(pcts["p10"])),
            "p25": int(math.ceil(pcts["p25"])),
            "mean_minus_1sigma_normal": int(math.ceil(max(0.0, mean - stdev))),
            "mean_minus_1sigma_lognormal": int(math.ceil(max(0.0, back(1.0)))),
        },
    }


# ---------------------------------------------------------------------------
# ASCII histogram (so the user can eyeball shape without matplotlib)
# ---------------------------------------------------------------------------


def ascii_histogram(values: list[int], bins: int = 20, width: int = 50) -> str:
    if not values:
        return "(no data)"
    lo, hi = min(values), max(values)
    if lo == hi:
        return f"  all values = {lo} (n={len(values)})"

    step = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / step), bins - 1)
        counts[idx] += 1
    peak = max(counts)

    lines: list[str] = []
    for i, c in enumerate(counts):
        left = lo + i * step
        right = left + step
        bar = "#" * int(round(width * c / peak)) if peak else ""
        lines.append(f"  [{left:7.1f}, {right:7.1f}) | {c:5d} | {bar}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


FEATURE_KEYS = ("title_words", "body_words", "comments_words", "commits_words")


def build_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    stats_per_feature = {
        key: summarise([row[key] for row in rows]) for key in FEATURE_KEYS
    }

    title_p10 = stats_per_feature["title_words"]["threshold_suggestions"]["p10"]
    body_p25 = stats_per_feature["body_words"]["threshold_suggestions"]["p25"]

    title_log = stats_per_feature["title_words"]["threshold_suggestions"][
        "mean_minus_1sigma_lognormal"
    ]
    body_log = stats_per_feature["body_words"]["threshold_suggestions"][
        "mean_minus_1sigma_lognormal"
    ]

    return {
        "sample_size": len(rows),
        "features": stats_per_feature,
        "recommended_thresholds": {
            "percentile_based": {
                "title_words_min": title_p10,
                "body_words_min": body_p25,
                "note": (
                    "Title floor at the 10th percentile (drop the shortest 10%),"
                    " body floor at the 25th percentile (drop the shortest 25%)."
                    " Rationale: word counts are right-skewed, so percentiles"
                    " are more robust than mean +/- sigma."
                ),
            },
            "lognormal_based": {
                "title_words_min": title_log,
                "body_words_min": body_log,
                "note": (
                    "Threshold = exp(mu_log - sigma_log) - 1, i.e. the lower-1-sigma"
                    " point after log(1+x) normalisation.  Keeps roughly the central"
                    " 84% of the distribution."
                ),
            },
            "current_hardcoded": {
                "title_words_min": 4,
                "body_words_min": 10,
                "note": "The baseline in demo_pipeline.is_valid_pr, no empirical basis.",
            },
        },
    }


def format_text_report(report: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    out: list[str] = []
    out.append(f"NL quality threshold analysis  (n = {report['sample_size']} PRs)")
    out.append("=" * 70)

    for key, stats in report["features"].items():
        out.append("")
        out.append(f"[{key}]")
        if stats.get("count", 0) == 0:
            out.append("  (no data)")
            continue
        out.append(
            f"  mean={stats['mean']}  stdev={stats['stdev']}  "
            f"skew={stats['skewness']}  min={stats['min']}  max={stats['max']}"
        )
        pct = stats["percentiles"]
        out.append(
            "  percentiles: "
            f"p5={pct['p5']}  p10={pct['p10']}  p25={pct['p25']}  "
            f"p50={pct['p50']}  p75={pct['p75']}  p90={pct['p90']}  p95={pct['p95']}"
        )
        ln = stats["lognormal"]
        out.append(
            f"  log-normal:  log_mean={ln['log_mean']}  log_stdev={ln['log_stdev']}  "
            f"mu-1sigma(back)={ln['lower_mu_minus_1sigma']}  "
            f"mu-2sigma(back)={ln['lower_mu_minus_2sigma']}"
        )
        ts = stats["threshold_suggestions"]
        out.append(
            f"  suggestions: p10={ts['p10']}  p25={ts['p25']}  "
            f"normal(mu-1s)={ts['mean_minus_1sigma_normal']}  "
            f"lognormal(mu-1s)={ts['mean_minus_1sigma_lognormal']}"
        )
        out.append("  histogram:")
        out.append(ascii_histogram([row[key] for row in rows]))

    out.append("")
    out.append("Recommended thresholds")
    out.append("-" * 70)
    rec = report["recommended_thresholds"]
    out.append(
        f"  percentile-based : title_words >= {rec['percentile_based']['title_words_min']}"
        f", body_words >= {rec['percentile_based']['body_words_min']}"
    )
    out.append(f"    {rec['percentile_based']['note']}")
    out.append(
        f"  lognormal-based  : title_words >= {rec['lognormal_based']['title_words_min']}"
        f", body_words >= {rec['lognormal_based']['body_words_min']}"
    )
    out.append(f"    {rec['lognormal_based']['note']}")
    out.append(
        f"  current hardcoded: title_words >= {rec['current_hardcoded']['title_words_min']}"
        f", body_words >= {rec['current_hardcoded']['body_words_min']}"
    )
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--fetch",
        nargs="*",
        default=[],
        metavar="OWNER/REPO",
        help="Optional repos to pull fresh PR data from before analysing.",
    )
    parser.add_argument(
        "--limit-per-repo",
        type=int,
        default=100,
        help="Max merged PRs to fetch per repo in --fetch mode (default: 100).",
    )
    parser.add_argument(
        "--state",
        default="closed",
        choices=("closed", "all"),
        help="PR state to consider when fetching (default: closed).",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=30,
        help="Warn if fewer than this many PRs are available (default: 30).",
    )
    args = parser.parse_args()

    records = load_cached_records(OUTPUT_DIR)
    print(f"Loaded {len(records)} PR records from {OUTPUT_DIR}")

    if args.fetch:
        extra = fetch_additional_records(args.fetch, args.limit_per_repo, args.state)
        # De-duplicate on (repo, pr_id) so re-runs are idempotent.
        seen = {(r.repo, r.pr_id) for r in records}
        records.extend(r for r in extra if (r.repo, r.pr_id) not in seen)
        print(f"Combined corpus size: {len(records)} PR records")

    if len(records) < args.min_samples:
        print(
            f"WARNING: only {len(records)} records (< min_samples={args.min_samples})."
            " Statistics may be unstable; consider --fetch to enlarge the corpus."
        )

    rows = extract_features(records)
    report = build_report(rows)

    OUTPUT_DIR.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    text = format_text_report(report, rows)
    TEXT_REPORT_PATH.write_text(text, encoding="utf-8")

    print("")
    print(text)
    print("")
    print(f"Wrote JSON report -> {REPORT_PATH}")
    print(f"Wrote text report -> {TEXT_REPORT_PATH}")


if __name__ == "__main__":
    main()
