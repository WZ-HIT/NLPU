# Scrapy SDD Deployment — Steps 10–18

Task: `scrapy__scrapy__8073__test_only__600152fbc76dd5ba` · PR 8073
Progress: **18/28 complete** · OpenSpec 1.12.0, Spec Kit 1.0.4 and cc-sdd 3.0.2 are installed in separate Agent HOMEs; OpenSpec and Spec Kit have passed their independent initialization, isolation and smoke audits.

## Logging Convention

This working log records the purpose, important result and remaining caveat for each completed main step. Full commands, hashes and machine-readable evidence remain in the linked audit records.

## Step 10 — Install OpenSpec

Revalidated the pinned OpenSpec 1.12.0 package lock and all 71 offline npm artifacts. The package-lock SHA256 is `c91b3c7c1dd3abf597291759371c9bf34b24f6bd8a04a580f20ab3af3864081f`; the artifact-manifest SHA256 is `fb9ee0748d19a1f956867184488abfb2d3b3dbff4d33f4e1bbe982713cec3d74`. Every artifact filename, size, SHA256 and npm integrity value matched.

Installed with Node 24.20.0 and npm 11.19.0 using exactly `npm ci --offline --ignore-scripts --engine-strict`. The resulting OpenSpec CLI reports version 1.12.0, its help output passed, and `npm ls --all --json` passed. The dependency tree contains 80 locked package entries and lifecycle scripts were disabled. Installation persists only under the OpenSpec Agent's private `/home/bench/tools/npm` path; temporary staged inputs were removed.

The Spec Kit and cc-sdd Agent environments do not resolve `openspec`, and the OpenSpec Scrapy repository remains at the pinned HEAD/tree with clean Git status and unchanged protected paths. No provider or model request was made. Evidence: [Step 10 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/openspec-install-10/evidence.json).

### Remaining Caveat

OpenSpec has been installed but not initialized in the real repository. Steps 12–18 must still perform the approved real initialization, generated-file and Git-diff audit, remaining tool deployments, and equal smoke validation. `formal_run_ready` remains false.

## Step 11 — Preview OpenSpec Initialization

Verified the installed OpenSpec CLI as version 1.12.0 at its private absolute package path and recorded the `init --help` output. Copied the clean OpenSpec Scrapy repository into the Agent's private `/tmp`, confirmed the pinned HEAD and tree, and ran the fixed `openspec init --tools codex` command only in that disposable copy.

The preview created ten project files: `openspec/config.yaml`, placeholders below `openspec/specs/` and `openspec/changes/archive/`, a `.agents/skills/.openspec-target` marker, and six Codex `SKILL.md` files. It changed no tracked file and produced no files under `scrapy/**` or `tests/**`; their protected index hash remained unchanged. No Spec Kit or cc-sdd path was generated.

The temporary repository and its local command-output files were removed after their trees and output were exported to the audit directory. The real OpenSpec repository remains clean and contains neither `openspec/` nor `.agents/`. The CLI displayed its anonymous-telemetry notice, but no provider/model request was made and this offline preview observed no network request. Evidence: [Step 11 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/openspec-init-preview-11/evidence.json).

### Remaining Caveat

The preview proves the generated shape for this pinned CLI and command. `formal_run_ready` remains false pending the remaining installation, initialization, isolation and live-provider checks.

## Step 12 — Formally Initialize OpenSpec

Reconfirmed the real OpenSpec repository at the pinned HEAD and tree on `experiment/openspec`, with no remotes and a clean pre-initialization status. Recorded matching prestate hashes for all tracked `scrapy/**` and `tests/**` content, then ran the fixed `openspec init --tools codex` command in the OpenSpec Agent's real `/workspace`; it exited zero and its stdout matched Step 11.

The command added exactly the ten previewed files under `.agents/skills/` and `openspec/`. It modified or deleted no tracked files, staged nothing, and generated no unexpected path. A second clean reference initialization produced identical SHA256 values for every generated file. Both protected directories retained their pre-initialization index and content hashes.

The complete untracked-file patch, generated-file hashes, stdout, stderr, status and preview comparison are preserved in [Step 12 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/openspec-init-formal-12/evidence.json). No model request was made.

### Remaining Caveat

The OpenSpec initialization files intentionally remain untracked for independent Step 13 auditing. Spec Kit and cc-sdd are still uninstalled and uninitialized, and `formal_run_ready` remains false.

## Step 13 — Independently Audit OpenSpec

Verified OpenSpec 1.12.0 from its private OpenSpec HOME package path. The real workspace has the `spec-driven` configuration, empty specification and change placeholders, and exactly six non-empty Codex skills targeting `codex`; every generated file still matches the Step 12 size and SHA256 manifest.

