# SDD Benchmark Gold-Leakage Audit

## Purpose

This document defines the gold-leakage audit that must run after a PR task is
provisioned and before any formal Agent call. The audit proves that evaluation
data did not cross into the Agent-visible task environment.

The audit is task-specific and fail-closed. A task may enter
`EXPERIMENT_READY` only when its report status is `PASS`.

## Information boundary

### Agent-visible inputs

An Agent may see only:

- the repository at the task's locked pre-change `base_sha`;
- the task description derived from approved natural-language fields;
- the SDD integration assigned to that Agent;
- common Agent/model configuration that contains no task answer;
- its own private writable repository, HOME, cache and temporary filesystem.

### Host-only evaluation inputs

The following must remain outside every Agent container, bind mount, named
volume, prompt and Agent-accessible Git object store:

- `head_sha` and `merge_commit_sha` when they are used to retrieve future code;
- PR patches and merged-tree content;
- `gold_test`, gold patches and reference answers;
- target files, test names or line ranges learned from hidden gold;
- raw PR records and prompt records that include old/gold test bodies;
- evaluator commands or reports that disclose the hidden target before a run.

`head_sha` and `merge_commit_sha` may appear in a host-side provenance or
evaluation manifest, but that manifest must not be mounted into an Agent.

## Important non-leak cases

The audit must not treat information already present in the locked base
repository as a leak. In particular:

- an old test file and old test name naturally present at `base_sha` are allowed;
- an error marker appearing in both the PR title/body and the base source is
  allowed when its prompt provenance is the approved natural-language field;
- an Agent finding a relevant file through its own repository search is allowed;
- generic SDD templates and skills are allowed when their bytes match the locked
  initialization manifest.

The boundary concerns generated control-plane input and inaccessible future/gold
state, not facts that an Agent independently discovers in the base repository.

## Approved natural-language provenance

By default, the generated task description may use only:

- `repo`;
- `pr_id` for host-side identity and a neutral task label;
- PR `title`;
- PR `body`.

Comments, review comments, commit messages and issue bodies require an explicit
policy decision because they may contain filenames, patches, CI links, head
SHAs or reviewer hints. The first batch should exclude them.

The generated description must record a SHA-256 digest of each source field and
of the final rendered task input. The audit report records hashes, not the
hidden gold content.

## Required checks

### G01 — Input identity

- Resolve exactly one raw PR record for `(repository, pr_id)`.
- Resolve all selected sample records for that PR.
- Verify that the task's `base_sha` matches the approved baseline policy.
- Verify that task input was rendered from the declared source fields.

### G02 — Prompt provenance

- Compare the rendered task input with a fresh render from approved fields.
- Reject unexplained text that was not introduced by the fixed public template.
- Reject use of the dataset `prompt` field, because it contains target file,
  target test and old test code.
- Reject use of raw `gold_test`, PR patch or merged source when rendering input.

### G03 — Forbidden-value scan of generated Agent-visible files

Scan generated files outside the base repository, including:

- task input;
- task/experiment configuration;
- Compose environment and labels;
- Codex configuration;
- launcher-generated phase prompts;
- SDD initialization files that differ from their locked generic manifests.

Check for forbidden exact values and derived signatures, including:

- `head_sha` and `merge_commit_sha`;
- full gold-test hashes;
- sufficiently long, distinctive gold-only text fragments;
- gold-derived target file/test identifiers when they are absent from approved
  title/body input;
- absolute paths to raw/gold datasets.

Do not include the matched gold text in normal logs. Record a finding category,
file, line number when safe, and a one-way signature.

### G04 — Mount and volume audit

- Inspect the effective Compose configuration and live container mounts.
- Permit only the assigned repository, private HOME, fixed read-only runtime
  configuration, provider secret mechanism and private tmpfs.
- Reject mounts containing `output/raw_prs`, `output/prompt`, evaluator data,
  another SDD repository or a prior experiment result.
- Verify that no named volume is shared between SDD variants.

### G05 — Git future-history audit

For the baseline and all three experiment repositories:

- `HEAD` must equal the task `base_sha`;
- the recorded tree must equal the baseline tree;
- reachable commit count must be one;
- configured remote count must be zero;
- remote-tracking references must be absent;
- Git alternates must be absent;
- the repository must not contain reachable `head_sha` or merge-result commits;
- the repository must not share a writable object store with another variant.

If unreachable future objects are retained in `.git/objects`, either remove them
or prove they cannot be named or recovered by the Agent. The preferred policy is
to omit them completely.

### G06 — Network and process boundary

- Direct external access from an Agent must be denied.
- Only the fixed provider proxy path may be available.
- Git remotes and repository credentials must be absent.
- Provider credentials must not be readable by the sandboxed Agent command.
- An Agent must not be able to inspect host-side evaluator processes or paths.

### G07 — Cross-variant and prior-run isolation

- Each SDD receives identical task-input bytes.
- An SDD can access only its own repository, HOME, cache, tmpfs and proxy.
- No variant can read another variant's artifacts or changes.
- No new run can read a previous run's result directory or persistent session.

### G08 — Viewer/evaluator timing

- Gold comparison and result rendering occur only after Agent output is sealed.
- The host-side viewer and evaluator are not mounted into a running Agent.
- A rerun begins only after restoring the checkpoint and creating a new result
  identity; reviewed gold data must not survive in Agent HOME or workspace.

## Audit output

Each task produces a host-side directory such as:

```text
Log/<task-slug>-audits/gold-check/
├── gold-check-report.json
├── visible-files.sha256
├── prompt-provenance.json
├── mount-audit.json
├── git-object-audit.json
├── isolation-audit.json
└── evidence.sha256
```

Only `gold-check-report.json` is required as the summary. Supporting evidence is
retained so that a PASS can be reproduced and independently reviewed.

Suggested report schema:

```json
{
  "schema_version": 1,
  "policy_version": "gold-check-v1",
  "task_id": "scrapy__scrapy__8073__pr_level__...",
  "pr_id": 8073,
  "status": "PASS",
  "checked_at_utc": "2026-09-14T00:00:00Z",
  "task_input_sha256": "...",
  "base_sha": "...",
  "checks": [
    {
      "id": "G01",
      "name": "input_identity",
      "status": "PASS",
      "finding_count": 0,
      "evidence": "prompt-provenance.json"
    }
  ],
  "finding_count": 0,
  "agent_call_permitted": true
}
```

Allowed report statuses:

- `PASS`: every required check passed; formal Agent calls are permitted;
- `FAIL`: at least one leak or boundary violation was found; Agent calls are
  prohibited until the task is rebuilt and re-audited;
- `ERROR`: the audit could not establish the boundary; fail closed and prohibit
  Agent calls;
- `NOT_RUN`: no audit has been performed; prohibit Agent calls.

The report must never store raw credential content or reproduce hidden gold
source. A failed finding should use a structure such as:

```json
{
  "check_id": "G03",
  "category": "MERGE_SHA_IN_AGENT_CONFIG",
  "agent_visible_path": "experiment-inputs/task.md",
  "line": 12,
  "matched_value_sha256": "...",
  "message": "A forbidden future revision identifier is Agent-visible."
}
```

## Enforcement

`run-agent.sh verify`, experiment `begin`, `all` and `parallel-all` must verify:

1. the report exists;
2. its task ID, PR ID, base SHA and task-input hash match the current task;
3. its policy version is supported;
4. its status is `PASS`;
5. `agent_call_permitted` is true;
6. the report and supporting evidence match the hashes locked in
   `deployment-lock.json`.

Changing an Agent-visible input, mount, repository, SDD initialization file,
runtime configuration or deployment definition invalidates the prior report and
requires the audit to run again.

## Operator record

For each task, record:

```text
Task ID:
PR ID:
Base SHA:
Gold-check policy version:
Task-input SHA256:
Report path:
Report SHA256:
Overall status:
Findings:
Reviewer:
Reviewed at UTC:
Decision:
```
