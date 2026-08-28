"""Visualise the NL length distributions used by analyze_nl_thresholds.py.

Loads every cached ``output/raw_prs_*.json`` (produced by
``demo_pipeline.py`` / ``analyze_nl_thresholds.py --fetch``) and renders
a multi-panel figure per feature so you can eyeball:

  - raw histogram + KDE-ish smoothing + vertical threshold markers
  - log-scale histogram (word counts are right-skewed, log makes the
    shape approximately Gaussian if a log-normal fit is appropriate)
  - Q-Q plot against the normal distribution on log(1+x) (straight line
    == log-normal)
  - empirical CDF with percentile markers
  - per-repo boxplot so you can see whether one repo's style is
    dominating the pooled statistics

Plus a joint-distribution scatter (title_words vs body_words) so you
can check whether the two features carry independent information.

Writes one PNG per feature plus a combined overview to ``output/``.
Requires matplotlib (``pip install matplotlib``).  Nothing else.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
from pathlib import Path
from typing import Any

from demo_pipeline import OUTPUT_DIR, PullRequestRecord, clean_text

try:
    import matplotlib.pyplot as plt
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "matplotlib is required for this script. Install with: pip install matplotlib"
    ) from exc


FEATURE_KEYS = ("title_words", "body_words", "comments_words", "commits_words")
# Hard-coded thresholds currently used by demo_pipeline.is_valid_pr, shown
# as a dashed vertical line so we can visually judge whether they land in
# a sensible part of the distribution.
CURRENT_THRESHOLDS = {"title_words": 4, "body_words": 10}


# ---------------------------------------------------------------------------
# Data loading / feature extraction
# ---------------------------------------------------------------------------


def load_rows(output_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("raw_prs_*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload:
            pr = PullRequestRecord(**item)
            rows.append(
                {
                    "repo": pr.repo,
                    "pr_id": pr.pr_id,
                    "title_words": len(pr.title.split()),
                    "body_words": len(clean_text(pr.body).split()),
                    "comments_words": sum(
                        len(clean_text(c).split())
                        for c in pr.comments + pr.review_comments
                    ),
                    "commits_words": sum(
                        len(clean_text(m).split()) for m in pr.commit_messages
                    ),
                }
            )
    return rows


# ---------------------------------------------------------------------------
# Small stats helpers (duplicated from analyze_nl_thresholds to keep this
# file independent and runnable on its own).
# ---------------------------------------------------------------------------


def percentile(sorted_values: list[float], pct: float) -> float:
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


def normal_inverse_cdf(p: float) -> float:
    """Acklam's rational approximation to the inverse normal CDF."""
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    p_low, p_high = 0.02425, 1 - 0.02425
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) \
               / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q \
               / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) \
           / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


# ---------------------------------------------------------------------------
# Individual panel plotters
# ---------------------------------------------------------------------------


def plot_histogram(ax, values: list[int], feature: str) -> None:
    ax.hist(values, bins=30, edgecolor="black", alpha=0.7, color="steelblue")
    mean = statistics.fmean(values)
    median = statistics.median(values)
    ax.axvline(mean, color="orange", linestyle="-", label=f"mean={mean:.1f}")
    ax.axvline(median, color="green", linestyle="-", label=f"median={median:.1f}")
    ax.axvline(percentile(sorted(values), 25), color="purple", linestyle=":",
               label=f"p25={percentile(sorted(values), 25):.1f}")
    if feature in CURRENT_THRESHOLDS:
        t = CURRENT_THRESHOLDS[feature]
        ax.axvline(t, color="red", linestyle="--", label=f"current={t}")
    ax.set_title(f"{feature} histogram (raw)")
    ax.set_xlabel(feature)
    ax.set_ylabel("count")
    ax.legend(fontsize=8)


def plot_log_histogram(ax, values: list[int], feature: str) -> None:
    log_vals = [math.log1p(v) for v in values]
    ax.hist(log_vals, bins=30, edgecolor="black", alpha=0.7, color="seagreen")
    log_mean = statistics.fmean(log_vals)
    log_std = statistics.pstdev(log_vals)
    ax.axvline(log_mean, color="orange", linestyle="-", label=f"log-mean={log_mean:.2f}")
    ax.axvline(log_mean - log_std, color="red", linestyle="--",
               label=f"mu-sigma={log_mean - log_std:.2f}")
    ax.set_title(f"{feature} histogram (log(1+x))")
    ax.set_xlabel(f"log(1 + {feature})")
    ax.set_ylabel("count")
    ax.legend(fontsize=8)


def plot_qq(ax, values: list[int], feature: str) -> None:
    """Q-Q plot of log(1+x) against the standard normal.

    Points on a straight line ==> the log-transformed data is Gaussian
    ==> the raw data is log-normal, which justifies the log-based
    threshold derivation.
    """
    log_vals = sorted(math.log1p(v) for v in values)
    n = len(log_vals)
    theoretical = [normal_inverse_cdf((i + 0.5) / n) for i in range(n)]
    ax.scatter(theoretical, log_vals, s=12, alpha=0.6)
    lo = min(theoretical[0], log_vals[0])
    hi = max(theoretical[-1], log_vals[-1])
    ax.plot([lo, hi], [lo * statistics.pstdev(log_vals) + statistics.fmean(log_vals)] * 2,
            color="red", linewidth=0.8)
    # reference line: y = mean + std*x
    m = statistics.fmean(log_vals)
    s = statistics.pstdev(log_vals)
    ax.plot([lo, hi], [m + s * lo, m + s * hi], color="red", linewidth=1,
            label="log-normal fit")
    ax.set_title(f"{feature} Q-Q plot vs normal")
    ax.set_xlabel("theoretical quantile")
    ax.set_ylabel(f"sample log(1+{feature})")
    ax.legend(fontsize=8)


