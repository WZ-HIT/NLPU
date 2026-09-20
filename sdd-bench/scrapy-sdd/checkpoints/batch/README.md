# Templated batch checkpoints

This directory holds the host-only rollback device for the batch experiments.
It generalises `checkpoints/pre-experiment-pr8073-*`, which protects one
hand-built deployment, into a template that covers the whole PR pool.

## Identity

The device is two layers plus one tool:

- `shared/` — deployment-wide state, captured once for every PR.
- `pr/<task_id>/` — one layer per task, holding only that task's evidence.
- `bin/sdd-checkpoint` — capture, verify, restore, and status.

Each layer holds `checkpoint.json` (trackable metadata), `SHA256SUMS`, and
`payloads/` (git-ignored archives). `restore-backups/<UTC>/` holds whatever a
restore or a `--refresh` replaced.

Nothing here is per-PR scripting. Adding the 98th PR to `tasks/` requires no
change to any file in this tree; `capture --pr-all` picks it up.

## What it protects

The partition is **irreplaceable versus rebuildable**, not per-PR:

- The shared layer packages `batch/baselines/*` (the two pure baseline caches,
  including their self-contained shallow Git repositories), `batch/images/*`
  (the Dockerfiles and stage scripts), `batch/runs/*` (every batch ledger,
  barrier, final report, and evaluation artifact), and an export of the six
  pinned Docker images.
- A task layer packages the whole `tasks/<task_id>/` tree except the nine
  per-method workspaces, plus `batch/gold/<task_id>/`.
- Git-tracked inputs — `output/prompt/scrapy__scrapy.json`,
  `output/raw_prs/scrapy__scrapy.jsonl`, and the tracked Codex and egress
  configuration — are recorded by SHA256 and Git blob SHA, not packaged.
- Docker images are exported by default. `capture --shared --skip-images`
  records their IDs and digests without the archive.

Exclusions are a deny-list of exactly two workspace shapes plus `.git`, not an
allow-list of evidence directories. A new artifact type is therefore packaged by
default instead of being dropped silently. Every excluded directory must pass a
regenerability assertion at capture time or the capture fails and names the
offending path:

- `runs/<method>/detect/workspace` — `HEAD` must equal the recorded base SHA and
  every untracked path must fall under `initialization/<method>/files`.
- `runs/<method>/update/executions/*/attempt-*/mode-*/workspace` — every tracked
  modification must appear in the sibling `artifacts/candidate.patch`, and every
  untracked path must fall under `initialization/<method>/files`.

Keeping those workspaces out is what makes 98 PRs affordable. Measured, not
estimated: a task directory is roughly 86M on disk, its payload compresses to
**0.76–0.89M**, and the shared layer is **707M** — of which 668M is the Docker
export and only about 6.6M is baselines, stage scripts, and batch-run evidence.
The Docker export deduplicates layers shared between the six pinned tags, which
is why it is far smaller than the sum of `docker images` sizes (5.3G). At that
rate the full 98-PR pool costs well under 100M on top of the shared layer.

Raw inputs and tracked configuration are recorded rather than packaged, so the
metadata paths are always repository-root-relative even though the two lists are
authored against different bases: the deployment config lives inside the bench
(`environments/...`), the dataset inputs live at the repository root
(`output/...`). `layout.tracked_input_rows` rebases both onto the repository
root, which is what Git and the checkpoint metadata speak.

## Verifying

```
./bin/sdd-checkpoint verify --shared
./bin/sdd-checkpoint verify --pr scrapy__scrapy__pr8073
```

Verification re-derives hashes rather than trusting metadata:

- every payload archive is re-hashed against `SHA256SUMS` and its own manifest,
- each payload is re-extracted into a scratch directory and checked line by line
  against `payloads/<name>.files.sha256`,
- baseline cache `HEAD^{tree}` and base-commit presence are read back out of the
  cache repository,
- each recorded image tag is compared against `docker image inspect`,
- the ledger event count, ledger hash, and last event hash are recomputed,
- for a task, `update/sealed-input/detection-manifest.json` is required to be
  byte-identical to the manifest inside at least one detect execution, which is
  the same cross-artifact rule `batch/reporting.py` enforces at report time.

Docker and credential probes degrade to `SKIP` when they cannot run; anything
else fails. The command exits non-zero if any check fails.

## Restoring

```
./bin/sdd-checkpoint restore --shared --yes
./bin/sdd-checkpoint restore --pr scrapy__scrapy__pr8073 --yes
```

`--yes` is mandatory. Restore then refuses outright if a batch is holding
`batch/runs/<batch_id>/run.lock` or if any container of that task's Compose
project is still running.

The ordering is: validate every payload first, confirm the host is quiescent,
move the current state into `restore-backups/<UTC>/`, extract the payloads, reload
the Docker images, re-check the tracked inputs, then run the full `verify` pass
and report its result.

Two properties matter:

- Nothing is ever deleted. Replaced state is moved, not removed, and a
  `--refresh` capture moves the previous checkpoint aside the same way.
- Task restore swaps one method's `runs/<method>/{detect,update}` at a time.
  Restoring only part of a method would leave `sealed-input` inconsistent with
  the detect execution and make `sdd-pilot report` raise.

Restoring does not start a container and does not open an API key. Batch stages
are one-shot, so the endpoint is "files back on disk and `verify` passing", not
`docker compose up`.

## Safety properties

- The preflight credential at `~/.config/sdd-bench/deepseek-api-key` is only ever
  existence-checked. It is never opened, copied, or written into metadata.
- `payloads/` and `restore-backups/` are git-ignored. Payloads can embed gold
  content, notably `batch/runs/*/evaluation/*/runs/*/logs/hidden_production_patch.log`,
  which must be treated exactly like `batch/gold/`.
- Checkpoint directories are created mode 0700 and metadata files mode 0600.
- Every layer records `contains_api_secret: false` and the schema enforces it.

## Operational limits

- Capturing changed evidence over an existing layer is refused. `--refresh`
  replaces the active checkpoint after moving the old one into
  `restore-backups/`, so a re-capture is a deliberate act.
- Workspaces are not packaged. Rebuilding one goes through the existing
  `sdd-batch provision`, `scaffold`, and `sdd-pilot update` path; when the
  original `--source-repository` is gone, `batch/baselines/<base_sha>/repository`
  from the shared layer is itself a usable source, because it contains the base
  commit object and has no alternates.
- `batch/runs/<batch_id>/run.lock` is held for the duration of a mutating
  `sdd-pilot` command. Read-only commands (`status`, `evaluate`) do not take it.
  This lock is what makes the restore-time quiescence probe meaningful; before it
  existed, the only lock in `batch/` spanned a single ledger append.
- Restore never deletes. Each replacement moves the displaced state into
  `restore-backups/<UTC>/`, so repeated restores accumulate backup directories.
  They are small (a task's evidence is under 1M) but nothing prunes them.
