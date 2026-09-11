# Scrapy SDD Baseline — Working Log

> **Scope:** Steps 07–12 of the 18-step baseline workflow  
> **State:** Shared image built; three isolated repositories and containers running  
> **Recorded:** 2026-09-05T04:49:03Z  
> **Previous log:** <code>scrapy-pr8073-test-only-600152fbc76dd5ba-steps-01-06.md</code>

## At a Glance

| Item | Value |
|---|---|
| Progress | **12 / 18 steps complete** |
| Host | <code>Mercury</code> |
| Operator UID:GID | <code>1007:1007</code> |
| Repository | <code>scrapy/scrapy</code> |
| Pull request | <code>8073</code> |
| Task ID | <code>scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| Task base SHA | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Shared image tag | <code>scrapy-sdd-scrapy:base-11079cb1c85b-py311</code> |
| Shared image ID | <code>sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Runtime | CPython <code>3.11.15</code> on <code>linux/amd64</code> |
| Experiment repositories | 3 independent shallow clones |
| Git worktrees | All clean at the task base SHA |
| Containers | 3 running, 0 restarts |
| SDD tools | Not installed or initialized |
| Smoke tests | Not started |
| Next step | Step 13 — runtime equality and isolation audit |

## Runtime Topology

~~~mermaid
flowchart TB
    B["Immutable baseline<br/>one shallow commit<br/>no remote"]
    I["Shared task image<br/>Python 3.11.15<br/>69 installed packages"]

    B --> O["OpenSpec repository<br/>experiment/openspec"]
    B --> S["Spec Kit repository<br/>experiment/speckit"]
    B --> C["cc-sdd repository<br/>experiment/cc-sdd"]

    I --> OC["OpenSpec container"]
    I --> SC["Spec Kit container"]
    I --> CC["cc-sdd container"]

    O -->|"bind mount /workspace"| OC
    S -->|"bind mount /workspace"| SC
    C -->|"bind mount /workspace"| CC

    OH["openspec-home"] --> OC
    SH["speckit-home"] --> SC
    CH["cc-sdd-home"] --> CC
~~~

The arrows from the baseline to the experiment repositories describe their
creation history only. After cloning, there is no live Git relationship:
the repositories have no remotes, alternates, or hard-linked Git objects.

## Isolation Matrix

| Resource | Shared | Isolation mechanism |
|---|---:|---|
| Docker image | Yes | One immutable image ID for all three services |
| Scrapy worktree | No | Three different host bind-mount sources |
| Git object store | No | <code>--no-hardlinks</code>; no alternates |
| Container writable layer | No | Docker creates one layer per container |
| Home directory and cache | No | Three task-scoped named volumes |
| <code>/tmp</code> | No | One tmpfs instance per container |
| <code>.venv</code> and <code>.tox</code> | No | Independent worktrees or container-local temporary storage |
| Network | Disabled | <code>network_mode: none</code> |

## Key Paths

| Purpose | Path |
|---|---|
| Immutable baseline | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy</code> |
| Dockerfile | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/docker/Dockerfile</code> |
| Task root | <code>/home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba</code> |
| OpenSpec repository | <code>runs/openspec/scrapy</code> |
| Spec Kit repository | <code>runs/speckit/scrapy</code> |
| cc-sdd repository | <code>runs/cc-sdd/scrapy</code> |
| Compose file | <code>compose.yaml</code> |

## Progress Summary

| Step | Purpose | Result | Files manually authored |
|---:|---|---|---:|
| 07 | Build the shared task image | Complete | 0 |
| 08 | Create the OpenSpec repository | Complete | Git materialization |
| 09 | Create the Spec Kit repository | Complete | Git materialization |
| 10 | Create the cc-sdd repository | Complete | Git materialization |
| 11 | Define the isolated Compose runtime | Complete | 1 |
| 12 | Start the three containers | Complete | Docker runtime objects only |

---

## Step 07 — Build the Shared Task Image

### Purpose

Build one dependency image for the task base SHA and use that exact image for
all three SDD experiments. No SDD implementation is included in the image.

### Image Artifact