The three Agents retain distinct HOME volumes. Only the OpenSpec HOME contains or resolves OpenSpec; the Spec Kit and cc-sdd containers have neither an `openspec` command nor an OpenSpec path under HOME. The OpenSpec repository retains the pinned HEAD/tree and `experiment/openspec` branch with no remote, tracked modification, staged file or deletion. Its ten untracked paths are exactly the approved initialization files, while `scrapy/**` and `tests/**` retain their protected hashes.

Ran `tests/test_http_headers.py::test_basics` from a private tmpfs copy inside the OpenSpec Agent: `1 passed in 0.18s`. The temporary copy was deleted and the real workspace was unchanged. Evidence: [Step 13 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/openspec-independent-audit-13/evidence.json).

### Remaining Caveat

The OpenSpec group is independently usable and isolated, but Spec Kit and cc-sdd deployment and auditing plus the separately approved live-provider check remain pending. `formal_run_ready` remains false.

## Step 14 — Install Spec Kit

Revalidated the pinned Spec Kit 1.0.4 source commit `cb610277fdea781fcfa83d20522c2db37c94068d`, the Git-archive commit marker, project version and all 23 artifact-manifest entries. The source archive, built wheel and build/runtime/install requirement locks matched their recorded SHA256 values.

Created `/home/bench/tools/python/speckit-1.0.4` only in the Spec Kit Agent's private HOME volume with Python 3.11.15, uv 0.12.10 and `include-system-site-packages = false`. Installed 15 packages using the fixed command policy `uv pip sync --offline --no-index --require-hashes --no-build`; `uv pip check`, `specify --version` (`specify 1.0.4`) and `specify --help` passed. The system Scrapy Python dependency hash remained unchanged.

OpenSpec and cc-sdd cannot see the Spec Kit HOME marker, venv, package or CLI. Temporary artifact staging was removed; all three repositories retained their prior HEAD/tree, remote and status states, and the protected `scrapy/**` and `tests/**` index hash remained identical. The strict parent AppArmor profile rejects execution through a HOME symlink, so no persistent shim was retained; administrative init checks use the fixed venv executable by absolute path without weakening the profile. Evidence: [Step 14 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/speckit-install-14/evidence.json).

### Remaining Caveat

Spec Kit is installed but has not initialized the real repository. Steps 15–17 must preview, formally initialize and independently audit its generated Codex integration. cc-sdd remains uninstalled, and `formal_run_ready` remains false.

## Step 15 — Preview Spec Kit Initialization

Confirmed that the fixed Spec Kit 1.0.4 CLI supports every locked non-interactive initialization option and uses templates bundled with the installed wheel. Copied the clean Spec Kit repository into its Agent's private `/tmp` tmpfs, verified that it was on a different filesystem from `/workspace`, and ran the fixed Codex-skills initialization command there only.

The preview exited zero with empty stderr and generated 30 untracked files: 20 under `.specify/` and ten non-empty Codex skills under `.agents/skills/`. Six generated shell scripts are executable. The full 245,223-byte untracked patch applies cleanly to the fixed real repository, and a SHA256 manifest records all generated files. This CLI version does not create `specs/` during initialization; it creates that directory when the first concrete specification is authored.

No tracked or staged file changed. The `scrapy/**` and `tests/**` index and content hashes remained identical, and neither `openspec/` nor `.kiro/` appeared. The temporary repository was deleted after evidence export, while the real Spec Kit repository stayed clean, remote-free and uninitialized. The strict AppArmor profile was preserved; direct Docker process entry was used for the fixed HOME executable. Evidence: [Step 15 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/speckit-init-preview-15/evidence.json).

### Remaining Caveat

The 30-file preview defines the required path and content contract for Step 16. Three tool-owned manifest files contain installation timestamps and therefore require timestamp-normalized comparison; all other files require exact SHA256 matches. The real Spec Kit repository remains unchanged until formal initialization is explicitly approved, and `formal_run_ready` remains false.

## Step 16 — Formally Initialize Spec Kit

Reconfirmed the real Spec Kit repository at the fixed HEAD/tree on `experiment/speckit`, with no remote and a clean prestate. Ran the same fixed non-interactive Codex-skills initialization command in the real `/workspace`; it exited zero with empty stderr and generated exactly the 30 previewed paths.

Twenty-seven generated files matched the preview byte-for-byte. The other three are the two integration manifests and workflow registry, whose only differences are the CLI-generated `installed_at` and `updated_at` timestamps. After normalizing only those fields and derived Git index lines, the complete preview and formal patches share SHA256 `6eda2ec4019724601cbc52d30a103e846097305883708b23af8934678a0fcff2`; no other content differs.

