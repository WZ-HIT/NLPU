# Scrapy PR 8073 SDD Experiment Operation Workflow

This document records the current experiment workflow, the meaning of each
operator command, the information boundary between Agent input and evaluation,
and the verified operator shortcuts implemented in S01-S07.

## Experiment principle

The experiment is **target-blind** and **gold-blind** while an Agent is running.
An Agent may receive the original task or problem description, repository source,
and the SDD integration assigned to its own isolated repository. It must infer the
relevant test location and required change through its own investigation.

The following information is evaluation-only and must never be placed in the
Agent prompt, an Agent-visible filename, an Agent-visible configuration field, or
an Agent-accessible directory:

- the gold patch or gold test;
- files and test cases identified by inspecting the merged pull request;
- a human-derived target file or target test name;
- future commits, pull-request patches, or reference answers.

The browser result viewer may show prompt and gold data side by side because it
is a host-side, post-run human evaluation tool. That information must not flow
back into any Agent container.

### Enforced input boundary

S01 replaced the target-revealing filename
`pr8073-test-invalid-credentials.md` with the neutral `pr8073-task.md`. Its task
statement is derived only from the PR natural-language description available at
experiment start. It names the reported `DirtyReactorAggregateError` problem but
does not disclose a target file, target test, old test body, merge result, or gold
patch. The Agent must locate and assess relevant tests in the base repository.

Manual and dataset inputs now use the same boundary. Dataset mode reads only the
matching record's top-level `sample_id`, `pr_id`, and `nl_description`; it no
longer forwards the generated `prompt`, which contains `old_test_file`, target
name, and old test code. The input policy also matches the current
`output-only-manual-review` finish policy: Agents do not run tests.

## Current end-to-end workflow

```text
verify checkpoint
       |
restore identical pre-experiment state
       |
prepare one shared, target-blind task description
       |
create and validate experiment JSON
       |
run OpenSpec -> Spec Kit -> cc-sdd
       |
capture each Agent output, SDD artifacts, Git diff, and failure evidence
       |
finish without running tests
       |
inspect all results and hidden gold in the host-side browser viewer
       |
record human review decision
```

## Current operator commands

### 1. Verify the rollback checkpoint

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/checkpoints/\
pre-experiment-pr8073-20260912T050742Z
./verify.sh
```

This is read-only. It checks checkpoint metadata, payload hashes, repository
archives, independent Agent HOME archives, and pinned Docker image archives.

### 2. Restore the common starting state

```bash
./restore.sh --yes
```

This verifies the checkpoint, creates a recovery backup of the displaced state,
restores all three repositories and three independent HOME volumes, starts the
pinned deployment, and reruns runtime checks. It does not archive the API key.

### 3. Prepare the shared task description

The current experiment uses a manual Markdown file selected by the `input` object
in the experiment JSON. The same resolved bytes are supplied to all three SDD
variants. Only the SDD workflow wrapper differs.

For a valid target-blind experiment, this file must use a neutral filename and
contain no target inferred from the merge, gold data, or future history.

### 4. Create and validate an experiment configuration

The JSON binds the run to one experiment ID, task ID, sample ID, PR ID, base SHA,
shared input, execution order, and no-intervention workflow policy.

Create a configuration from the canonical target-blind template using a short
alias, then validate it using the same alias:

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/\
scrapy__scrapy__8073__test_only__600152fbc76dd5ba
./run-experiment.sh prepare pr8073-006
./run-experiment.sh validate-config pr8073-006
```

Validation rejects identity mismatches, invalid paths, malformed execution order,
and unsupported workflow settings before a model call is made.

### 5. Run all three SDD variants

```bash
./run-experiment.sh all pr8073-006
```

The launcher follows the configured `execution_order`, currently OpenSpec, Spec
Kit, then cc-sdd. Each variant gets exactly one attempt per phase and no human
intervention between phases. A variant failure is recorded but does not prevent
later variants from running. Experiment-wide failures such as an invalid config,
missing secret, active lock, or result-directory collision stop the entire run.

The phase sequences are:

- OpenSpec: `propose`, then `apply`;
- Spec Kit: `specify`, `plan`, `tasks`, then `implement`;
- cc-sdd: `spec`, then `implement`.

The current finish policy is output-only manual review. `finish` captures state
and does not execute `tests/`.

### 6. Optional manual phase control

These commands expose the same state machine for diagnosis or controlled dry
work. They are not needed for a normal `all` run.

