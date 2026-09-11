# Scrapy SDD Deployment — Steps 19–27

Task: `scrapy__scrapy__8073__test_only__600152fbc76dd5ba` · PR 8073
Progress: **27/28 complete** · Formal startup entrypoints and the final deployment manifest are complete; only the independent final audit remains.

## Logging Convention

This working log records only the purpose, important result and remaining caveat for each completed main step. Full commands, generated-file hashes and machine-readable observations remain in the linked audit directory.

## Step 19 — Preview cc-sdd Initialization

Locked the deterministic non-interactive initialization command to the installed cc-sdd 3.0.2 entrypoint with explicit `codex-skills`, English, Linux, force-overwrite and full-profile settings. A dry-run in an independent `/tmp` tmpfs repository copy exited zero, wrote nothing and declared the same 68-file total produced by the subsequent real preview in that disposable copy.

The preview generated 50 files under `.agents/skills/`, one Codex agent file, 16 `.kiro/settings/` files and root `AGENTS.md`, totalling 244,335 bytes. All 17 `SKILL.md` files are non-empty and have valid frontmatter. The 24 remaining `{{...}}` variables are intentional specification-template fields and occur only in the two skills that explain their substitution or under `.kiro/settings/templates/`; no unexpected placeholder path exists.

No tracked or staged file changed. The protected Scrapy index hash remained `9c5323c4165074b47ab2c251d6b9c1592988a8af673437e6d4234a9b79043446`, and no OpenSpec or Spec Kit path appeared. The complete generated-file manifest hashes to `3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca`; the full initialization patch hashes to `270f8e1dc736745ac55154ca9b8dc4b904c9a3e5f6c19861a0fcd92fb373f00b`. The disposable copy was deleted, and the real cc-sdd repository remains clean. Evidence: [Step 19 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/cc-sdd-init-preview-19/evidence.json).

### Remaining Caveat

Initialization has not yet been written to the real cc-sdd workspace. Step 20 must reproduce the same 68-file result there and require exact path and byte equality with this preview before any independent smoke audit. `formal_run_ready` remains false.

## Step 20 — Formally Initialize cc-sdd

Reconfirmed the real cc-sdd repository at the pinned single-commit HEAD/tree on `experiment/cc-sdd`, with no remote and a clean prestate. Ran the exact Step 19 command in its real `/workspace`; it exited zero with empty stderr and wrote all 68 expected files.

Every generated path and byte matches the disposable preview. The formal and preview generated-file manifests both hash to `3be430c9092a6396aa0d9f5ae4be85f9d66ac33ee3cb986c175334503abf4cca`, their complete initialization patches both hash to `270f8e1dc736745ac55154ca9b8dc4b904c9a3e5f6c19861a0fcd92fb373f00b`, and stdout is identical. The formal project contains 17 validated Codex skills, valid `.codex/agents/spec-reviewer.toml`, 16 `.kiro/settings/` files and root `AGENTS.md`; `.kiro/specs/` is intentionally created later by a concrete specification workflow.

The repository has no tracked, staged or deleted change. Its 68 untracked paths are exactly the approved generated set. Both the protected index hash and independent protected-content hash remained unchanged, and neither OpenSpec nor Spec Kit files appeared. Evidence: [Step 20 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/cc-sdd-init-formal-20/evidence.json).

### Remaining Caveat

The initialized cc-sdd group still requires an independent version, structure, isolation and Scrapy smoke audit. Final cross-group and separately approved live-provider checks also remain pending, so `formal_run_ready` remains false.

## Step 21 — Independently Audit cc-sdd

Revalidated cc-sdd 3.0.2 from its private npm tree. `npm ls` contains only the fixed direct package and passes; the installed tree hash remains `573c2b2c33bb43161c8762972726a5efd830408bec4977de8236f2707a66c21c`. The shared Scrapy Python still contains 69 packages, passes `pip check`, and has the normalized dependency hash `570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd`. An initially different raw-output hash was resolved by applying the established sorted-freeze normalization, with no dependency change found.

All 68 generated files independently match the Step 20 manifest. The 17 skill directories, 50 skill-tree files, valid `SKILL.md` frontmatter, `.codex/agents/spec-reviewer.toml` and 16 `.kiro/settings/` files passed structure checks. The repository retains its pinned single-commit HEAD/tree with no remote, tracked or staged change; all protected hashes remain unchanged.

