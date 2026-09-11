# Scrapy SDD Baseline Manifest

> **Status:** Complete and ready for SDD experiments  
> **Recorded:** 2026-09-06T06:33:19Z  
> **Workflow:** 18 / 18 baseline-preparation steps  
> **SDD tools:** Not installed or initialized

## Task Identity

| Field | Value |
|---|---|
| Repository | <code>scrapy/scrapy</code> |
| Prompt array index | <code>0</code> |
| Sample ID / Task ID | <code>scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| Pull request | <code>8073</code> |
| Task base SHA | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Base commit subject | <code>Remote control extension. (#7866)</code> |
| Base commit time | <code>2026-08-21T17:56:41+05:00</code> |
| Git tree | <code>0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2</code> |

The task identity was read from the top-level fields of prompt object
<code>0</code>. The base SHA was resolved from the matching top-level raw PR
record using <code>(repo, pr_id)</code>; identity was not parsed from the
natural-language prompt body.

## Input Provenance

| Input | SHA-256 |
|---|---|
| <code>/home/wangzuohit/NLPU/output/prompt/scrapy__scrapy.json</code> | <code>76867cef42647720db0c052963ff9ae0f7db8de41f821cca1773cab5ecdd1c76</code> |
| <code>/home/wangzuohit/NLPU/output/raw_prs/scrapy__scrapy.jsonl</code> | <code>4cf2d27621963dc79b413f84b4c04e3a5a4fbd1e540c682be6d3e9c15dd239e1</code> |

### Baseline Reuse Policy

| Metric | Count |
|---|---:|
| Test-case prompt records | 1,245 |
| Unique pull requests | 98 |
| Unique task base SHAs | 75 |
| Prompt records for PR 8073 | 3 |

Immutable baselines and dependency images are keyed by the full base SHA and
may be reused. Git worktrees, containers, home volumes, temporary storage,
and caches remain sample-specific.

## Host Environment

| Item | Value |
|---|---|
| Host | <code>Mercury</code> |
| Kernel | <code>Linux 6.8.0-137-generic x86_64 GNU/Linux</code> |
| Operator UID:GID | <code>1007:1007</code> |
| Host Git | <code>2.43.0</code> |
| Docker Engine | <code>29.7.1</code> |
| Docker Compose | <code>5.4.0</code> |

## Final Directory Tree

~~~text
/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/
├── Log/
│   ├── scrapy-pr8073-test-only-600152fbc76dd5ba-steps-01-06.md
│   ├── scrapy-pr8073-test-only-600152fbc76dd5ba-steps-07-12.md
│   └── scrapy-pr8073-test-only-600152fbc76dd5ba-steps-13-18.md
├── environments/
│   └── scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/
│       ├── baseline/
│       │   └── scrapy/
│       │       ├── .git/
│       │       ├── scrapy/
│       │       ├── tests/
│       │       ├── pyproject.toml
│       │       └── tox.ini
│       └── docker/
│           └── Dockerfile
└── tasks/
    └── scrapy__scrapy__8073__test_only__600152fbc76dd5ba/
        ├── compose.yaml
        ├── results/
        │   └── baseline-manifest.md
        └── runs/
            ├── openspec/
            │   └── scrapy/
            │       ├── .git/
            │       ├── scrapy/
            │       ├── tests/
            │       ├── pyproject.toml
            │       └── tox.ini
            ├── speckit/
            │   └── scrapy/
            │       ├── .git/
            │       ├── scrapy/
            │       ├── tests/
            │       ├── pyproject.toml
            │       └── tox.ini
            └── cc-sdd/
                └── scrapy/
                    ├── .git/
                    ├── scrapy/
                    ├── tests/
                    ├── pyproject.toml
                    └── tox.ini
~~~

## Git Baseline and Run Repositories

| Repository | Branch state | HEAD | Reachable commits | Shallow | Remotes | Status |
|---|---|---|---:|---:|---:|---|
| Baseline | Detached HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> | 1 | Yes | 0 | Clean |
| OpenSpec | <code>experiment/openspec</code> | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> | 1 | Yes | 0 | Clean |
| Spec Kit | <code>experiment/speckit</code> | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> | 1 | Yes | 0 | Clean |
| cc-sdd | <code>experiment/cc-sdd</code> | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> | 1 | Yes | 0 | Clean |

All four repositories have tree
<code>0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2</code>. The three run
repositories have no remote-tracking refs, object alternates, or hard-linked
Git objects. Their branch names are the only intended starting-state
difference.

### Required Paths

The following exist in the baseline and every run repository:

- <code>scrapy/</code>
- <code>tests/</code>
- <code>pyproject.toml</code>
- <code>tox.ini</code>

No run repository contains <code>.venv</code>, <code>.tox</code>, or
<code>.pytest_cache</code>.

## Shared Docker Image

| Item | Value |
|---|---|
| Tag | <code>scrapy-sdd-scrapy:base-11079cb1c85b-py311</code> |
| Image ID | <code>sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Local RepoDigest | <code>scrapy-sdd-scrapy@sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Base image | <code>python:3.11-slim@sha256:94c50be2dc994b873b55bc123e95e6dbade08095b3dfd790f51c34de3f08cbb7</code> |
| Created | <code>2026-09-04T08:57:41.897770197Z</code> |
| Platform | <code>linux/amd64</code> |
| Size | <code>118,589,804 bytes</code> |
| Runtime user | <code>bench</code> |
| Label: repository | <code>scrapy/scrapy</code> |
| Label: base SHA | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Label: purpose | <code>Scrapy SDD test baseline</code> |

| Artifact | SHA-256 |
|---|---|
| Dockerfile | <code>a75e587e9a27dc05f7fce5fae3430e17fd9e29d123366790ca0eb5d23d15bc71</code> |
| Compose definition | <code>08050666f6026bc59b0fa51f435496903f01dd294e8da240e01b7fcd351f48a7</code> |

## Container Runtime Equality

| Check | Common result |
|---|---|
| Actual image ID | <code>sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Python | <code>3.11.15</code> |
| Python executable | <code>/usr/local/bin/python</code> |
| Container Git | <code>2.47.3</code> |
| Runtime UID:GID | <code>1007:1007</code> |
| Installed packages | 69 |
| Sorted freeze SHA-256 | <code>570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd</code> |
| <code>pip check</code> | No broken requirements |
| Root filesystem | Read-only |
| Network mode | <code>none</code> |
| Command | <code>sleep infinity</code> |
| SDD commands | <code>openspec</code>, <code>specify</code>, and <code>cc-sdd</code> absent |

<details>
<summary><strong>Complete normalized package set</strong></summary>

~~~text
Automat==25.4.16
Incremental==24.11.0
Protego==0.6.2
PyDispatcher==2.0.7
Pygments==2.21.0
Scrapy @ file:///opt/scrapy-source
Twisted==26.4.0
aiohappyeyeballs==2.7.1
aiohttp==3.14.3
aiosignal==1.4.0
anyio==4.15.0
attrs==26.1.0
backports.zstd==1.7.0
brotli==1.2.0
certifi==2026.7.22
cffi==2.1.1
charset-normalizer==3.5.1
constantly==23.10.4
coverage==7.16.0
cryptography==50.0.1
cssselect==1.5.0
decorator==5.3.1
defusedxml==0.7.1
execnet==2.1.2
filelock==3.32.5
frozenlist==1.8.0
greenlet==3.5.5
h11==0.16.0
httpcore2==2.12.0
httpx2==2.12.0
hyperlink==21.0.0
idna==3.19
iniconfig==2.3.0
itemadapter==0.13.1
itemloaders==1.4.0
jmespath==1.1.0
lxml==6.1.3
multidict==6.7.1
packaging==26.3
parsel==1.11.0
pexpect==4.9.0
pip==24.0
platformdirs==4.11.7
pluggy==1.6.0
propcache==0.5.2
ptyprocess==0.7.0
pyOpenSSL==26.4.0
pycparser==3.0
pyftpdlib==2.2.0
pytest-cov==7.1.0
pytest-rerunfailures==16.6.1
pytest-timeout==2.4.0
pytest-twisted==1.14.3
pytest-xdist==3.8.0
pytest==9.1.1
queuelib==1.10.0
requests-file==3.0.1
requests==2.34.2
service-identity==26.1.0
setuptools==79.0.1
sybil==10.1.0
tldextract==5.3.2
truststore==0.10.4
typing_extensions==4.16.0
urllib3==2.7.0
w3lib==2.4.1
wheel==0.46.3
yarl==1.24.5
zope.interface==8.6
~~~

</details>

## Container and Mount Isolation

| Service | Container ID | Workspace bind source | Home volume | Mount namespace |
|---|---|---|---|---|
| OpenSpec | <code>45b8fc24bfb7e6281f131be7feea90412cfdea6ac6bc6dcba36f83edcd43af66</code> | <code>runs/openspec/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_openspec-home</code> | <code>mnt:[4026536581]</code> |
| Spec Kit | <code>4f4bde7b4e805ff1dbf465f92d2ce01b311c086172a4897c117546f937de4e29</code> | <code>runs/speckit/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_speckit-home</code> | <code>mnt:[4026538623]</code> |
| cc-sdd | <code>1da7d3fc1d5ee47ed1475f61c96f242ace18b71b58b217d45b958a71aaed3981</code> | <code>runs/cc-sdd/scrapy</code> | <code>scrapy-sdd-8073-600152fbc76dd5ba_cc-sdd-home</code> | <code>mnt:[4026538596]</code> |

Every container is running with zero restarts. Each has a private tmpfs at
<code>/tmp</code> using
<code>rw,nosuid,nodev,mode=1777</code>. The baseline is not mounted into any
experiment container.

The containers share the host kernel and immutable image layers, but they do
not share experiment worktrees, Git metadata, writable container layers,
home volumes, temporary storage, or cache state. No Docker socket is mounted.

## Smoke Test

### Command

The same command was run once in each service:

~~~bash
python -m pytest \
  -q \
  -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics
~~~

### Results

| Service | Exit code | Pytest result | Pytest duration | Docker exec wall time |
|---|---:|---|---:|---:|
| OpenSpec | 0 | 1 passed | 0.17s | 2,648ms |
| Spec Kit | 0 | 1 passed | 0.17s | 2,260ms |
| cc-sdd | 0 | 1 passed | 0.17s | 2,264ms |

The wall-time difference reflects container-command scheduling overhead and
is not treated as a test-performance result.

The smoke test exercises in-memory
<code>scrapy.http.Headers</code> construction, missing-header behavior, and
normalization of default values to bytes. It requires no network, external
service, filesystem fixture, or Twisted reactor.

## Core Commands Executed

The state-changing and test commands are recorded below in full. Read-only
assertions and their outputs are expanded in the three task-specific working
logs listed under Supporting Logs.

<details>
<summary><strong>Resolve the task and create the skeleton</strong></summary>

~~~bash
jq -r '.[0] | [.sample_id, .repo, (.pr_id | tostring)] | @tsv' \
  /home/wangzuohit/NLPU/output/prompt/scrapy__scrapy.json

jq -r '
  select(.repo == "scrapy/scrapy" and .pr_id == 8073)
  | .base_sha
' /home/wangzuohit/NLPU/output/raw_prs/scrapy__scrapy.jsonl

mkdir -p \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/results
~~~

</details>

<details>
<summary><strong>Materialize and disconnect the baseline</strong></summary>

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

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  remote remove origin
~~~

</details>

<details>
<summary><strong>Build the shared image</strong></summary>

~~~bash
docker build \
  --file /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker/Dockerfile \
  --build-arg BENCH_UID=1007 \
  --build-arg BENCH_GID=1007 \
  --tag scrapy-sdd-scrapy:base-11079cb1c85b-py311 \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy
~~~

</details>

<details>
<summary><strong>Create the three independent experiment repositories</strong></summary>

~~~bash
git clone --no-hardlinks --no-tags --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy \
  switch --create experiment/openspec \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy \
  remote remove origin

git clone --no-hardlinks --no-tags --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy \
  switch --create experiment/speckit \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy \
  remote remove origin

git clone --no-hardlinks --no-tags --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy \
  switch --create experiment/cc-sdd \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy \
  remote remove origin
~~~

</details>

<details>
<summary><strong>Start the isolated containers</strong></summary>

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  config --quiet

docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  up --detach --no-build --pull never
~~~

</details>

<details>
<summary><strong>Run the three smoke tests</strong></summary>

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T openspec \
  python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics

docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T speckit \
  python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics

docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  exec -T cc-sdd \
  python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/pytest-smoke \
  tests/test_http_headers.py::test_basics
~~~

</details>

## Supporting Logs

| Scope | File | SHA-256 at manifest time |
|---|---|---|
| Steps 01–06 | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-steps-01-06.md</code> | <code>ff8d4f634cd1a983596e03ee61a0cd49d7be354c5c1af8bb1a1aec7f465fafdb</code> |
| Steps 07–12 | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-steps-07-12.md</code> | <code>873faca594800abb7ec11f9e2a527e3bec935964f0b9986f188f7c4307c0cfd7</code> |
| Steps 13–18 | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/Log/scrapy-pr8073-test-only-600152fbc76dd5ba-steps-13-18.md</code> | Authored after this manifest snapshot |

## Final Audit

- [x] Task identity resolves uniquely to the full base SHA.
- [x] Baseline has one reachable commit, no remote, and a clean worktree.
- [x] Baseline files were not moved, renamed, or modified.
- [x] Three physically independent Git repositories exist.
- [x] Three experiment branches point to the same HEAD and tree.
- [x] All run worktrees are clean.
- [x] No run repository shares Git alternates or hard-linked objects.
- [x] One image ID, Python version, and dependency set is used everywhere.
- [x] Worktrees, home volumes, tmpfs instances, and mount namespaces differ.
- [x] All smoke commands and functional results are identical.
- [x] No OpenSpec, Spec Kit, or cc-sdd tool was installed or initialized.

The baseline environment is ready for the three SDD experiments.
