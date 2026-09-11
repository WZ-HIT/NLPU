# Scrapy SDD Deployment — Steps 01–09

Task: `scrapy__scrapy__8073__test_only__600152fbc76dd5ba` · PR 8073  
Progress: **09/28 complete** · The common Agent inputs, image, sandbox,
runtime policy, launcher and final six-service deployment are verified. The
next phase installs and initializes one fixed SDD tool per isolated Agent.

## Logging Convention

Keep one English Markdown working log per nine main steps: 01–09, 10–18,
19–27, then 28–36 if needed. Append only the purpose, important result and
remaining caveat after each completed step. Substeps belong to their parent step.
Keep full commands, hashes and machine-readable evidence separately and link them.
The earlier baseline-preparation logs are a different task and remain unchanged.

## Step 01 — Check the Starting Environment

Verified the existing baseline, three independent Scrapy clones, Docker containers
and available resources. All clones started at the same commit with clean Git
worktrees; each container had its own repository mount and HOME volume.
This step inspected the baseline rather than creating it again.

## Step 02 — Choose Fixed Tool Versions

Reviewed official project documentation and selected Codex CLI as the common
Agent. Fixed OpenSpec **1.12.0**, Spec Kit **1.0.4**, cc-sdd **3.0.2**, Codex
**0.153.4**, Node **24.20.0**, npm **11.19.0** and uv **0.12.10**.
These are experiment pins, not a claim that all three SDD projects offer LTS releases.

## Step 03 — Write the Deployment Lock

Created [deployment-lock.json](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json)
to record versions, source identity, resource targets and isolation requirements.
Unchosen model/provider/auth/network settings were left explicitly pending.
The file is updated with verified artifacts and image identity as work progresses.

## Step 04 — Prepare and Verify Reproducible Inputs

Created [Dockerfile.agent](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/Dockerfile.agent).
Substeps 04a–04j fixed source commits and dependencies, verified installation
archives, and moved reusable inputs into `environments/` rather than per-task storage.

- OpenSpec and cc-sdd: npm locks plus 72 verified tarballs in total.
- Spec Kit: 14 runtime dependencies, 6 build dependencies, and a locally built wheel;
  two consecutive offline builds produced identical wheel bytes.
- All three tools passed offline installation, version and help checks in separate
  disposable containers. Scrapy's 69 test dependencies and their hash stayed unchanged.

These were preparation checks, not installation into the experiment services.
Raw records: [OpenSpec](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/offline-install-04i/openspec.json),
[cc-sdd](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/offline-install-04i/cc-sdd.json),
[Spec Kit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/offline-install-04i/speckit.json).

## Step 05 — Build the Common Agent Image

Built and runtime-verified one image containing the baseline Python environment
and common Agent tools, **without any SDD tool**. Python is **3.11.15**; the
original Scrapy dependency set and baseline filesystem layers are preserved.

```text
sha256:4e31d1759723319461745913e81fd37c0af4ad7343ef1b7ac80d6f085fce5330
```

This was the first common image. Step 06 later produced the verified deployment
candidate with the required same-release Codex sandbox binary.

The first build hit a registry-mirror 401. Exporting the same baseline to a verified
local OCI layout and mapping its original digest resolved the issue without changing
the Dockerfile or base image. Rebuilds on this server must use the recorded OCI mapping,
not just the abbreviated command in the Dockerfile header.

Evidence: [successful command and summary](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/common-agent-image-05/build-summary.json),
[build log](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/common-agent-image-05/build-local-oci.log),
[runtime checks](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/common-agent-image-05/runtime-verification.json).

## Step 06 — Prepare a Swappable Model Configuration

**06a–06d:** Created a provider-independent policy template, retained the official
DeepSeek Pro catalog entry without rewriting its embedded prompts, and added a
`deepseek-v4-pro` Profile with explicit `high` reasoning. Recorded all three file
hashes in the deployment lock. Credentials are referenced by `DEEPSEEK_API_KEY`,
never embedded. A future provider switch selects another Profile and starts a
fresh experiment; it does not require reinstalling the common tools.