Fresh HOME probes confirmed that each of the three identical-image Agents contains only its assigned SDD installation and cannot see another Agent's private tool tree. The initialized cc-sdd workspace was copied to independent tmpfs and ran `tests/test_http_headers.py::test_basics`: `1 passed in 0.18s`. The repository copy and pytest basetemp were deleted, and all three real repositories retained exactly their expected 10, 30 and 68 generated files. Evidence: [Step 21 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/cc-sdd-independent-audit-21/evidence.json).

### Remaining Caveat

Each individual SDD deployment now passes its own audit. The benchmark still requires a single symmetric cross-group comparison, Codex integration recognition checks and the separately approved live-provider validation before `formal_run_ready` can become true.

## Step 22 — Symmetrically Compare All Three Groups

Collected every common runtime field with the same command sequence. All Agents are running on image `sha256:5331d81398045534dfca13267402e4f97dad9d6ad43524a62b05286741e960a9` as UID/GID 1007, with Python 3.11.15, Node 24.20.0, npm 11.19.0, uv 0.12.10 and Codex 0.153.4. Each system Python has the same 69-package normalized hash and passes `pip check`.

All three Agent resource and security fields match: 4 CPU quota, 8 GiB memory with no additional swap, PID limit 512, read-only root filesystem, capability drop ALL, no-new-privileges, identical custom Seccomp/AppArmor settings and a private 2 GiB `/tmp`. Their network modes, HOME volumes and workspace sources are three distinct values. A same-path cache ownership probe proved the caches are private and was removed. Each HOME exposes only its assigned fixed SDD version.

The DeepSeek model, provider, API base, Codex config, provider profile and model catalog hashes are equal in all three groups; only the secret mount path and read-only property were checked, never credential content. The three healthy egress proxies also have one common fixed image and identical 0.25 CPU, 128 MiB, PID 64 and security settings.

All repositories still share the same single-commit HEAD/tree and identical protected index/content hashes with no remotes or tracked/staged differences. Their 10, 30 and 68 untracked files are exactly their respective SDD outputs. Finally, the identical smoke command ran sequentially in the same path inside each private tmpfs: all three returned `1 passed in 0.18s`, exit zero, empty stderr and normalized stdout SHA256 `34423ae2823934c8bcf724d1b5ea6959c87621a972ef23277995f842d0018922`. Every temporary path was removed. Evidence: [Step 22 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/symmetric-cross-group-22/evidence.json).

### Remaining Caveat

Runtime fairness and smoke equivalence are now demonstrated. Codex still needs non-model recognition checks for each generated integration, followed by separately approved minimal live-provider validation and final manifest/audit work. `formal_run_ready` remains false.

## Step 23 — Verify Codex Integration Recognition Offline

Checked the rolling official Codex rules for repository-scoped `.agents/skills` and `AGENTS.md`, then verified the actual behavior of the pinned Codex CLI 0.153.4. All three provider egress proxies were paused while Codex rendered its model-visible prompt and answered its local `skills/list` protocol request, so no provider or model request was possible.

Codex registered exactly the generated filesystem sets: 6 OpenSpec, 10 Spec Kit and 17 cc-sdd repo skills, all enabled with zero parse errors. No registry contained a foreign SDD skill. OpenSpec and Spec Kit exposed all their skills in the initial prompt. cc-sdd intentionally exposed only `kiro-spec-batch` for implicit use; its other 16 generated `openai.yaml` files set `allow_implicit_invocation: false`, but all remain registered for explicit `$kiro-*` invocation. Codex also loaded cc-sdd's root `AGENTS.md`, including the explicit workflow and skill-location guidance.

The pinned CLI rejects `--strict-config` on `debug` and `--profile` on `app-server`; both fail-fast behaviors were retained as version evidence, and the checks were rerun with the supported interfaces. Codex's first local invocation materialized one identical system-skill tree independently inside each private HOME. No session or shell-snapshot file remained. All egress proxies were restored healthy, all temporary schemas were removed, and every repository's pre/post Git state is byte-identical. Evidence: [Step 23 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/codex-recognition-23/evidence.json).

### Remaining Caveat

Static initialization, runtime fairness, smoke equivalence and Codex recognition now pass. The separately approved minimal live-provider compatibility check and final deployment manifest/audit work remain pending, so `formal_run_ready` remains false.

## Step 24 — Validate the Live Provider Symmetrically

Used the fixed launcher to invoke Codex CLI 0.153.4 sequentially in OpenSpec, Spec Kit and cc-sdd with the same prompt, DeepSeek v4 Pro profile, Responses wire protocol, high reasoning setting, sandbox/approval policy and timeout. The prompt explicitly prohibited skills, tools, commands and file access and required the exact marker `BENCH_API_OK`. The official Codex non-interactive JSONL contract was checked before execution.

