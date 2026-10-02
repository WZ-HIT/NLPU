# Scrapy SDD Benchmark Environment

This directory contains the reproducible deployment definition and audit trail
for comparing OpenSpec, Spec Kit and cc-sdd with Codex CLI on Scrapy test-case
tasks.

The completed reference task is
`scrapy__scrapy__8073__test_only__600152fbc76dd5ba`. Its deployment lock reports
`deployment_ready` and `formal_run_ready=true`.

## Experiment workflow

Maintain one `batch/experiments/*.json` file for the PRs, methods, stages,
Update modes and evaluation plan. Use `bin/sdd-experiment` from this directory:

```bash
bin/sdd-experiment prepare batch/experiments/scrapy-3pr-both-pilot-v1.json
bin/sdd-experiment run batch/experiments/scrapy-3pr-both-pilot-v1.json
bin/sdd-experiment run batch/experiments/scrapy-3pr-both-pilot-v1.json --stage detect --execute
bin/sdd-experiment run batch/experiments/scrapy-3pr-both-pilot-v1.json --stage update --execute
bin/sdd-experiment evaluate batch/experiments/scrapy-3pr-both-pilot-v1.json --kind both
bin/sdd-experiment results list
```

`prepare` freezes `batch/prepared/<experiment-id>/prepared-manifest.json` and
can resume an interrupted preparation. The default `run` action is read-only
`inspect`; `probe` records a dry run. `detect`, `update` and `all` may call a
paid Agent, so each requires `--execute`. `evaluate` runs on the host after
sealed evidence exists; `compliance` verifies run evidence and `quality` uses
the pinned host plan and hidden gold. Detect-only configs without a host plan
support `--kind compliance`. `results list` and `results report` include the
historical batches. See [the migration and acceptance notes](docs/refactor/experiment-entry.md)
for options and compatibility.

## Quick Non-mutating Probe

Run from the task directory. Keep the real credential path outside this Git
tree and never put it in a prompt, log, manifest or command committed to Git.

```bash
cd tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba
export DEEPSEEK_API_KEY_FILE=<ABSOLUTE_SECRET_PATH_OUTSIDE_BENCHMARK>

printf '%s\n' \
  'Reply with exactly SDD_READY. Do not use tools and do not modify files.' \
  > /tmp/sdd-ready-prompt.txt

./run-agent.sh verify
./run-agent.sh run openspec /tmp/sdd-ready-prompt.txt probe-openspec
./run-agent.sh run speckit  /tmp/sdd-ready-prompt.txt probe-speckit
./run-agent.sh run cc-sdd   /tmp/sdd-ready-prompt.txt probe-cc-sdd
```

The three runs are intentionally sequential and use distinct run IDs. JSONL
and stderr evidence is written below `Log/.../agent-runs/`. A prompt that asks
the Agent to edit files begins an actual experiment and changes that group's
workspace; use a fresh task clone for another fair run.

## Provider and Model Bundles

The current formal bundle is fixed to `deepseek-v4-pro`. It is composed of:

- common Codex policy in `environments/agent-runtime/.../config-templates/config.toml`;
- a provider profile such as `deepseek-v4-pro.config.toml`;
- that profile's `model-catalogs/<profile>/models.json`;
- a provider-specific egress proxy configuration;
- Compose mounts, DNS mapping and Docker secret declaration;
- fixed profile names and expected SHA256 values in `run-agent.sh`;
- the resulting values and evidence hashes in `deployment-lock.json`.

Do not change only `model = ...` or bypass the launcher with an arbitrary `-m`
for a formal comparison. That would leave the catalog, endpoint, authentication,
egress policy and reproducibility record inconsistent.

To add a replaceable provider/model safely:

1. Create a new named profile and matching model catalog without editing the
   completed DeepSeek bundle.
2. Create the provider-specific read-only secret and fixed egress configuration.
3. Generate a new Compose/launcher pair whose three groups use identical bytes.
4. Replace every expected configuration hash and record a new deployment lock.
5. Recreate all three services together, then repeat offline parsing, sandbox,
   credential, egress, recognition, live compatibility and symmetric smoke
   validations.

The Codex configuration reference is the authoritative source for supported
profile and provider fields:
<https://developers.openai.com/codex/config-reference/>.

## Versioned and Local-only Content

Git stores deployment source, dependency locks, retained SDD artifacts, hashes,
manifests and audit evidence. Nested Scrapy Git worktrees, common runtime release
archives and the OCI image layout remain server-local. They are reconstructible
from the fixed commits, source URLs and SHA256 values in the lock and logs and
are excluded to avoid invalid embedded repositories and hundreds of megabytes
of duplicate binary data.

Start with the final documents:

- `Log/scrapy-pr8073-test-only-600152fbc76dd5ba-deployment-manifest.md`
- `tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json`
- `Log/scrapy-pr8073-test-only-600152fbc76dd5ba-sdd-deployment-steps-28-28.md`

## 独立重跑 30 PR Detect

配置和逐步命令见 [独立 Detect 轮次](docs/refactor/isolated-detect-rounds.md)。通过配置中的 `prs` 选择 PR，通过 `--round` 创建或续跑独立轮次；只有 `run --stage detect --execute` 会调用 Agent。
