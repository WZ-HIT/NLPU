# Scrapy SDD Baseline — Working Log

> **Scope:** Steps 13–18 of the 18-step baseline workflow  
> **State:** Baseline workflow complete; three isolated containers running  
> **Recorded:** 2026-09-06T06:33:19Z  
> **Previous log:** <code>scrapy-pr8073-test-only-600152fbc76dd5ba-steps-07-12.md</code>

## At a Glance

| Item | Value |
|---|---|
| Progress | **18 / 18 steps complete** |
| Repository | <code>scrapy/scrapy</code> |
| Pull request | <code>8073</code> |
| Task ID | <code>scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| Task base SHA | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Shared image ID | <code>sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Runtime equality | Verified |
| Repository isolation | Verified |
| Smoke tests | 3 / 3 passed |
| Git worktrees | 3 / 3 clean |
| Containers | 3 / 3 running, zero restarts |
| Manifest | Created and validated |
| SDD tools | Not installed or initialized |

## Verification Flow

~~~mermaid
flowchart LR
    E["Step 13<br/>environment equality"] --> O["Step 14<br/>OpenSpec smoke"]
    O --> S["Step 15<br/>Spec Kit smoke"]
    S --> C["Step 16<br/>cc-sdd smoke"]
    C --> A["Step 17<br/>combined audit"]
    A --> M["Step 18<br/>manifest + logs"]
~~~

## Progress Summary

| Step | Purpose | Result | Files manually authored |
|---:|---|---|---:|
| 13 | Compare runtime environment and isolation | Complete | 0 |
| 14 | Run OpenSpec smoke test | Complete | 0 |
| 15 | Run Spec Kit smoke test | Complete | 0 |
| 16 | Run cc-sdd smoke test | Complete | 0 |
| 17 | Compare results and re-audit Git state | Complete | 0 |
| 18 | Create manifest and finalize documentation | Complete | 2 new files; 2 requested renames |

---

## Step 13 — Verify Runtime Equality and Isolation

### Purpose

Prove that the three containers use the same immutable runtime while their
writable experiment state remains separate.

### Equality Results

| Check | OpenSpec | Spec Kit | cc-sdd |
|---|---|---|---|
| Actual image ID | <code>sha256:f59cd…adfa</code> | Same | Same |
| Python | <code>3.11.15</code> | Same | Same |
| Python executable | <code>/usr/local/bin/python</code> | Same | Same |
| Installed packages | 69 | 69 | 69 |
| Freeze SHA-256 | <code>570e165…abd</code> | Same | Same |
| <code>pip check</code> | Pass | Pass | Pass |
| Runtime UID:GID | <code>1007:1007</code> | Same | Same |
| Root filesystem | Read-only | Read-only | Read-only |
| Network mode | None | None | None |
| SDD commands | Absent | Absent | Absent |

The complete normalized package set is preserved in
<code>baseline-manifest.md</code> and in the Steps 07–12 log.

### Isolation Results

| Service | Workspace source | Home volume | Mount namespace |
|---|---|---|---|
| OpenSpec | <code>runs/openspec/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_openspec-home</code> | <code>mnt:[4026536581]</code> |
| Spec Kit | <code>runs/speckit/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_speckit-home</code> | <code>mnt:[4026538623]</code> |
| cc-sdd | <code>runs/cc-sdd/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_cc-sdd-home</code> | <code>mnt:[4026538596]</code> |

The three workspace paths, volume names, and mount namespace IDs are all
distinct. Each container also has a private tmpfs at <code>/tmp</code>.

### Why the Repositories Are Independent

Repository isolation is enforced at several layers:

1. Each experiment has a different host worktree path.
2. Each worktree contains its own <code>.git</code> directory.
3. <code>git clone --no-hardlinks</code> copied Git object files.
4. No repository uses <code>.git/objects/info/alternates</code>.
5. Every configured Git remote and remote-tracking ref was removed.
6. Docker binds only one run repository into each container.
7. The immutable baseline is not mounted into any experiment container.

The repositories contain equal Git object IDs because their content is
equal, but the corresponding object files are stored independently.

~~~text
baseline object store
├── copied independently → OpenSpec object store
├── copied independently → Spec Kit object store
└── copied independently → cc-sdd object store
~~~

A commit or worktree modification in one experiment therefore does not
propagate into another experiment through Git or the filesystem.

### Cache and Temporary-State Isolation

| State | OpenSpec | Spec Kit | cc-sdd |
|---|---|---|---|
| Home | Independent volume | Independent volume | Independent volume |
| XDG cache | <code>/home/bench/.cache</code> | Same path, different volume | Same path, different volume |
| pip cache | <code>/tmp/pip-cache</code> | Same path, different tmpfs | Same path, different tmpfs |
| tox work dir | <code>/tmp/tox</code> | Same path, different tmpfs | Same path, different tmpfs |
| pytest temp | <code>/tmp/pytest-smoke</code> | Same path, different tmpfs | Same path, different tmpfs |