```bash
./run-experiment.sh begin openspec EXPERIMENT.json
./run-experiment.sh phase openspec propose EXPERIMENT.json
./run-experiment.sh phase openspec apply EXPERIMENT.json
./run-experiment.sh finish openspec EXPERIMENT.json
./run-experiment.sh status openspec EXPERIMENT.json
```

Equivalent phase names apply to Spec Kit and cc-sdd. `probe` validates multistage
state transitions without asking the Agent to modify source code.

### 7. Inspect results

```bash
sdd-results
```

The browser dashboard discovers available experiment output globally. Missing
artifacts are omitted instead of crashing the viewer. It provides three SDD tabs,
changed-file navigation, colored unified diffs, collapsible specifications and
Agent output, failure phase/reason, prompt/gold comparison with file locations,
and human-review status.

Run evidence is stored under:

```text
Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/
  experiments/<experiment-id>/
```

Each variant directory contains the available phase logs, state, generated SDD
artifacts, Git diff, failure evidence, and finish evidence. The experiment-level
summary records execution order and per-variant outcome.

## Implemented usability improvements

### Persistent API-key path

Use the already protected default file:

```text
/home/wangzuohit/.config/sdd-bench/deepseek-api-key
```

The launch and restore scripts use this as their default when
`DEEPSEEK_API_KEY_FILE` is unset. The environment variable remains an explicit
override for a different provider credential file. This stores neither a secret
nor a secret path in experiment JSON and removes repeated shell setup.

Normal commands require no environment prefix:

```bash
./restore.sh --yes
./run-experiment.sh all EXPERIMENT.json
```

### Short experiment alias

The `prepare` command accepts a concise run alias:

```bash
./run-experiment.sh prepare pr8073-006
```

The launcher validates the PR number against the fixed task identity and derives
the full ID `pr8073-comparison-006`. It creates the JSON from the canonical
target-blind `experiment.json`, preserves the fixed task/sample/base identities
and execution order, validates the result, refuses config/result overwrites, and
prints the final path. It does not read merge content or inject gold-derived
target information.

The same alias should then resolve in normal commands:

```bash
./run-experiment.sh all pr8073-006
```

Configuration generation and execution remain separate deliberate operations so
the operator can inspect the generated JSON before spending a model run.

## S01-S07 implementation and verification record

- **S01 — PASS:** created neutral `experiment-inputs/pr8073-task.md` and removed
  the target-revealing input filename.
- **S02 — PASS:** updated `experiment.json` and comparison 005 to reference the
  neutral input. Generated comparison 006 inherits the same path.
- **S03 — PASS:** `run-experiment.sh` defaults to the protected external key file
  and still accepts `DEEPSEEK_API_KEY_FILE` as an override.
- **S04 — PASS:** added `prepare pr8073-NNN` plus alias resolution for validate,
  all, begin, phase, finish, status, and probe. Dataset resolution was restricted
  to the target-blind natural-language description.
- **S05 — PASS:** `restore.sh` uses the same default key path while retaining the
  mandatory `--yes` confirmation.
- **S06 — PASS:** both shell scripts passed `bash -n`; default configuration and
  `pr8073-006` passed validation; comparison 006 was generated; repeated 006 was
  rejected; `pr9999-007` was rejected; the key file was mode 600, owner UID 1007,
  and non-empty; default-key preflight passed the credential/runtime checks and
  stopped at the expected dirty-repository guard; no 006 result directory was
  created; restore without `--yes` remained a safe refusal.
- **S07 — PASS:** this document was updated with the implemented behavior and
  restart procedure.

At S06, all repository HEADs still matched
`11079cb1c85b9e75a39a7269943c69d1a975d485`, but the repositories retained
previous experiment working-tree changes. OpenSpec modified
`tests/test_extension_remote_control.py`; Spec Kit modified
`tests/test_utils_remote_control.py`; cc-sdd had no tracked test modification.
Each repository also retained its own expected untracked SDD initialization
files. A checkpoint restore is therefore mandatory before comparison 006.

## Simplified restart routine

To start comparison 006 from the common pre-experiment state:

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/checkpoints/\
pre-experiment-pr8073-20260912T050742Z
./restore.sh --yes

cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/\
scrapy__scrapy__8073__test_only__600152fbc76dd5ba
./run-experiment.sh validate-config pr8073-006
./run-experiment.sh all pr8073-006