| Item | Value |
|---|---|
| Image tag | <code>scrapy-sdd-scrapy:base-11079cb1c85b-py311</code> |
| Image ID | <code>sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Local RepoDigest | <code>scrapy-sdd-scrapy@sha256:f59cdcb1f1be58c9ee0becf4eff13ea4979aea617aa5bf2c4619ae2c13c4adfa</code> |
| Created | <code>2026-09-04T08:57:41.897770197Z</code> |
| Platform | <code>linux/amd64</code> |
| Size | <code>118,589,804 bytes</code> |
| Runtime user | <code>bench</code>, UID:GID <code>1007:1007</code> |
| Python | <code>3.11.15</code> |
| Git | <code>2.47.3</code> |
| Installed package count | <code>69</code> |
| Normalized freeze SHA-256 | <code>570e1651694fe0e30bbd07a231c2f70cccf09cd18503b8ead34fdfd50f5f3abd</code> |
| <code>pip check</code> | No broken requirements |
| SDD commands | <code>openspec</code>, <code>specify</code>, and <code>cc-sdd</code> absent |

The image labels bind it to repository <code>scrapy/scrapy</code> and the
full base SHA <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code>.

<details>
<summary><strong>Successful build command</strong></summary>

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
<summary><strong>Image validation commands</strong></summary>

~~~bash
docker image inspect \
  scrapy-sdd-scrapy:base-11079cb1c85b-py311

docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp \
  scrapy-sdd-scrapy:base-11079cb1c85b-py311 \
  python --version

docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp \
  scrapy-sdd-scrapy:base-11079cb1c85b-py311 \
  python -m pip check

docker run --rm \
  --network none \
  --read-only \
  --tmpfs /tmp \
  scrapy-sdd-scrapy:base-11079cb1c85b-py311 \
  python -m pip freeze --all
~~~

</details>

<details>
<summary><strong>Resolved package set — 69 entries</strong></summary>

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

> **Build note:** One approval request expired without executing a build.
> A later build process was interrupted before it produced the target image.
> The final build completed successfully, reusing valid build cache. Neither
> earlier attempt left a target image or changed the baseline worktree.

## Step 08 — Create the OpenSpec Repository

### Purpose

Create a physically independent Git repository for the OpenSpec experiment,
place it on its own branch, and remove all configured remote access.

### Result

| Check | Result |
|---|---|
| Path | <code>runs/openspec/scrapy</code> |
| Branch | <code>experiment/openspec</code> |
| HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Git tree | <code>0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2</code> |
| Reachable commits | <code>1</code> |
| Shallow repository | Yes |
| Remotes / remote refs | <code>0 / 0</code> |
| Alternates / hard-linked objects | Absent / <code>0</code> |
| <code>.venv</code> / <code>.tox</code> | Absent / absent |
| Worktree | Clean |

<details>
<summary><strong>Executed commands</strong></summary>

~~~bash
git clone \
  --no-hardlinks \
  --no-tags \
  --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy \
  switch --create experiment/openspec \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/openspec/scrapy \
  remote remove origin
~~~

</details>

The <code>--no-hardlinks</code> option copied Git objects instead of linking
them to the baseline. The absence of
<code>.git/objects/info/alternates</code> confirms there is no object-store
fallback to another repository.

## Step 09 — Create the Spec Kit Repository

### Purpose

Create the second independent repository from the same immutable baseline,
using only a different experiment branch name.

### Result

| Check | Result |
|---|---|
| Path | <code>runs/speckit/scrapy</code> |
| Branch | <code>experiment/speckit</code> |
| HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Git tree | <code>0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2</code> |
| Reachable commits | <code>1</code> |
| Shallow repository | Yes |
| Remotes / remote refs | <code>0 / 0</code> |
| Alternates / hard-linked objects | Absent / <code>0</code> |
| Worktree | Clean |

<details>
<summary><strong>Executed commands</strong></summary>

~~~bash
git clone \
  --no-hardlinks \
  --no-tags \
  --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy \
  switch --create experiment/speckit \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/speckit/scrapy \
  remote remove origin
~~~

</details>

The baseline, OpenSpec, and Spec Kit repositories had identical Git tree
IDs after this step.

## Step 10 — Create the cc-sdd Repository

### Purpose

Complete the three-way experiment layout with an independently stored cc-sdd
repository.

### Result