<details>
<summary><strong>Historical 06e–06j diagnosis and repair plan</strong></summary>

**06e:** Rechecked the fixed image in a disposable, network-disabled container.
Profile rendering, configuration hashes and the original Python dependency hash
passed. All three repositories retained the same base HEAD, one reachable commit,
no remotes and clean worktrees. However, `codex sandbox linux -- /bin/true` exited
**101**: neither system `bwrap` nor bundled `codex-resources/bwrap` was found.
Earlier fallback messages were not proof that the resource existed. Sandbox write
and network enforcement could not be tested. No security settings were relaxed.

**06f:** Consolidated these findings here; no additional per-step Markdown logs.
Evidence: [offline configuration and sandbox audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/agent-runtime-config-and-sandbox-06e.json)
contains the complete probe command, inline script, hashes and failure output.

**06g–06i:** The verified Codex archive contains only the executable; the image
has neither a system nor bundled `bwrap`. This is a missing runtime dependency,
not a failed archive extraction. Docker 29.7.1 embeds `moby/profiles/seccomp v0.2.3`:
its [unshare allow rule](https://github.com/moby/profiles/blob/seccomp/v0.2.3/seccomp/default_linux.go)
requires `CAP_SYS_ADMIN`; the capability-free probe does not qualify, so the
default `EPERM` action explains its failure. Ubuntu enables user namespaces but
also restricts them through AppArmor. Supplied denial logs concern
`cursorsandbox`, not a correlated experiment probe. AppArmor may remain a second
blocker; its role is not proven. The initial image checks covered versions and
dependencies but missed an actual sandbox startup test.

**06j:** Recorded the following repair plan only. No repair or security change
has been authorized by this planning step.

## Repair Plan — Separate Approval for Every Step

| Step | Action | Maximum persistent file change |
| --- | --- | --- |
| 06k | Resolve Debian 13 amd64 bubblewrap and required dependencies; pin versions, URLs and verified hashes. | One sandbox artifact manifest under shared `environments/`. |
| 06l-1…N | Acquire each approved artifact and verify its manifest hash. | One artifact per substep. |
| 06m | Add the pinned runtime dependencies and build-time presence checks. | Task `Dockerfile.agent` only. |
| 06n | Build a separately tagged candidate image; retain the old image and original baseline. | One build evidence JSON; candidate Docker image. |
| 06o | Draft a version-pinned, least-privilege seccomp profile for reviewed sandbox operations. Do not activate it. | One experiment-specific seccomp JSON. |
| 06p | After explicit approval of the policy delta, test only a disposable offline container: sandbox startup, allowed writes, denied writes and denied network access. | One verification JSON. |
| Conditional | If AppArmor blocks the test, diagnose first; draft one scoped profile in a separately approved step. Host loading requires separate administrator approval. | One draft profile; no automatic host changes. |
| 06q | Once sandbox tests pass, verify Python/dependency equality and repeat the baseline smoke target on the candidate. | One verification JSON. |
| 06r | Record verified artifact, policy and image identities plus outstanding runtime choices. | Existing `deployment-lock.json` only. |
| 06s | Append key outcomes and evidence links here. | This existing English working log only. |

Keep non-root execution and existing isolation controls. No `--privileged`, broad
`CAP_SYS_ADMIN`, `seccomp=unconfined`, AppArmor disablement or global sysctl changes.
Policy drafts are proposals, not proof of sufficiency; stop on an unexpected
denial and request approval for any expanded scope. All three eventual services
must use the same verified candidate image and policy bytes, with independent
repositories, HOME and caches. Do not replace existing experiment containers yet.

</details>

### 06k–06r Outcome

Debian Bubblewrap 0.12.0 was a valid package, but its executable did not match
the digest embedded in Codex 0.153.4. The final image therefore uses the official
same-release OpenAI static bwrap binary, verified at archive and executable level.
The verified common deployment candidate is:

```text
sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9
```

Task-scoped Seccomp and AppArmor policies were added without using a privileged
container, broad `CAP_SYS_ADMIN`, unconfined Seccomp, global sysctl changes or
AppArmor disablement. After the operator loaded the profiles, the final offline
probe passed sandbox startup, workspace write, outside-write denial and inner
network denial. The inner process ran as UID 1007 with zero capabilities,
`NoNewPrivs=1`, enforcing AppArmor and two Seccomp filters.

The validated sandbox command prefix is:

```text
codex --profile deepseek-v4-pro sandbox \
  -P :workspace -C /workspace -- <COMMAND>
```

The candidate retains exactly 69 Scrapy test packages with normalized hash
`570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd`.
`pip check` passed, and no SDD command or package is installed. The three clean,
remote-free repositories ran the same smoke target from independent tmpfs copies:

| Repository | Branch | Result |
| --- | --- | --- |
| OpenSpec | `experiment/openspec` | `1 passed in 0.17s` |
| Spec Kit | `experiment/speckit` | `1 passed in 0.17s` |
| cc-sdd | `experiment/cc-sdd` | `1 passed in 0.17s` |

The source mounts remained read-only. Tmpfs copies were necessary because Scrapy's
`conftest.py` generates ephemeral TLS keys below `tests/keys/`. Step 06r updated
the deployment lock with the final image, artifact, policy and evidence hashes;
it intentionally keeps `formal_run_ready=false`.

Key evidence:

- [runtime configuration preflight](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/agent-runtime-config-and-sandbox-06e.json)
- [official bwrap artifact manifest](../environments/agent-runtime/codex-0.153.4_node-24.20.0_uv-0.12.10_linux-amd64/artifacts/sandbox/artifact-manifest.json)
- [final sandbox validation](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/agent-sandbox-bubblewrap-final-06p.json)
- [dependency and three-way smoke validation](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/common-agent-dependencies-and-smoke-06q.json)
- [current deployment lock](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json)

No model request was made, no experiment container was replaced, and no SDD tool
was installed or initialized during Steps 01–06.

## Step 07 — Define the Isolated Deployment Runtime

Hardened the common Codex policy, moved provider authentication to a fixed
command-backed Docker secret, and verified that sandboxed commands cannot read
the secret or inspect the parent process. Fixed a HAProxy **3.2.23** TLS
passthrough image and configuration so each Agent can reach only its own proxy,
while generated shell commands remain offline.

Selected a common 100,000-unit rollout budget with equal prefill and sampling
weights and remaining-budget reminders at 25,000 and 10,000. Codex 0.153.4
accepts this version-specific configuration but labels the feature under
development, so it is tracking rather than a guaranteed billing cap. A
2,700-second TERM timeout with a 30-second kill grace is selected for enforcement
by the Step 08 launcher; cost is recorded from `codex exec --json` usage after
each run.

Created [compose.agent.yaml](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.agent.yaml)
without changing the original baseline Compose. It defines three identical Agent
services and three pinned proxies. Every Agent has one distinct repository, HOME
volume and internal network; tools and caches are private paths inside that HOME.
Only its proxy joins a separate uplink. Static private addresses plus Agent-only
host mappings preserve the
provider TLS name without making a proxy resolve its backend to itself.

The final Compose passed schema, image, resource, security, mount, environment,
network and missing-secret fail-closed assertions. No deployment container,
network or volume was created, and all three repositories stayed clean and
remote-free. Formal runtime behavior remains a Step 09 validation.

```text
deployment Compose SHA-256: e4740873b943a2707a845a15f68d30c56436e77b2769e9fc5780821b34e50e1c
common config SHA-256:       b1c8c6d896b4c7e56adb864487f6d667cd682e21ccf1d0989c5646abc981851f
Agent image ID:              sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9
HAProxy image ID:            sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e
```

Evidence: [deployment Compose validation](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/deployment-compose-07o.json)
and the [current deployment lock](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json).

## Step 08 — Create the Uniform Agent Launcher

Created the executable [run-agent.sh](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/run-agent.sh)
as the only supported formal-run entry point. It maps each variant to exactly one
Agent and proxy, verifies pinned file and image hashes, rejects an unsafe secret
file, checks the three clean remote-free baseline repositories before deployment,
and detects Docker subnet overlap.

Every model run uses the fixed `deepseek-v4-pro` profile, strict configuration,
an ephemeral session and JSONL output. A task-wide non-blocking file lock enforces
sequential execution. GNU `timeout` runs inside the Agent container, sends TERM
after 2,700 seconds and KILL 30 seconds later. The launcher accepts no arbitrary
Codex overrides and stores JSONL and stderr outside all three repositories with
an owner-only umask.

Static validation and a complete preflight with a temporary fake secret passed.
Failure tests rejected a missing secret, missing run arguments, an unknown
variant and an unexpected argument. The `up` guard also rejected creation while
the old baseline containers remained running. No deployment object or SDD state
was created.

```text
launcher SHA-256: f3bd12b5225d1d1c529ef2df3bce58a837f41fb7587300a5c84f6cced41460a7
timeout policy:    TERM at 2700 seconds; KILL after another 30 seconds
execution order:   one task-wide flock; no parallel formal Agent runs
```

Evidence: [uniform launcher validation](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/unified-agent-launcher-08c.json)
and the [current deployment lock](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json).

The Step 07 and Step 08 evidence records preserve the initial static design.
Step 09 runtime corrections produced the final hashes shown above.

## Step 09 — Create and Audit the Isolated Runtime

Validated the operator-supplied secret path without persisting its location or
content, stopped but retained the three old baseline containers, and created the
formal project. Runtime checks exposed three symmetric configuration defects:
the Compose PATH omitted the immutable Node directory, AppArmor allowed
nonexistent Node compatibility paths, and nested tools/cache volumes were
root-owned. These were corrected before any SDD installation or Agent request.

The final project has six running containers, six networks and three independent
HOME volumes. All Agents use the same image, UID 1007, four CPUs, 8 GiB memory,
512 PIDs, read-only root, capability drop, no-new-privileges, custom Seccomp and
the reloaded AppArmor profile. Their environment-set hash, Python dependency
hash and tool versions are identical. Config and secret mounts are read-only.

Each Agent belongs only to its own internal /24 with its matching proxy. Direct
external-IP access failed with errno 101, while provider TLS 1.3 reached only
the matching private proxy address and returned the api.deepseek.com certificate.
Inside the Codex bubblewrap sandbox, both provider network access and secret reads
were denied. HOME, tools, cache and workspace cross-visibility probes passed and
all markers were removed.

The same isolated smoke command passed in every final container:

| Variant | Branch | Result |
| --- | --- | --- |
| OpenSpec | `experiment/openspec` | `1 passed in 0.18s` |
| Spec Kit | `experiment/speckit` | `1 passed in 0.18s` |
| cc-sdd | `experiment/cc-sdd` | `1 passed in 0.18s` |

All repositories remain at `11079cb1c85b9e75a39a7269943c69d1a975d485`,
clean and remote-free. No SDD command or initialization directory exists, and no
HTTP or model API request was made.

```text
Compose SHA-256:  e4740873b943a2707a845a15f68d30c56436e77b2769e9fc5780821b34e50e1c
launcher SHA-256: f3bd12b5225d1d1c529ef2df3bce58a837f41fb7587300a5c84f6cced41460a7
AppArmor SHA-256: c86d37481ca8c4eb44cc6432f4a8de4c65224f4fe9945ebfb772bf18b13d0b48
environment hash: 60851c6fd353143f04375be178aa90983024418ea59754e7b534f88a3f6fe4eb
```

Evidence: [final isolated runtime audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/isolated-agent-runtime-09h.json)
and the [current deployment lock](../tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/deployment-lock.json).

## Remaining Work Before a Formal Run

- Install and initialize exactly one fixed SDD tool per isolated service.
- Validate generated Skills and diffs, run the equal smoke test, and perform a
  separately approved minimal live-provider compatibility check.
