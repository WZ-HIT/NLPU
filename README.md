# PR Runnable Filtering Demo

This demo shows a minimal Python pipeline for the following six steps:

1. Collect repository and PR data
2. Filter candidate PRs
3. Verify runnable PRs
4. Extract runnable code fragments
5. Clean and align natural language descriptions
6. Build the dataset, run quality checks, and export outputs

## Files

- `demo_pipeline.py`: main pipeline script
- `data/sample_prs.json`: local sample PR data
- `output/raw_prs_<owner>_<repo>.json`: cached GitHub PR records
- `output/dataset.jsonl`: generated dataset samples
- `output/quality_report.json`: generated quality report

## Run With Local Sample Data

```bash
python demo_pipeline.py
```

## Run With Real GitHub PR Data

Set a GitHub token first:

```bash
set GITHUB_TOKEN=your_token_here
```

Then fetch real PRs:

```bash
python demo_pipeline.py --mode github --owner psf --repo requests --limit 5
```

## What This Demo Does

- Supports local sample data and live GitHub REST API collection
- Uses GitHub pagination to fetch real PRs
- Caches raw GitHub PR records to the `output` directory
- Scores PRs with simple heuristics
- Treats merged PRs with successful CI as runnable candidates
- Extracts Python file patches as runnable fragments
- Cleans PR title/body into a usable natural language description
- Exports final aligned samples as JSONL

## How To Extend It

- Replace heuristic verification with Docker-based build and test execution
- Replace file-level extraction with AST-level or coverage-based fragment extraction
- Add SQLite or Parquet output for larger-scale experiments
