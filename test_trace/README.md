# Test Trace

A project-independent Python collector for **per-test-body coverage of named
source functions and observed Python call graphs**. The first adapter uses
pytest, including standard unittest cases collected by pytest. There are no
Scrapy, reactor, repository-name or model-provider branches in the core.

The implementation takes inspiration from IssueExec's per-test profiling and
function graph representation. It independently records coverage nodes, uses
real parent frames instead of a filtered caller stack, preserves external
Python/C boundaries, and pins source and runtime identities.

## Run

Create a configuration outside the analyzed repository:

```json
{
  "repository": "/path/to/project",
  "output": "/path/to/evidence/run-001",
  "base_sha": "<optional Git base SHA; required by the SDD adapter>",
  "runtime": {
    "kind": "docker",
    "image": "sha256:<caller-provided test image>",
    "python": "python3",
    "network": "none",
    "cpus": 1,
    "memory": "2g",
    "env": {"PYTHONHASHSEED": "0"}
  },
  "test_paths": ["tests"],
  "production_roots": ["src/library"],
  "source_mappings": [],
  "pytest_args": [],
  "workers": 1,
  "timeout_seconds": 120,
  "collection_timeout_seconds": 300,
  "budget_seconds": 3600,
  "raw_events": false
}
```

Paths in `repository` and `output` are resolved relative to the configuration.
Output must be outside the analyzed repository. Production roots are explicitly
declared source ranges, not predictions of which functions need editing.
Project pytest configuration is retained. Retries, xdist and pytest-cov are
disabled to preserve one-execution attribution. If project addopts need an
override, set the explicit, pinned `pytest_addopts` string.

For mechanism checks or an already isolated caller-owned environment, use
`{"kind":"local","python":"/path/to/venv/bin/python"}`. The runner does not
install dependencies, construct test environments, access gold, or call models.
The test interpreter needs pytest; the coordinator and reader use only the
standard library.

An optional top-level `worker_root` selects a separate directory for disposable
worker repositories and homes, for example an executable host tmpfs directory.
Every execution still receives a fresh copied source tree and a fresh process;
durable instance records, diagnostics and frozen bundles stay under `output`.
Use a unique scratch root per run. The caller supplies its capacity and cleans
up only after workers exit. Scratch must not contain the durable output or be
inside the analyzed source. This changes storage location, not capture scope.

```bash
python3 -m test_trace discover --config /path/to/config.json
python3 -m test_trace collect --config /path/to/config.json
python3 -m test_trace resume --config /path/to/config.json
python3 -m test_trace summary --root /path/to/evidence/run-001
python3 -m test_trace tests --root /path/to/evidence/run-001 --limit 50
python3 -m test_trace show --root /path/to/evidence/run-001 'tests/test_api.py::Case.test_api'
python3 -m test_trace reverse --root /path/to/evidence/run-001 'src/library/api.py::parse'
python3 -m test_trace export --root /path/to/evidence/run-001 'tests/test_api.py::Case.test_api' --output /path/to/view.html
python3 -m test_trace bundle --root /path/to/evidence/run-001 --output /path/to/frozen-bundle
python3 -m test_trace verify --root /path/to/frozen-bundle
```

Use a single coordinator for each output directory. Resume skips all recorded
terminal instances, including failures: it does not silently retry them. New
source, environment, collection policy, timeout or collector code requires a
new output directory. Worker count and the next invocation's execution budget
may change during a later resume. The budget applies to execution scheduling
after discovery; environment startup and source-copy overhead are separately
bounded and can add wall time.

## Identities and semantics

The immutable source snapshot is hashed before collection and copied into a
private master. Individual executions use fresh copies and fresh processes.
Container workers are pooled; containers themselves are not recreated after
every successful test. Test subprocess groups are cleaned after each instance.
The test working directory and source import path refer to the copied snapshot.

Each runtime item keeps its original nodeid, including parameters and inherited
execution aliases. `source_test_id` is the actual defining
`repository-relative/path.py::Class.method`, resolved from code and AST rather
than runtime `self.__class__`. Unresolvable identities remain explicitly unknown.

If an environment executes an installed copy of project code, the caller can
provide `source_mappings` entries with `runtime_root` and `repository_root`.
The latter is repository-relative. Files must match the snapshot hash; changed
files invalidate evidence, and newly generated code is excluded and labelled.
The snapshot also records executable permission bits.