def plot_cdf(ax, values: list[int], feature: str) -> None:
    sv = sorted(values)
    ys = [(i + 1) / len(sv) for i in range(len(sv))]
    ax.plot(sv, ys, linewidth=1.2)
    for pct in (10, 25, 50, 75, 90):
        v = percentile(sv, pct)
        ax.axvline(v, color="gray", linestyle=":", linewidth=0.7)
        ax.text(v, pct / 100, f" p{pct}={v:.0f}", fontsize=7, va="bottom")
    if feature in CURRENT_THRESHOLDS:
        t = CURRENT_THRESHOLDS[feature]
        ax.axvline(t, color="red", linestyle="--", label=f"current={t}")
        ax.legend(fontsize=8)
    ax.set_title(f"{feature} empirical CDF")
    ax.set_xlabel(feature)
    ax.set_ylabel("F(x)")
    ax.set_ylim(0, 1)


def plot_box_by_repo(ax, rows: list[dict[str, Any]], feature: str) -> None:
    repos: dict[str, list[int]] = {}
    for row in rows:
        repos.setdefault(row["repo"], []).append(row[feature])
    keys = sorted(repos.keys())
    ax.boxplot([repos[k] for k in keys], tick_labels=keys, vert=True, showfliers=True)
    ax.set_title(f"{feature} by repo")
    ax.set_ylabel(feature)
    ax.tick_params(axis="x", rotation=20, labelsize=8)


# ---------------------------------------------------------------------------
# Top-level figure composition
# ---------------------------------------------------------------------------


def render_feature_figure(rows: list[dict[str, Any]], feature: str, out_path: Path) -> None:
    values = [row[feature] for row in rows]
    if not values:
        print(f"  skip {feature}: no data")
        return

    fig, axes = plt.subplots(2, 3, figsize=(17, 9))
    plot_histogram(axes[0, 0], values, feature)
    plot_log_histogram(axes[0, 1], values, feature)
    plot_qq(axes[0, 2], values, feature)
    plot_cdf(axes[1, 0], values, feature)
    plot_box_by_repo(axes[1, 1], rows, feature)

    # Summary text in the last panel.
    sv = sorted(values)
    log_vals = [math.log1p(v) for v in values]
    summary = [
        f"{feature}  (n={len(values)})",
        f"  mean   = {statistics.fmean(values):.2f}",
        f"  stdev  = {statistics.pstdev(values):.2f}",
        f"  median = {statistics.median(values)}",
        f"  min/max= {sv[0]} / {sv[-1]}",
        "",
        f"  p10    = {percentile(sv, 10):.1f}",
        f"  p25    = {percentile(sv, 25):.1f}",
        f"  p50    = {percentile(sv, 50):.1f}",
        f"  p75    = {percentile(sv, 75):.1f}",
        f"  p90    = {percentile(sv, 90):.1f}",
        "",
        f"  log_mean  = {statistics.fmean(log_vals):.3f}",
        f"  log_stdev = {statistics.pstdev(log_vals):.3f}",
        f"  mu-1s back= {math.expm1(statistics.fmean(log_vals) - statistics.pstdev(log_vals)):.2f}",
    ]
    if feature in CURRENT_THRESHOLDS:
        summary += ["", f"  current threshold = {CURRENT_THRESHOLDS[feature]}"]
    axes[1, 2].axis("off")
    axes[1, 2].text(0, 1, "\n".join(summary), family="monospace",
                    fontsize=10, va="top", ha="left")

    fig.suptitle(f"NL length distribution — {feature}", fontsize=14)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


def render_joint_scatter(rows: list[dict[str, Any]], out_path: Path) -> None:
    """Scatter title_words vs body_words — do they add independent info?"""
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(7, 6))
    repos = sorted({r["repo"] for r in rows})
    cmap = plt.get_cmap("tab10")
    for i, repo in enumerate(repos):
        pts = [(r["title_words"], r["body_words"]) for r in rows if r["repo"] == repo]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.scatter(xs, ys, s=14, alpha=0.6, label=repo, color=cmap(i % 10))
    ax.axvline(CURRENT_THRESHOLDS["title_words"], color="red", linestyle="--", linewidth=0.8)
    ax.axhline(CURRENT_THRESHOLDS["body_words"], color="red", linestyle="--", linewidth=0.8)
    ax.set_xlabel("title_words")
    ax.set_ylabel("body_words")
    ax.set_title("Joint distribution: title vs body (red dashes = current thresholds)")
    ax.set_yscale("symlog", linthresh=1)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"  wrote {out_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--input-dir", type=Path, default=OUTPUT_DIR,
        help="Directory containing raw_prs_*.json files (default: output/).",
    )
    parser.add_argument(
        "--figure-dir", type=Path, default=None,
        help="Directory to write PNG figures into (default: same as --input-dir).",
    )
    args = parser.parse_args()

    figure_dir = args.figure_dir if args.figure_dir is not None else args.input_dir
    figure_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(args.input_dir)
    print(f"Loaded {len(rows)} PR rows across "
          f"{len({r['repo'] for r in rows})} repos from {args.input_dir}")
    if not rows:
        raise SystemExit("No cached PR data found. Run analyze_nl_thresholds.py --fetch first.")

    for feature in FEATURE_KEYS:
        out = figure_dir / f"plot_{feature}.png"
        render_feature_figure(rows, feature, out)

    render_joint_scatter(rows, figure_dir / "plot_title_vs_body.png")
    print(f"done. figures in {figure_dir}")


if __name__ == "__main__":
    main()