| Check | Result |
|---|---|
| Path | <code>runs/cc-sdd/scrapy</code> |
| Branch | <code>experiment/cc-sdd</code> |
| HEAD | <code>11079cb1c85b9e75a39a7269943c69d1a975d485</code> |
| Git tree | <code>0b9ebb13cca2038ecf5f84ba1f3e7efd6e1cebf2</code> |
| Reachable commits | <code>1</code> |
| Shallow repository | Yes |
| Remotes / remote refs | <code>0 / 0</code> |
| Alternates / hard-linked objects | Absent / <code>0</code> |
| Worktree | Clean |

<details>
<summary><strong>Executed commands</strong></summary>

~~~bash
git clone \
  --no-hardlinks \
  --no-tags \
  --no-checkout \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/environments/scrapy__scrapy__base_11079cb1c85b9e75a39a7269943c69d1a975d485/baseline/scrapy \
  /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy \
  switch --create experiment/cc-sdd \
  11079cb1c85b9e75a39a7269943c69d1a975d485

git -C /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/runs/cc-sdd/scrapy \
  remote remove origin
~~~

</details>

### Three-Repository Equality Check

| Repository | Branch | HEAD | Tree | Status |
|---|---|---|---|---|
| OpenSpec | <code>experiment/openspec</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |
| Spec Kit | <code>experiment/speckit</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |
| cc-sdd | <code>experiment/cc-sdd</code> | <code>11079cb…d485</code> | <code>0b9ebb…bf2</code> | Clean |

Every repository contains exactly one reachable commit and has no Git
remote. The branch name is the only intended Git-state difference.

## Step 11 — Create the Compose Definition

### Purpose

Describe three container services that share the exact image while keeping
their repositories, home directories, caches, temporary files, and writable
container state separate.

### Artifact

| Item | Value |
|---|---|
| File | <code>tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml</code> |
| SHA-256 | <code>08050666f6026bc59b0fa51f435496903f01dd294e8da240e01b7fcd351f48a7</code> |
| Compose project | <code>scrapy-sdd-8073-600152fbc76dd5ba</code> |
| Services | <code>openspec</code>, <code>speckit</code>, <code>cc-sdd</code> |
| Manually authored files | <code>1</code> |

### Design Decisions

- A YAML anchor holds the common image and runtime configuration.
- <code>pull_policy: never</code> and the absence of a build section prevent
  an implicit image replacement.
- Each service binds a different repository to <code>/workspace</code>.
- Each service mounts a different named volume at <code>/home/bench</code>.
- Each service receives its own tmpfs at <code>/tmp</code>.
- The image root filesystem is read-only; only declared mounts are writable.
- Networking is disabled.
- <code>sleep infinity</code> keeps each container running for later,
  repeatable <code>docker compose exec</code> commands.

<details>
<summary><strong>Authored Compose definition</strong></summary>

~~~yaml
name: scrapy-sdd-8073-600152fbc76dd5ba

x-scrapy-common: &scrapy-common
  image: scrapy-sdd-scrapy:base-11079cb1c85b-py311
  pull_policy: never
  init: true
  user: "1007:1007"
  working_dir: /workspace
  read_only: true
  network_mode: none
  command: ["sleep", "infinity"]
  environment:
    HOME: /home/bench
    PIP_CACHE_DIR: /tmp/pip-cache
    PYTHONPYCACHEPREFIX: /tmp/pycache
    TOX_WORK_DIR: /tmp/tox
    XDG_CACHE_HOME: /home/bench/.cache
  tmpfs:
    - /tmp:rw,nosuid,nodev,mode=1777

services:
  openspec:
    <<: *scrapy-common
    container_name: scrapy-sdd-8073-600152fbc76dd5ba-openspec
    volumes:
      - type: bind
        source: ./runs/openspec/scrapy
        target: /workspace
      - type: volume
        source: openspec-home
        target: /home/bench

  speckit:
    <<: *scrapy-common
    container_name: scrapy-sdd-8073-600152fbc76dd5ba-speckit
    volumes:
      - type: bind
        source: ./runs/speckit/scrapy
        target: /workspace
      - type: volume
        source: speckit-home
        target: /home/bench

  cc-sdd:
    <<: *scrapy-common
    container_name: scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd
    volumes:
      - type: bind
        source: ./runs/cc-sdd/scrapy
        target: /workspace
      - type: volume
        source: cc-sdd-home
        target: /home/bench