Using the same in-container path does not imply sharing: the backing mount
or mount namespace is different.

<details>
<summary><strong>Representative runtime audit commands</strong></summary>

~~~bash
docker inspect \
  scrapy-sdd-8073-600152fbc76dd5ba-openspec \
  scrapy-sdd-8073-600152fbc76dd5ba-speckit \
  scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd

docker exec scrapy-sdd-8073-600152fbc76dd5ba-openspec \
  python -m pip freeze --all

docker exec scrapy-sdd-8073-600152fbc76dd5ba-speckit \
  python -m pip freeze --all

docker exec scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd \
  python -m pip freeze --all

docker exec scrapy-sdd-8073-600152fbc76dd5ba-openspec \
  readlink /proc/1/ns/mnt

docker exec scrapy-sdd-8073-600152fbc76dd5ba-speckit \
  readlink /proc/1/ns/mnt

docker exec scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd \
  readlink /proc/1/ns/mnt
~~~

</details>

> **Audit note:** The first strict mount assertion compared a named volume's
> host storage <code>Source</code> with its logical name. Docker exposes the
> logical volume name in the <code>Name</code> field. The corrected audit
> used <code>Name</code> and passed. The failed assertion made no repository
> or container configuration change.

## Step 14 — Run the OpenSpec Smoke Test

### Purpose

Confirm that the OpenSpec runtime can import the mounted Scrapy checkout,
load pytest, and execute a deterministic unit of core behavior.

### Command

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T openspec \
  python -m pytest \
  -q \
  -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics
~~~

### Result

~~~text
.                                                                        [100%]
1 passed in 0.17s
~~~

| Check | Result |
|---|---|
| Exit code | 0 |
| Docker exec wall time | 2,648ms |
| Git status | Clean |
| HEAD and tree | Unchanged |
| <code>.pytest_cache</code>, <code>.venv</code>, <code>.tox</code> | Absent |
| Container | Running, zero restarts |

## Step 15 — Run the Spec Kit Smoke Test

### Purpose

Repeat the same test with the same arguments in the independently mounted
Spec Kit container.

### Command

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T speckit \
  python -m pytest \
  -q \
  -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics
~~~

### Result

~~~text
.                                                                        [100%]
1 passed in 0.17s
~~~

| Check | Result |
|---|---|
| Exit code | 0 |
| Docker exec wall time | 2,260ms |
| Git status | Clean |
| HEAD and tree | Unchanged |
| <code>.pytest_cache</code>, <code>.venv</code>, <code>.tox</code> | Absent |
| Container | Running, zero restarts |

## Step 16 — Run the cc-sdd Smoke Test

### Purpose

Complete the three-way comparison using the same smoke command in the
cc-sdd container.

### Command

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T cc-sdd \
  python -m pytest \
  -q \
  -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics
~~~

### Result

~~~text
.                                                                        [100%]
1 passed in 0.17s
~~~

| Check | Result |
|---|---|
| Exit code | 0 |
| Docker exec wall time | 2,264ms |
| Git status | Clean |
| HEAD and tree | Unchanged |
| <code>.pytest_cache</code>, <code>.venv</code>, <code>.tox</code> | Absent |
| Container | Running, zero restarts |

## What the Smoke Test Means

A smoke test is a small, fast check that answers whether the system is
operational enough for deeper testing. The selected target is itself a unit
test, but it is used here as a smoke test because only this representative
test is run.

The execution path is:

~~~text
Docker exec
  → CPython 3.11.15
  → pytest collection
  → import mounted Scrapy worktree
  → construct scrapy.http.Headers
  → evaluate basic lookup and normalization behavior
~~~

### Current Test Code

The selected test is
<code>tests/test_http_headers.py::test_basics</code>:

~~~python
def test_basics() -> None:
    h = Headers({"Content-Type": "text/html", "Content-Length": 1234})
    assert h["Content-Type"]
    assert h["Content-Length"]

    with pytest.raises(KeyError):
        h["Accept"]
    assert h.get("Accept") is None
    assert h.getlist("Accept") == []

    assert h.get("Accept", "*/*") == b"*/*"
    assert h.getlist("Accept", "*/*") == [b"*/*"]
    assert h.getlist("Accept", ["text/html", "images/jpeg"]) == [
        b"text/html",
        b"images/jpeg",
    ]
~~~

The implementation in <code>scrapy/http/headers.py</code> normalizes:

- header keys through <code>normkey()</code>;
- values through <code>normvalue()</code>;
- strings to encoded bytes;
- integers to their string representation encoded as bytes;
- default lists to <code>list[bytes]</code>.

The test checks:

1. Existing header lookup returns non-empty values.
2. Bracket lookup of a missing header raises <code>KeyError</code>.
3. <code>get()</code> returns <code>None</code> for a missing header.
4. <code>getlist()</code> returns an empty list for a missing header.
5. String and list defaults are normalized to bytes.

### What It Proves

- The container, interpreter, pytest, dependencies, and mount are usable.
- The mounted Scrapy checkout imports successfully.
- A basic in-memory Scrapy API behaves as expected.
- All three experimental lanes produce the same functional result.

### What It Does Not Prove

- It does not represent the complete Scrapy test suite.
- It does not test Twisted, downloader, network, spider, or reactor behavior.
- It does not prove that PR 8073's requested change has been implemented.
- It does not compare OpenSpec, Spec Kit, or cc-sdd capabilities.

No SDD tool exists in the containers at this stage. The smoke test establishes
only that the three experimental lanes start from healthy, equivalent
baselines.

## Step 17 — Compare Results and Re-Audit

### Smoke Comparison

| Service | Exit code | Functional result | Pytest duration | Wall time |
|---|---:|---|---:|---:|
| OpenSpec | 0 | 1 passed | 0.17s | 2,648ms |
| Spec Kit | 0 | 1 passed | 0.17s | 2,260ms |
| cc-sdd | 0 | 1 passed | 0.17s | 2,264ms |

The pytest-reported result and duration are identical. Docker exec wall time
is recorded for traceability but is not treated as a performance result.

### Final Git Comparison

| Service | Branch | HEAD | Tree | Status |
|---|---|---|---|---|
| OpenSpec | <code>experiment/openspec</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |
| Spec Kit | <code>experiment/speckit</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |
| cc-sdd | <code>experiment/cc-sdd</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |

The audit also reconfirmed:

- one reachable commit per run repository;
- shallow history;
- no remotes or remote-tracking refs;
- no alternates or hard-linked Git objects;
- no pytest cache, virtual environment, or tox directory;
- three running containers with zero restarts;
- unchanged Dockerfile and Compose SHA-256 values.

## Step 18 — Finalize the Manifest and Logs

### Manifest

| Item | Value |
|---|---|
| Path | <code>tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/results/baseline-manifest.md</code> |
| SHA-256 | <code>8bf4266059fcedc635614ddb689dedab368c8661460b6ba2f7db8a2f880f3fac</code> |
| Lines | 465 |
| Dependency entries | 69 |
| Markdown details blocks | 7 matched pairs |
| Markdown code fences | 9 matched pairs |

The manifest contains task identity and provenance, the final directory
tree, Git and Docker state, the dependency lock snapshot, mount isolation,
smoke results, core commands, and final safety assertions.

### Consistently Named Logs

| Scope | Final filename |
|---|---|
| Steps 01–06 | <code>scrapy-pr8073-test-only-600152fbc76dd5ba-steps-01-06.md</code> |
| Steps 07–12 | <code>scrapy-pr8073-test-only-600152fbc76dd5ba-steps-07-12.md</code> |
| Steps 13–18 | <code>scrapy-pr8073-test-only-600152fbc76dd5ba-steps-13-18.md</code> |

<details>
<summary><strong>Requested rename commands</strong></summary>

~~~bash
mv \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/working-log-steps-01-06.md \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-steps-01-06.md

mv \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/working-log-steps-07-12.md \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-steps-07-12.md
~~~

</details>

The Steps 07–12 document's previous-log reference was updated to the new
Steps 01–06 filename.

> **Documentation note:** The direct patch helper twice encountered a host
> sandbox loopback initialization failure while updating documentation. No
> partial edit occurred. The same scoped patches were then applied
> successfully through the interactive patch program.

---

## Final Safety Invariants

- [x] The baseline is shallow, detached, clean, and remote-free.
- [x] The baseline still has exactly one reachable commit.
- [x] Baseline source files were not modified, moved, or renamed.
- [x] Three independent run repositories exist.
- [x] Each run has its own experiment branch and Git object store.
- [x] All three runs start from the same commit and tree.
- [x] All three run worktrees are clean.
- [x] One immutable image is used by every service.
- [x] Python, Git, dependency count, and dependency hash match.
- [x] Repository mounts, home volumes, tmpfs, and mount namespaces differ.
- [x] All three smoke tests passed with identical functional results.
- [x] No SDD tool was installed or initialized.
- [x] The final manifest and three consistently named logs exist.

## Completion State

The baseline is ready for separate OpenSpec, Spec Kit, and cc-sdd
experiments. Any later SDD installation or source modification must occur
only in its corresponding task-scoped repository and container.
