# Scrapy SDD Deployment Manifest

Task: `scrapy__scrapy__8073__test_only__600152fbc76dd5ba`  
PR: `8073`  
Agent: Codex CLI  
Manifest scope: fixed, isolated OpenSpec, Spec Kit and cc-sdd deployments

## Outcome

Three independent Scrapy experiment repositories start from the same commit and tree, run in the same fixed Agent image, and differ only in branch name and assigned SDD integration. Each experiment has a private writable HOME, tool installation, cache, tmpfs, workspace mount and internal network. No SDD package is installed in the common image.

```text
TASK_BASE_SHA 11079cb1c85b9e75a39a7269943c69d1a975d485
                         |
        +----------------+----------------+
        |                |                |
   OpenSpec repo     Spec Kit repo     cc-sdd repo
   private HOME      private HOME      private HOME
   private network   private network   private network
        |                |                |
   private proxy     private proxy     private proxy
        +----------------+----------------+
                         |
                  api.deepseek.com
```

## Final Directory Layout

```text
scrapy-sdd/
├── environments/
│   ├── agent-runtime/
│   │   └── codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/
│   ├── network/haproxy-3.2.23/
│   ├── scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/
│   │   └── baseline/scrapy/
│   └── sdd-tools/
│       ├── openspec-1.12.0_node-24.20.0_npm-11.19.0_linux-amd64/
│       ├── speckit-1.0.4_cb610277fdea_py-3.11.15_uv-0.12.10_linux-amd64/
│       └── cc-sdd-3.0.2_node-24.20.0_npm-11.19.0_linux-amd64/
├── tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/
│   ├── runs/
│   │   ├── openspec/scrapy/
│   │   ├── speckit/scrapy/
│   │   └── cc-sdd/scrapy/
│   ├── Dockerfile.agent
│   ├── compose.agent.yaml
│   ├── deployment-lock.json
│   ├── run-agent.sh
│   ├── apparmor-codex-bwrap-0.12.0.draft
│   └── seccomp-bubblewrap-0.12.0-moby-0.2.3-amd64.draft.json
└── Log/
    ├── scrapy-pr8073-test-only-600152fbc76dd5ba-deployment-manifest.md
    ├── scrapy-pr8073-test-only-600152fbc76dd5ba-sdd-deployment-steps-01-09.md
    ├── scrapy-pr8073-test-only-600152fbc76dd5ba-sdd-deployment-steps-10-18.md
    ├── scrapy-pr8073-test-only-600152fbc76dd5ba-sdd-deployment-steps-19-27.md
    └── scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/
```

The task-specific result files intentionally live under `Log/`, not under the task directory. Common downloaded build artifacts live under versioned `environments/` directories; they are not shared writable runtime state.

## Pinned Common Runtime

| Field | Fixed value |
|---|---|
| Agent image | `scrapy-sdd-agent:base-11079cb1c85b-codex-0.153.4-node-24.20.0-uv-0.12.10-official-bwrap-path-candidate` |
| Agent image ID | `sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9` |
| Python | `3.11.15` |
| Python dependency count/hash | `69` / `570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd` |
| Node.js | `24.20.0` |
| npm | `11.19.0` |
| uv | `0.12.10` |
| Codex CLI | `0.153.4` |
| Model profile | `deepseek-v4-pro` |
| Wire API | Responses |
| Reasoning effort | high |
| Agent resources | 4 CPU, 8 GiB memory, PID limit 512, 2 GiB private `/tmp` |
| Agent security | non-root `1007:1007`, read-only root, capabilities dropped, no-new-privileges, fixed Seccomp and AppArmor |
| Proxy | `haproxy:3.2.23-alpine3.24` at image ID `sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e` |

The three Agent services have identical common configuration hashes and resource limits. Each Agent can reach only its matching private HAProxy service; direct external IP connections are denied.

## Repository Identity

| Experiment | Branch | HEAD | Tree | Reachable commits | Remotes |
|---|---|---|---|---:|---:|
| OpenSpec | `experiment/openspec` | `11079cb1c85b9e75a39a7269943c69d1a975d485` | `0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2` | 1 | 0 |
| Spec Kit | `experiment/speckit` | `11079cb1c85b9e75a39a7269943c69d1a975d485` | `0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2` | 1 | 0 |
| cc-sdd | `experiment/cc-sdd` | `11079cb1c85b9e75a39a7269943c69d1a975d485` | `0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2` | 1 | 0 |

All tracked and staged diffs are empty. The untracked files listed below are the intentional, hash-locked SDD initialization output. `scrapy/**` and `tests/**` retain the shared base content hash.

## SDD Installations and Initialization

### OpenSpec

- Version: `1.12.0`
- Private installation: `/home/bench/tools/npm/node_modules/@fission-ai/openspec`
- Offline installation policy: `npm ci --offline --ignore-scripts --engine-strict`
- Initialization command:

  ```bash
  openspec init --tools codex
  ```

- Generated output: 10 files under `.agents/skills/` and `openspec/`
- Codex skills: 6
- Git result: 0 tracked/staged changes; 10 approved untracked files
- Fixed generated manifest SHA256: `70168a45d79ce6cd6d686c280476e3fbaf57179cc239cda700b49cac298c7141`

### Spec Kit