The resulting project contains 20 `.specify/` files, ten validated Codex skills and six executable shell scripts. Both generated manifests validate every listed file hash. There are no tracked, staged or deleted changes, and the 30 untracked files are the complete expected initialization set. `scrapy/**` and `tests/**` retained their pre-initialization hashes; neither `openspec/` nor `.kiro/` was generated. As observed in the preview, `specs/` is created only when the first specification is authored. Evidence: [Step 16 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/speckit-init-formal-16/evidence.json).

### Remaining Caveat

The initialized Spec Kit group still requires the independent version, isolation and smoke audit in Step 17. cc-sdd remains uninstalled, and `formal_run_ready` remains false.

## Step 17 — Independently Audit Spec Kit

Independently revalidated Spec Kit 1.0.4 in its private Python 3.11.15 venv using uv 0.12.10. All 15 packages pass `uv pip check`, the venv freeze hash remains `c7417b5ac7c83bb87922eb9db5b4626325b52b87e679c00a70814755faca149a`, and the separate Scrapy system-Python dependency hash remains unchanged.

Recomputed all 30 generated-file hashes and verified both generated manifests, ten non-empty Codex skills with valid frontmatter, 20 `.specify/` files and six executable scripts. The repository remains on the fixed single-commit HEAD/tree with no remote, tracked modification, staged file or deletion; its 30 untracked paths are exactly the formal initialization set, and `scrapy/**` plus `tests/**` remain unchanged.

Fresh HOME-marker and tool-visibility probes confirmed that OpenSpec and cc-sdd cannot see the Spec Kit venv or CLI, while Spec Kit contains neither other SDD tool. The common smoke target ran from an independent private tmpfs copy and returned `1 passed in 0.18s`; all temporary files were removed and the real repository remained unchanged. Evidence: [Step 17 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/speckit-independent-audit-17/evidence.json).

During the final audit, all three Agent containers were found to have received SIGTERM in the same second and exited with code 143; none was OOM-killed, and all three egress proxies remained healthy. The same existing Agent containers were restarted symmetrically without recreation, retaining the common image, distinct mounts and HOME volumes. All six services, the Spec Kit CLI, temporary-path cleanup and repository state passed the post-recovery check.

### Remaining Caveat

OpenSpec and Spec Kit are independently audited. cc-sdd installation, preview, initialization and audit plus the final cross-group and live-provider checks remain pending, so `formal_run_ready` remains false.

## Step 18 — Install cc-sdd

Revalidated cc-sdd 3.0.2 against its one-entry npm lock, retained release tarball, registry integrity string, exact Node 24.20.0 and npm 11.19.0 engine requirements. The package-lock SHA256 is `933c67ed634facbb5a724d45cb05089b0ac7bb31e7664489879a9ca9cf300000`; the tarball SHA256 is `ae5a247b357e61139d1f154dcdc67996e5da783f931c99dd450cf03569441fe4`. Source commit `3795eb4274c07dedcf56c571b5c0a826736f23c8` remains a separate provenance pin because the npm package metadata does not contain `gitHead`.

Installed only into the cc-sdd Agent's private `/home/bench/tools/npm` using `npm ci --offline --ignore-scripts --engine-strict --no-audit --no-fund`. `npm ls`, `cc-sdd v3.0.2` and the complete help check passed. The installed package has no transitive runtime dependency; its 410-file tree hashes to `573c2b2c33bb43161c8762972726a5efd830408bec4977de8236f2707a66c21c`. Lifecycle scripts were disabled, no model/provider request was made, and the exact staging directory was removed after installation.

Fresh write probes confirmed that all three Agent HOMEs remain independent. OpenSpec and Spec Kit cannot see cc-sdd, while the cc-sdd HOME contains neither other SDD tool. All repositories retain the fixed HEAD/tree and no remotes. OpenSpec has exactly its ten approved generated files, Spec Kit has exactly its 30 approved generated files, and cc-sdd remains completely clean because Step 18 performed installation only. No protected `scrapy/**`, `tests/**`, `pyproject.toml` or `tox.ini` path changed. Evidence: [Step 18 audit](scrapy-pr8073-test-only-600152fbc76dd5ba-baseline-and-deployment-audits/cc-sdd-install-18/evidence.json).

### Remaining Caveat

cc-sdd is installed but not initialized. Its disposable preview, formal initialization and independent smoke audit remain pending, followed by final cross-group and separately approved live-provider validation. `formal_run_ready` remains false.