All three invocations exited zero, emitted one successful `turn.completed`, returned exactly `BENCH_API_OK`, wrote nothing to stderr and produced no command, file-change, MCP or web-search event. Usage was 8,875/6 input/output tokens for OpenSpec, 8,949/6 for Spec Kit and 10,244/6 for cc-sdd. The input differences are expected because the initialized integrations contribute different context; protocol success and observable side effects are the comparison criteria. Each stream also contained the same local warning that pinned `rollout_budget` is under development, followed by a successful provider turn.

The auditor inspected only credential-file metadata. Credential bytes were consumed solely by the trusted Codex parent through the existing Docker-secret auth command and were absent from JSONL, stderr and all evidence. `--ephemeral` left no rollout or shell-snapshot file. Repository pre/post state is byte-identical, runtime configuration hashes remain equal, and all six containers finished running with every egress proxy healthy. Evidence: [Step 24 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/live-provider-24/evidence.json).

### Remaining Caveat

The live check validates the configured endpoint and protocol, not immutable model weights: `deepseek-v4-pro` remains an upstream alias. A post-live symmetric integrity/reproducibility audit, final manifest and final readiness audit remain, so `formal_run_ready` is still false.

## Step 25 — Audit Post-live Integrity and Reproducibility

Revalidated the Step 22–24 evidence chain against the deployment lock, then recollected repository, runtime, resource, mount, security, private-tool and isolation facts. All three Agents remain on the same fixed image and runtime versions. Each repository retains the pinned single-commit HEAD/tree with no remote, tracked or staged change; only its approved 10, 30 or 68 generated SDD files remain untracked.

The assigned tools still report OpenSpec 1.12.0, Spec Kit 1.0.4 and cc-sdd 3.0.2. Their dependency checks and fixed entrypoints pass, and each private HOME contains exactly one SDD installation. A single ad-hoc Spec Kit preflight briefly returned a permission denial, but the formal audit could not reproduce it: both the direct private-venv console script and the trusted system-Python/private-site-packages invocation passed. This transient observation is retained in the evidence rather than hidden.

Private HOME/cache markers remained group-specific, direct external connections returned errno 101, and provider DNS resolved only to each group's matching private proxy. No Codex session, shell snapshot, credential filename/path, prompt copy, or temporary smoke/cache probe remained. The same smoke target ran sequentially from private tmpfs copies in all three groups; each produced one pass, exit zero, empty stderr and the same normalized hash as Step 22. Docker's expanded `SecurityOpt` serialization used a different hashing representation than Step 22, so the audit compared stable semantic columns byte-for-byte and separately verified one common current serialization plus the unchanged pinned seccomp source hash. Evidence: [Step 25 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/post-live-symmetric-25/evidence.json).

### Remaining Caveat

The environments have passed post-live integrity checks, but `formal_run_ready` remains false until the final startup commands and deployment manifest are generated and independently audited in Steps 26–28.

## Step 26 — Validate the Formal Startup Entry

The original launcher still required an entirely clean worktree, which was correct before initialization but rejected the intended 10, 30 and 68 generated SDD files. The launcher now requires no tracked or staged changes and validates every untracked path and byte against the fixed formal-initialization manifest for that experiment. Extra, missing or modified generated files fail closed.

Shell syntax, live runtime verification, service status, all three variant routes, workspace/HOME/network mappings and missing/empty-secret behavior passed without a provider request. The three workspaces, HOME volumes and private networks remain distinct. Evidence: [Step 26 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/formal-startup-entry-26/evidence.json).

## Step 27 — Generate the Deployment Manifest

Created one human-readable English manifest containing the final directory layout, pinned common runtime, repository identities, all fixed SDD versions and initialization commands, generated-file/Git results, isolation controls, symmetric smoke result, limitations, evidence index and exact startup/run command templates.

The manifest uses only a secret-path placeholder and contains neither credential content nor the real host credential path. Step 28 corrected its baseline location to the shared versioned `environments/` directory; the corrected SHA256 is `ccdb1e5cacb5ae40ea85eb2911b18a82245ea4a3b8ba53ad3c7bd83002cb2983`. Manifest: [deployment manifest](scrapy-pr8073-test-only-600152fbc76dd5ba-deployment-manifest.md). Evidence: [Step 27 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/deployment-manifest-27/evidence.json).

### Remaining Caveat

All implementation and documentation work is complete, but `formal_run_ready` deliberately remains false until Step 28 independently rechecks the complete evidence chain, live objects, repositories, isolation, launcher and manifest.
