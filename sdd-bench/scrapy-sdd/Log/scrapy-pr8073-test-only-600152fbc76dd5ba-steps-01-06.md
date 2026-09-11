# Scrapy SDD Baseline — Working Log

> **Scope:** Steps 01–06 of the 18-step baseline workflow  
> **State:** Baseline prepared; image not built  
> **Recorded:** 2026-09-03T06:19:39Z  
> **Reformatted:** 2026-09-03 (UTC)

## At a Glance

| Item | Value |
|---|---|
| Progress | **6 / 18 steps complete** |
| Host | <code>Mercury</code> |
| Operator UID:GID | <code>1007:1007</code> |
| Repository | <code>scrapy/scrapy</code> |
| Pull request | <code>8073</code> |
| Selected prompt index | <code>0</code> |
| Task ID | <code>scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| Task base SHA | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Baseline Git state | Detached HEAD, shallow, one reachable commit |
| Baseline remote count | <code>0</code> |
| Baseline worktree | Clean |
| Docker image | Not built yet |
| SDD tools | Not installed or initialized |
| Next step | Step 07 — build the shared task image |

## Reuse and Isolation Model

The prompt collection does **not** require one baseline per prompt:

~~~mermaid
flowchart LR
    P["1,245 test-case prompts"] --> R["98 pull requests"]
    R --> S["75 distinct base SHAs"]
    S --> E["Reusable immutable baseline + dependency image"]

    P --> T["Sample-specific task"]
    T --> O["OpenSpec clone + container"]
    T --> K["Spec Kit clone + container"]
    T --> C["cc-sdd clone + container"]
~~~

| Scope | Reused | Never shared |
|---|---|---|
| Same base SHA | Immutable baseline and dependency image | — |
| Same PR | Base SHA environment; PR 8073 has 3 prompts | Task worktrees and runtime state |
| Same test-case task | Common starting commit and image | OpenSpec, Spec Kit, and cc-sdd Git repositories |
| Containers | Same image ID and Python/dependency versions | Writable layer, <code>.venv</code>, <code>.tox</code>, and cache |

The full base SHA is the environment cache key. A <code>sample_id</code>
remains the identity of one test-case experiment.

## Key Paths

| Purpose | Path |
|---|---|
| Suite root | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd</code> |
| SHA environment | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Immutable baseline | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy</code> |
| Dockerfile | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker/Dockerfile</code> |
| Current task | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |

## Input Provenance

The current prompt record was read from the top level of array entry
<code>0</code>. The <code>sample_id</code>, <code>repo</code>, and
<code>pr_id</code> values were read directly; the prompt body was not parsed
for identity data. The matching raw PR was selected by
<code>(repo, pr_id)</code>, and its top-level <code>base_sha</code> became
the task base SHA.

| Input | SHA-256 |
|---|---|
| <code>output/prompt/scrapy__scrapy.json</code> | <code>76867cef42647720db0c052963ff9ae0f7db8de41f821cca1773cab5ecdd1c76</code> |
| <code>output/raw_prs/scrapy__scrapy.jsonl</code> | <code>4cf2d27621963dc79b413f84b4c04e3a5a4fbd1e540c682be6d3e9c15dd239e1</code> |

## Progress Summary

| Step | Purpose | Result | Files manually authored |
|---:|---|---|---:|
| 01 | Resolve task identity and base SHA | Complete | 0 |
| 02 | Create directory skeleton | Complete | 0 |
| 03 | Materialize shallow Scrapy baseline | Complete | Git materialization |
| 04 | Remove remote and validate minimal history | Complete | Git control metadata only |
| 05 | Inspect compatibility and test requirements | Complete | 0 |
| 06 | Create the task Dockerfile | Complete | 1 |

---

## Step 01 — Resolve Task Identity and Base SHA

### Purpose

Select the current test-case prompt without parsing its natural-language
body, resolve the matching PR, and determine the exact pre-PR commit.