Collection starts on actual entry into the verified source test body, not at
the start of pytest's entire call phase. Pytest setup/teardown, dynamic fixture
requests, unittest setup/teardown and cleanup, and decorator pre/post code are
excluded. Plain helper calls from the body are retained. Every covered named
definition becomes a node, even without an internal incoming edge.

Edges describe observed Python parents. External intermediaries are not
collapsed into false internal direct edges. External Python/C boundaries are
stored separately. An unindexed project scope (for example a class body or
lambda) is also an opaque boundary; a boundary is not necessarily third-party
code. Graphs can have cycles, several roots and disconnected
components. Async generator/coroutine suspension is distinguished from final
return; source ownership and call edges remain separate concepts.

Only passing instances with verified identity/body boundaries and no capture
errors enter formal graphs. Other outcomes keep status and host diagnostics;
their coverage is unknown, not an empty set. Methods aggregate passing instances
with explicit `complete`, `partial`, or `unavailable` coverage status. For
unavailable methods `covered_functions` is JSON `null`. A graph edge's count is
the number of observed profile call events, including relevant resumes, not a
statement about high-level business invocations.

`production_covered_functions` means covered named definitions inside the
caller's production roots, with recognized test/fixture sources excluded. It
does not establish assertion dependence or update necessity.

## Stored data

The host run stores `run.json`, `collection.json`, per-instance results,
per-method aggregates, the symbol table, forward/reverse indexes, progress,
logs, and separate diagnostics. Optional raw events remain host-side. Public
bundles contain a manifest with complete file hashes, the standard-library
reader, index, formal graphs, and status-only records for unavailable instances.
Existing bundles are never overwritten.

Default query views bound graph nodes and report omissions; the complete
coverage set and graph stay on disk. `show --max-nodes 0` returns the full graph.
`export` creates standalone SVG or zoomable HTML with view limits shown.

## Runtime limits

The profile backend is capability-gated to CPython 3.10–3.13; mechanism tests have
been executed on CPython 3.11 and 3.12. Other interpreters are not silently
treated as supported. Existing profilers are preserved and cause capture to be
refused. Async execution requires whatever pytest adapter the caller's project
normally uses; arbitrary custom pytest items are explicitly unsupported.

Lambda, comprehension, module and generated code are not named source-function
nodes. Instrumented threads without proven ownership and subprocess code are
not added to certain coverage. A synchronous test returning an awaitable or
Deferred may finish its lexical body before its continuation executes: such
continuations are outside this `test_body_only` scope. Fixtures and their
background work do not become test-body evidence just because they run nearby.
See the machine-readable limitations on each result.

Independent per-instance execution repeats module/session fixtures and may
expose tests that depend on suite order. Collection or infrastructure errors
are retained. `dataset_complete` requires both complete discovery and a terminal
record for every discovered instance; it does not mean that every test passed.

## Three-SDD adapter

`sdd-bench/scrapy-sdd/batch/dynamic_trace.py` verifies a caller-generated public
bundle. Experiment v2 accepts a parallel optional input:

```json
{
  "dynamic_trace": {
    "entrypoint": "test-traces/README.md",
    "artifacts": {
      "<base_sha>": {"path": "<relative-path>/manifest.json", "sha256": "<hash>"}
    }
  }
}
```

Fresh scaffolding copies the same bundle into each method's `test-traces/`
before workspace hashing, pins `dynamic-trace.json`, and rechecks bytes before
Detect. Trace-only and combined test-intention/trace configurations are supported.
The reader imports neither pytest nor the collector. Agents still do not run
tests; all existing tests remain searchable and missing traces never exclude
them. Historical rounds are not rewritten.

## Verification

```bash
python3 -m unittest -v tests.test_test_trace_collector
TEST_TRACE_TEST_PYTHON=/path/to/python-with-pytest python3 -m unittest -v tests.test_test_trace
PYTHONPATH=sdd-bench/scrapy-sdd python3 -m unittest -v batch.tests.test_dynamic_trace batch.tests.test_test_intention
```

Collector tests require pytest in the executing environment. End-to-end tests
exercise flat-package and src-layout projects, parameter aggregation, unittest,
failure isolation, bundle tamper detection, source drift and nonrecursive export.