volumes:
  openspec-home: {}
  speckit-home: {}
  cc-sdd-home: {}
~~~

</details>

<details>
<summary><strong>Static validation commands</strong></summary>

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  config --quiet

docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  config --format json

docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  ps --all --quiet
~~~

</details>

Static validation confirmed three distinct bind sources and three distinct
home-volume sources. At the end of Step 11, zero containers and zero volumes
had been created.

## Step 12 — Start the Three Containers

### Purpose

Create the task-scoped runtime objects from the validated Compose definition,
without rebuilding or pulling the shared image.

### Executed Command

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  up --detach --no-build --pull never
~~~

### Container Result

| Service | Container ID | State | Restarts |
|---|---|---|---:|
| OpenSpec | <code>45b8fc24bfb7e6281f131be7feea90412cfdea6ac6bc6dcba36f83edcd43af66</code> | Running | 0 |
| Spec Kit | <code>4f4bde7b4e805ff1dbf465f92d2ce01b311c086172a4897c117546f937de4e29</code> | Running | 0 |
| cc-sdd | <code>1da7d3fc1d5ee47ed1475f61c96f242ace18b71b58b217d45b958a71aaed3981</code> | Running | 0 |

### Created Home Volumes

~~~text
scrapy-sdd-8073-600152fbc76dd5ba_openspec-home
scrapy-sdd-8073-600152fbc76dd5ba_speckit-home
scrapy-sdd-8073-600152fbc76dd5ba_cc-sdd-home
~~~

All three containers use <code>sleep infinity</code> as their configured
command. Their PID 1 processes are live, and no container has restarted.

<details>
<summary><strong>Runtime-state validation commands</strong></summary>

~~~bash
docker compose \
  -f /home/wangzuohit/NLPU/sdd-bench/scrapy-sdd/tasks/scrapy__scrapy__8073__test_only__600152fbc76dd5ba/compose.yaml \
  ps --all

docker inspect \
  scrapy-sdd-8073-600152fbc76dd5ba-openspec \
  scrapy-sdd-8073-600152fbc76dd5ba-speckit \
  scrapy-sdd-8073-600152fbc76dd5ba-cc-sdd

docker volume ls \
  --filter label=com.docker.compose.project=scrapy-sdd-8073-600152fbc76dd5ba
~~~

</details>

> **Display note:** Compose printed some volume progress events twice while
> starting services concurrently. Docker's object inventory was checked
> afterward and contains exactly three containers and three home volumes.

No smoke test ran during this step, and no SDD tool was installed or
initialized.

---

## Current Safety Invariants

- [x] All three repositories start at the exact task base SHA.
- [x] All three repositories have the same Git tree and one reachable commit.
- [x] All three repositories are shallow, clean, and have no remotes.
- [x] Git objects are neither hard-linked nor accessed through alternates.
- [x] The baseline remained detached, remote-free, and clean.
- [x] One immutable image is selected for all three services.
- [x] The image contains Scrapy test dependencies but no SDD tool.
- [x] The three repository bind mounts use different host paths.
- [x] The three home volumes have different task-scoped names.
- [x] Three containers are running with zero restarts.
- [ ] Cross-container image, Python, dependency, mount, and cache equality has been audited.
- [ ] The three smoke tests have been executed and compared.

## Next Step — 13

Perform a read-only cross-container audit:

| Comparison | Required outcome |
|---|---|
| Image ID | Identical in all three containers |
| Python version and executable | Identical |
| Installed package count and normalized hash | Identical |
| <code>pip check</code> | Pass in all three containers |
| <code>/workspace</code> source | Different and correct for each service |
| <code>/home/bench</code> volume | Different for each service |
| <code>/tmp</code> | Independent tmpfs per container |
| Mount namespace | Different for each container |
| Root filesystem, network, and user | Identical configuration |
| <code>.venv</code>, <code>.tox</code>, and SDD commands | Absent |
| Git status | Clean in all three repositories |

Smoke tests remain intentionally deferred to Steps 14–16.
