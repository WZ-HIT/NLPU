# Detect planning notes: PR 7966 "Address warnings from the VCS workflow"

Method: cc-sdd (Detect stage). Phases covered in this run: `spec` (this note) and `detect`
(`detection-draft.json`). No project code or tests were modified and no tests were run.

## Spec phase

Repository: `scrapy/scrapy`, base commit `5427080f4892fb8f33cc159fdcd6f8ce8d4c140e`.
Pull request: 7966, titled "Address warnings from the VCS workflow" (empty body).

What "VCS workflow" means in this repository:

- `.github/workflows/tests-vcs-deps.yml` (workflow name "VCS dependencies") runs on a schedule
  and installs development versions of Scrapy's dependencies.
- The workflow sets `TOXENV: vcs-deps`, and `tox.ini` defines `[testenv:vcs-deps]`, which
  starts from the `extra-deps` environment and then force-reinstalls a long list of
  dependencies from `git+https://…` with `uv pip install --no-deps --reinstall`
  (Twisted, pyOpenSSL, cryptography, Pillow, uvloop, lxml, parsel, w3lib, itemadapter,
  itemloaders, cssselect, protego, queuelib, tldextract, packaging, service-identity,
  zope.interface, boto3, brotli, brotlicffi, python-storage, httpx2, ipython, ptpython,
  zstandard).
- The job runs on Python 3.14 with `PYTEST_ADDOPTS: -n auto --no-cov --timeout=120`, i.e. the
  full test suite against unreleased dependency builds.

Consequence: the warnings surfaced by this workflow can only come from (a) development builds
of dependencies, and (b) interpreter-version (3.14) behavior. The relevant code in the tree is
the dependency-compatibility layer and the tests that assert on warnings:

- `scrapy/utils/_deps_compat.py` is the single place that encodes dependency-version gates
  currently consumed by `scrapy/pipelines/media.py`, `scrapy/core/downloader/contextfactory.py`,
  `scrapy/utils/ssl.py` and several test modules.
- Warning-sensitive test code exists around deprecations and around imports of deprecated
  modules (`scrapy.mail`, `scrapy.extensions.statsmailer`, `scrapy.interfaces`,
  `scrapy/core/downloader/handlers/http.py`).

Repository-relative location for all planning artifacts of this method/stage:
`/workspace/.kiro/specs` (the mounted planning directory). The single detection draft lives at
`/workspace/.kiro/specs/detection-draft.json`.

## Detect phase

Detection was performed statically: the workflow and tox environment were inspected to
establish which dependency builds and interpreter are in play, then the test tree was searched
for files that (1) assert on warning emission or suppression, and (2) branch on dependency or
interpreter versions, since those are the only tests whose outcome can change when the VCS
workflow resolves newer builds.

Selection rules applied:

- prefer tests that assert on warnings (`pytest.warns`, `filterwarnings`, `simplefilter`)
  or that assert a warning must not occur;
- prefer shared test bases and fixtures that build TLS/pyOpenSSL and stdlib-parser objects,
  because they are exercised across many download handlers;
- prefer tests gated by `scrapy.utils._deps_compat`, `sys.version_info`, or runtime library
  version parsing.

Candidates are listed with the symbols most likely to change. Confidence: medium. The PR body
is empty and the upstream patch was not available in the workspace, so the draft is inferred
from the workflow/environment definition rather than from the diff.

Loose ends deliberately not included as candidates: `tests/test_dependencies.py` (guards the
`min` environment, not the VCS one), `tests/test_toplevel.py` and other version-agnostic tests.