sdd-results
```

Comparison 006 was already prepared during S06, so it must not be prepared a
second time. For a later unused number, create the configuration once before
running it, for example:

```bash
./run-experiment.sh prepare pr8073-007
./run-experiment.sh all pr8073-007
```

This routine preserves the scientific controls: identical restored state, one
shared target-blind input, fixed execution order, no retries, no inter-phase human
intervention, independent repositories/HOMEs/caches, and post-run-only access to
gold information.

## E01 bounded-research revision after comparison 006

Comparison 006 established that OpenSpec completed, while Spec Kit failed in
`plan` and cc-sdd failed in `spec`. Both failures were recorded as
`shared rollout token budget exhausted`; neither implementation phase ran, so
the absence of test-file changes was an orchestration consequence rather than an
implementation decision.

The rollout ceiling remains unchanged at 100,000 tokens. E01 instead introduced
a common bounded-research contract:

- initial planning phases may use at most 12 repository-investigation commands;
- downstream planning/apply phases may use at most 6;
- Spec Kit implementation may use at most 4 implementation-only lookups;
- each investigation command must be focused and capped at 200 output lines;
- equivalent searches, complete repository enumeration, full CI workflow dumps,
  and whole third-party source-tree inspection are prohibited;
- downstream phases reuse predecessor artifacts as authoritative scope;
- every phase writes mandatory artifacts early and returns immediately when its
  completion condition is satisfied;
- cc-sdd `spec` stops when `spec.json` reaches
  `ready_for_implementation=true`.

These controls do not disclose a target file or test. Initial discovery still
starts from an exact marker search in the restored base repository.

At the operator's request, the common DeepSeek profile was changed from high to
medium reasoning while keeping the model, provider, image, Python, Node.js,
resources, permissions, and rollout ceiling fixed. The deployed hashes are:

```text
common config   b1c8c6d896b4c7e56adb864487f6d667cd682e21ccf1d0989c5646abc981851f
medium profile  50eb14fd71cd12ddcea733664ea1acc4233ab3d75433869bd0ab438e6d317080
model catalog   ff83686fe30186610d2f14eb726af1b21881eb02a53d6acf05b30a16f7834e55
```

All three live Agent containers exposed those exact hashes and independently
parsed `reasoning=medium`, `rollout=100000`, and `catalog_default=medium`.
`run-agent.sh verify` passed, Codex 0.153.4 resolved the supported levels as
`low,medium,high,max`, and a strict-config loopback probe found no configuration
or medium-reasoning error before its intentional outer timeout. All eight phase
prompts were rendered without a model call and contained exactly one bounded
research contract with the expected 12/6/4 policy class.

The original checkpoint keeps its initial repository and HOME payloads, but its
deployment-configuration payload was deliberately revised on 2026-09-14 to the
Pro/medium state. Its verifier checks the archived effort and configuration
hashes before restore. It remains available as the independent Pro/medium
rollback point.

Configuration `pr8073-comparison-007` was prepared and validated after the
revision. No Agent or formal comparison 007 model call was started during E01.

## M01-M10 migration to DeepSeek-V4.1-Flash/high

DeepSeek's 2026-09-10 API documentation identifies `deepseek-flash` as the API
model ID for DeepSeek-V4.1-Flash. A separate `deepseek-flash` Codex profile and
single-entry model catalog were added from the official Flash metadata. The
catalog preserves the official `low`, `high`, and `max` levels; both its default
and the profile are fixed to `high`. The initial local profile name containing a
dot was rejected by Codex 0.153.4 before any network access, so all local names
were normalized to the valid plain name `deepseek-flash`.

The Compose definition and both launchers now mount and hash-check the same
Flash files for OpenSpec, Spec Kit, and cc-sdd. The unchanged Agent image,
provider endpoint, Responses protocol, secret boundary, Python/Node versions,
resource limits, networks, repositories, private HOME volumes, and 100,000-token
rollout ceiling preserve the other experimental controls.

```text
profile SHA256   2e594da8abb241ef9c54cc376956a198371d305db4252d21341bd8d4fa1dd029
catalog SHA256   4240127a851f7582bb4f92b9fe3b258f18393d560446e84430e5f90f473db9a1
Compose SHA256   11789f438228df24976e397a6b446edbe51736ba6a9f3288718bdcf40b4f2904
rendered Compose 77a7414b9be70c21de92838a17b91701a3fb0ee3860d650759761d929e985714
```

All six containers were recreated without deleting repositories or named HOME
volumes. `run-agent.sh verify` passed; all three Agent containers independently
reported `model=deepseek-flash`, `effort=high`, and identical hashes. The Codex
model resolver exposed the official Flash reasoning levels. A strict-config
probe entered a turn against forced loopback endpoint `127.0.0.1:9` and ended at
the intentional five-second timeout, proving local configuration acceptance
without an external model request.

A separate rollback point was created and fully verified:

```text
pre-experiment-pr8073-flash-high-20260914T064502Z
checkpoint_verification=PASS
```

Unchanged large repository, HOME, and image payloads use hard links to avoid
physical duplication; the Flash deployment payload, metadata, verifier, and
restore logic are independent. The earlier Pro/medium checkpoint remains
available. No formal comparison or live Flash inference was started during this
migration.

## P01-P06 parallel comparison mode

### P01-P02 — Design and isolation review

The experiment launcher now provides two explicit comparison modes. `all`
retains sequential execution. `parallel-all` launches the three SDD workers in
the configured `execution_order`, waits until every successful preflight reaches
a shared start barrier, and then releases those workers together. In parallel
mode, `execution_order` defines deterministic launch and report order; it does
not impose predecessor completion.

Parallelism does not merge runtime state. OpenSpec, Spec Kit, and cc-sdd still
use distinct Scrapy repositories, Agent containers, HOME volumes, caches,
private networks, phase directories, console logs, and result directories. The
parent launcher holds the existing task-wide non-blocking `flock` for the whole
comparison, preventing a second formal launcher from entering concurrently.

### P03-P04 — Failure and evidence contract

There are no automatic retries and no opportunity for inter-phase human input.
A worker failure is captured in that variant's `failure.json` and
`parallel-all.console.log`; it does not cancel either remaining worker. The
launcher waits for all three workers, then returns zero only when all completed
under the output-only manual-review policy. Any variant failure produces a
non-zero aggregate exit after the other workers have finished.

The experiment-level `all-summary.json` records:

- `execution_mode: parallel`;
- `start_barrier_status: PASS` or `DEGRADED`;
- the configured `execution_order`;
- one final status record per SDD.

A `DEGRADED` barrier means at least one worker failed or timed out during
preflight; ready workers are still released so that one broken environment does
not erase the other independent observations. All result collisions are checked
before any worker is launched, so existing experiment evidence is never
overwritten.

The deployment lock pins the experiment-launcher SHA-256 and documents these
semantics. The implementation adds `sleep` and `rmdir` to fail-closed runtime
command discovery.

### P05-P06 — Validation and operation

Validation made no model or provider request. Bash parsing passed, configuration
`pr8073-comparison-007` passed the normal validator, and a three-worker `/tmp`
probe deliberately failed Spec Kit with exit code 23. OpenSpec and cc-sdd still
finished, the aggregate exit was 1, all three console logs were present, the
start barrier passed, and the measured worker start spread was 7.679 ms.

To prepare and run a new parallel comparison:

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/\
scrapy__scrapy__8073__test_only__600152fbc76dd5ba
./run-experiment.sh prepare pr8073-008
./run-experiment.sh validate-config pr8073-008
./run-experiment.sh parallel-all pr8073-008
```

Comparison 007 already has a complete sequential result set and must not be
reused. Inspect it as historical evidence, or choose a new unused ID after
restoring the repositories to the intended checkpoint.

Results appear under:

```text
Log/scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/
  experiments/<experiment-id>/
    all-summary.json
    openspec/parallel-all.console.log
    speckit/parallel-all.console.log
    cc-sdd/parallel-all.console.log
```

The existing Flash/high checkpoint was created before `parallel-all` and remains
an immutable historical snapshot. Restoring that checkpoint restores its
archived pre-parallel launcher. Create a new post-change checkpoint before a
formal parallel experiment if rollback must preserve this new command itself.

During P06 documentation, an unsafe shell-quoting attempt accidentally invoked
`prepare` and `parallel-all` for comparison 008. All three workers failed closed
in preflight because their repositories already contained tracked test changes;
no phase, Codex, SDD, or model execution began. The accidentally created config
and failure-only directory were removed from the benchmark tree and retained at
`/tmp/sdd-accidental-pr8073-008.zPAMbE` for recoverability. Comparison 007 and
all earlier evidence were untouched.
