# PR Runnable Filtering Demo

This demo shows a minimal Python pipeline for the following steps:

1. Collect repository and PR data (from GitHub)
2. Filter candidate PRs
3. Extract runnable code fragments
4. Clean and align natural language descriptions
5. Build the dataset, run quality checks, and export outputs

## Files

- `collector/`: collection package (GitHub client, issue parsing, orchestration)
- `demo_pipeline.py`: downstream pipeline (filter -> extract -> align -> build)
- `analyze_intent.py`: PR change-intent classification via the Claude API
- `analyze_nl_thresholds.py`: derive NL quality thresholds from collected data
- `plot_nl_thresholds.py`: visualise NL length distributions
- `output/raw_prs/<owner>__<repo>.jsonl`: collected PR records (one JSON object per line)
- `output/raw_prs/manifest.json`: collection metadata (schema version, counts, resume info)
- `output/dataset.jsonl`: generated dataset samples
- `output/quality_report.json`: generated quality report

## Run

Set a GitHub token first:

```bash
export GITHUB_TOKEN=your_token_here
```

Then collect real PRs and run the full pipeline:

```bash
python demo_pipeline.py --owner psf --repo requests --limit 5
```

Re-running skips PRs already collected (incremental). To force a fresh fetch:

```bash
python demo_pipeline.py --owner psf --repo requests --limit 5 --no-resume
```

## What This Demo Does

- Uses the GitHub REST API (with pagination and retries) to collect merged PRs
- Caches raw PR records to `output/raw_prs/` as versioned JSONL plus a manifest
- Scores PRs with simple heuristics
- Treats merged PRs with successful CI as runnable candidates
- Extracts Python file patches as runnable fragments
- Cleans PR title/body into a usable natural language description
- Exports final aligned samples as JSONL

## Downstream Tools

- `python analyze_nl_thresholds.py [--fetch owner/repo ...]` — derive NL length thresholds
- `python analyze_intent.py --input output/dataset.jsonl` — classify PR change intent
- `python plot_nl_thresholds.py` — visualise NL length distributions

## How To Extend It

- Replace heuristic verification with Docker-based build and test execution
- Replace file-level extraction with AST-level or coverage-based fragment extraction
- Add SQLite or Parquet output for larger-scale experiments