- Version: `1.0.4`
- Source commit: `cb610277fdea781fcfa83d20522c2db37c94068d`
- Private virtualenv: `/home/bench/tools/python/speckit-1.0.4`
- Offline installation policy: uv with `--offline --no-index --require-hashes --no-build`
- Initialization command:

  ```bash
  /home/bench/tools/python/speckit-1.0.4/bin/specify init \
    --here --force --non-interactive --script sh \
    --integration codex --integration-options=--skills
  ```

- Generated output: 30 files under `.agents/skills/` and `.specify/`
- Codex skills: 10
- Git result: 0 tracked/staged changes; 30 approved untracked files
- Fixed generated manifest SHA256: `404c4d70c695f254aa9bd372bf0f0b508ce53c6f3ab4f8f8446931eda6c0ce34`
- `.specify/specs/` is created when a concrete specification is authored, not by this initializer version.

### cc-sdd

- Version: `3.0.2`
- Source commit: `3795eb4274c07dedcf56c571b5c0a826736f23c8`
- Private installation: `/home/bench/tools/npm/node_modules/cc-sdd`
- Offline installation policy: `npm ci --offline --ignore-scripts --engine-strict --no-audit --no-fund`
- Initialization command:

  ```bash
  /opt/agent/node/bin/node /home/bench/tools/npm/node_modules/cc-sdd/dist/cli.js \
    --agent codex-skills --lang en --os linux \
    --overwrite force --profile full
  ```

- Generated output: 68 files under `.agents/`, `.codex/`, `.kiro/`, plus `AGENTS.md`
- Codex skills: 17
- Git result: 0 tracked/staged changes; 68 approved untracked files
- Fixed generated manifest SHA256: `3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca`
- `.kiro/specs/` is created by a concrete specification workflow, not initialization.

The launcher now validates each untracked path and file digest against these manifests before verification or a formal Agent run. Extra, missing or modified generated files cause startup to fail.

## Codex Recognition and Live Compatibility

- Offline Codex recognition registered exactly 6, 10 and 17 repository skills for OpenSpec, Spec Kit and cc-sdd.
- No group registered another group's SDD skills.
- The same minimal live-provider prompt completed in all three groups with exact output `BENCH_API_OK`.
- The live probe created no command, file-change, MCP or web event and left no persistent session.
- `deepseek-v4-pro` is an upstream alias. Endpoint and protocol compatibility are validated; immutable model-weight identity is not asserted.

## Symmetric Smoke Test

Command:

```bash
/usr/local/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke-step25 \
  tests/test_http_headers.py::test_basics
```

| Experiment | Exit | Result | stderr | Normalized stdout SHA256 |
|---|---:|---|---|---|
| OpenSpec | 0 | 1 passed | empty | `34423ae2823934c8bcf724d1b5ea6959c87621a972ef23277995f842d0018922` |
| Spec Kit | 0 | 1 passed | empty | `34423ae2823934c8bcf724d1b5ea6959c87621a972ef23277995f842d0018922` |
| cc-sdd | 0 | 1 passed | empty | `34423ae2823934c8bcf724d1b5ea6959c87621a972ef23277995f842d0018922` |

Each run used a copy inside that Agent's private tmpfs because Scrapy generates temporary TLS keys below `tests/keys`. All copies and pytest basetemp directories were removed.

## Starting and Using the Environments

Run these commands from the task directory. The placeholder must resolve to a non-symlink regular file outside the benchmark tree, owned by the invoking user and inaccessible to group/other users. Do not write the real path into Git, logs or manifests.

```bash
cd /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba
export DEEPSEEK_API_KEY_FILE=<ABSOLUTE_SECRET_PATH_OUTSIDE_BENCHMARK>
```

If the task-specific AppArmor profiles are not loaded after a reboot, load the pinned source first:

```bash
sudo /usr/sbin/apparmor_parser -r -T -K \
  --abort-on-error --warn=all --Werror \
  ./apparmor-codex-bwrap-0.12.0.draft
```

Start a fresh deployment:

```bash
./run-agent.sh preflight
./run-agent.sh up
./run-agent.sh verify
./run-agent.sh status
```

For the currently running deployment, use only the last two commands. `preflight` and `up` intentionally reject an already-existing Compose project.

Run one experiment at a time with the same prompt file and unique run IDs:

```bash
./run-agent.sh run openspec /absolute/path/to/prompt.txt <RUN_ID>-openspec
./run-agent.sh run speckit  /absolute/path/to/prompt.txt <RUN_ID>-speckit
./run-agent.sh run cc-sdd   /absolute/path/to/prompt.txt <RUN_ID>-cc-sdd
```

The launcher enforces one task-wide lock, the fixed profile, strict configuration, ephemeral sessions, JSONL output, a 2,700-second timeout and sequential execution. Output is written below the task's `Log/.../agent-runs/` audit directory.

## Evidence Index

- Baseline: `Log/.../baseline-manifest.md`
- OpenSpec install/init/audit: Steps 10–13 audit directories
- Spec Kit install/init/audit: Steps 14–17 audit directories
- cc-sdd install/init/audit: Steps 18–21 audit directories
- Symmetric comparison: Step 22
- Codex recognition: Step 23
- Live compatibility: Step 24
- Post-live reproducibility: Step 25
- Formal startup entry: Step 26
- Machine-readable source of truth: `tasks/.../deployment-lock.json`

No evidence file contains credential content or the real host credential path.