### Result

| Field | Value |
|---|---|
| <code>CURRENT_PROMPT_INDEX</code> | <code>0</code> |
| <code>TASK_ID</code> | <code>scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| <code>TASK_REPO</code> | <code>scrapy/scrapy</code> |
| <code>TASK_PR_ID</code> | <code>8073</code> |
| <code>TASK_BASE_SHA</code> | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Prompts from PR 8073 | <code>3</code> |
| Environment state | New |
| Target conflicts | None |

### Collection-Wide Reuse Audit

| Metric | Count |
|---|---:|
| Prompt records | 1,245 |
| Unique prompt PRs | 98 |
| Unique task base SHAs | 75 |
| PR records belonging to shared-base groups | 41 |

> **Audit note:** The first read-only <code>jq</code> deduplication query
> failed because <code>.base_sha</code> was projected outside
> <code>map()</code>. It made no filesystem or Docker changes. The corrected
> query completed successfully.

<details>
<summary><strong>Resolution and validation logic</strong></summary>

1. Read <code>output/prompt/scrapy__scrapy.json[0]</code>.
2. Read <code>sample_id</code>, <code>repo</code>, and <code>pr_id</code>
   from that object's top level.
3. Match <code>output/raw_prs/scrapy__scrapy.jsonl</code> on repository and
   PR ID.
4. Require exactly one distinct, full 40-character <code>base_sha</code>.
5. Check that the SHA-level environment and sample-level run targets do not
   conflict with existing paths.
6. Compute SHA-256 fingerprints of both source data files.

</details>

## Step 02 — Create the Directory Skeleton

### Purpose

Separate reusable SHA-level resources from sample-specific SDD runs before
any repository or container is created.

### Result

- Created the SHA environment's <code>baseline/</code> and
  <code>docker/</code> directories.
- Created task-local <code>runs/openspec/</code>,
  <code>runs/speckit/</code>, and <code>runs/cc-sdd/</code>.
- Created the task-local <code>results/</code> directory.
- Created no files.

<details>
<summary><strong>Executed command</strong></summary>

~~~bash
mkdir -p \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/results
~~~

</details>

## Step 03 — Materialize the Shallow Baseline

### Purpose

Create a complete Scrapy working tree at the exact task base SHA while
retaining only the minimum Git history.

### Result

| Check | Result |
|---|---|
| HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Commit subject | <code>Remote control extension. (#7866)</code> |
| Reachable commits | <code>1</code> |
| Branch state | Detached HEAD |
| Worktree | Clean |

The repository was materialized directly at its final path. No baseline file
was moved, renamed, or manually edited.

<details>
<summary><strong>Executed commands</strong></summary>

~~~bash
git init \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  remote add origin https://github.com/scrapy/scrapy.git

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  fetch --depth=1 --no-tags origin \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  checkout --detach FETCH_HEAD
~~~

</details>

## Step 04 — Remove Remote Access

### Purpose

Prevent agents from discovering future repository state through a configured
Git remote.

### Result

| Check | Result |
|---|---:|
| HEAD matches task base SHA | Yes |
| Reachable commits | 1 |
| Shallow repository | Yes |
| Configured remotes | 0 |
| Remote-tracking refs | 0 |
| Worktree status | Clean |

Only <code>.git</code> control metadata changed. Scrapy source files remained
untouched.

<details>
<summary><strong>Executed command and validation</strong></summary>

~~~bash
git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  remote remove origin

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  rev-list --count HEAD

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  rev-parse --is-shallow-repository

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  status --porcelain=v1 --untracked-files=all
~~~

</details>

## Step 05 — Inspect Compatibility and Test Requirements

### Purpose

Choose a compatible Python runtime, install the project-defined test
dependencies, and select a deterministic smoke test.

### Required Project Paths

All are present and tracked:

| Path | Type |
|---|---|
| <code>scrapy/</code> | Package source |
| <code>tests/</code> | Test suite |
| <code>pyproject.toml</code> | Project and build metadata |
| <code>tox.ini</code> | Test environment definition |

### Runtime Decision

| Item | Decision |
|---|---|
| Project requirement | Python <code>>=3.10</code> |
| Selected runtime line | CPython 3.11 |
| Project test extra | None |
| Test dependency source | <code>[test-requirements]</code> in <code>tox.ini</code> |
| Smoke target | <code>tests/test_http_headers.py::test_basics</code> |

The smoke test exercises in-memory <code>Headers</code> behavior. It requires
no network, external service, filesystem fixture, or Twisted reactor.

### Test Dependencies

| Dependency | Constraint |
|---|---|
| attrs | Unpinned |
| coverage | <code>>=7.10.6</code> |
| httpx2 | Unpinned |
| pexpect | <code>>=4.8.0</code> |
| pyftpdlib | <code>>=2.0.1</code> |
| pygments | Unpinned |
| pytest | <code>>=8.4.1</code> |
| pytest-cov | <code>>=7.0.0</code> |
| pytest-rerunfailures | Unpinned |
| pytest-timeout | Unpinned |
| pytest-xdist | Unpinned |
| sybil | <code>>=1.3.0</code> |
| pytest-twisted | <code>>=1.14.3</code> |

The baseline remained clean after all inspection commands.

## Step 06 — Create the Dockerfile

### Purpose

Define one image for all experiments starting from this base SHA, without
installing or initializing any SDD tool.

### Artifact

| Item | Value |
|---|---|
| File | <code>environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker/Dockerfile</code> |
| SHA-256 | <code>a75e587e9a27dc05f7fce5fae3430e17fd9e29d123366790ca0eb5d23d15bc71</code> |
| Base image | <code>python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7</code> |
| Runtime user | Non-root <code>bench</code> |
| SDD tools | None |

### Design Decisions

- The Python base is pinned by digest rather than a mutable tag.
- Git, Scrapy, and the test dependencies from <code>tox.ini</code> are
  installed.
- Tox itself is not installed.
- Only package build inputs are copied; <code>.git</code> and
  <code>tests/</code> are excluded from the image.
- pip cache, XDG cache, Python bytecode, and tox work paths point below
  container-private <code>/tmp</code>.
- The Dockerfile defaults to UID/GID <code>1000:1000</code>; Step 07 must
  explicitly build with the host values <code>1007:1007</code>.
- Exact resolved package versions will be captured with
  <code>pip freeze --all</code> after the image is built once.

### Post-Step Baseline Audit

| Check | Result |
|---|---|
| HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Remote count | <code>0</code> |
| Worktree | Clean |

---

## Current Safety Invariants

- [x] The baseline has exactly one reachable commit.
- [x] The baseline is shallow and checked out at the exact task base SHA.
- [x] The baseline has no Git remote or remote-tracking refs.
- [x] Baseline source files have not been modified.
- [x] OpenSpec, Spec Kit, and cc-sdd have not been installed or initialized.
- [x] No SDD worktree, virtual environment, tox directory, or cache is shared.
- [ ] The task image has been built.
- [ ] The three independent SDD clones have been created.
- [ ] The three isolated containers have been started.
- [ ] Smoke tests have been executed.

## Next Step — 07

Build a single image for this base SHA:

| Build setting | Value |
|---|---|
| Image tag | <code>scrapy-sdd-scrapy:base-11079cb1c85b-py311</code> |
| <code>BENCH_UID</code> | <code>1007</code> |
| <code>BENCH_GID</code> | <code>1007</code> |

After the build, record:

1. Final image ID and RepoDigest, if present.
2. Exact Python version.
3. <code>pip check</code> result.
4. Complete <code>pip freeze --all</code> output and its normalized SHA-256.
5. Docker labels linking the image to the full Scrapy base SHA.

No image or container had been created when this log was recorded.
