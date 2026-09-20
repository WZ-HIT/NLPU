## Context

See `proposal.md` for motivation. Current state that shapes the approach:

- `scrapy/utils/_compression.py` imports `zstandard` inside
  `contextlib.suppress(ImportError)` and `_unzstd()` builds a
  `zstandard.ZstdDecompressor()` and reads from `stream_reader(BytesIO(data))`
  in 64 KiB chunks, checking the decompressed size against `max_size` on every
  chunk. The module therefore has a hard runtime dependency on whichever zstd
  binding is importable, but no declared dependency requirement.
- `scrapy/downloadermiddlewares/httpcompression.py` decides whether zstd is
  supported with `importlib.util.find_spec("zstandard")` at import time and
  appends `b"zstd"` to `ACCEPTED_ENCODINGS` only if it is found. The
  unsupported-encoding warning appends "You need to install zstandard to
  decode 'zstd'." when zstd is among the undecodable encodings.
- `pyproject.toml` declares `zstd = ["zstandard>=0.16.0; implementation_name
  != 'pypy'"]` as an optional extra and requires Python >= 3.10. `tox.ini`
  installs `zstandard` (pinned, and from the git repository in the vcs-deps
  environment) for the test environments that need it.
- `tests/test_downloadermiddleware_httpcompression.py` contains the zstd
  coverage, guarded by a local `_skip_if_no_zstd()` helper
  (`pytest.importorskip("zstandard")`), plus
  `test_process_response_zstd_unsupported`, which asserts the old
  missing-dependency warning and only runs when `zstandard` is absent.

Both `compression.zstd` (Python 3.14+) and `backports.zstd` expose a
`ZstdDecompressor` with the streaming reader interface used here.

## Goals / Non-Goals

**Goals:**

- One import path for the zstd backend that always succeeds on every supported
  interpreter, so the middleware never has to guess whether zstd is supported.
- Keep `_unzstd(data, *, max_size=...)` behavior identical from the caller's
  point of view: streaming, chunked, size-checked decompression.
- Express the new dependency using the same marker style already used for the
  brotli/brotlicffi pair in `pyproject.toml`.

**Non-Goals:**

- No change to which encodings exist, to the `DOWNLOAD_MAXSIZE` /
  `DOWNLOAD_WARNSIZE` semantics, or to the decompression-bomb protections.
- No compression of request bodies and no zstd support outside the HTTP
  compression middleware.
- No change to the public Python API of Scrapy.

## Decisions

**1. Try the standard library first, fall back to the backport.**
Use `try: from compression.zstd import ZstdDecompressor / except ImportError:
from backports.zstd import ZstdDecompressor`. This covers Python 3.14+
(including builds where the `_zstd` extension is unavailable), older CPython,
and PyPy in a single statement, and it avoids a version check that could get
the fallback wrong if `compression.zstd` is missing from an otherwise new
interpreter. *Alternatives considered:* keeping `zstandard` as the only backend
(rejected - it is the dependency we want to drop and it is not stdlib);
unconditional `backports.zstd` (rejected - it would add a needless dependency
on interpreters that already provide the module).

**2. Declare the backport as a default requirement with a Python marker.**
Add `backports.zstd>=1.3.0; python_version < "3.14"` to `[project]
dependencies` and remove the `zstd` optional extra. The marker is required
because the backport refuses to import on 3.14+ (it raises `RuntimeError` when
`sys.version_info` is outside `>=3.10,<3.14`), where the standard library
module is used instead; its floor is the oldest release providing the
`ZstdDecompressor` streaming API used here. *Alternatives considered:* keeping
the extra and only switching the import (rejected - "mandatory" is the point of
the change); vendoring a fallback (rejected - adds maintenance burden);
installing the backport on 3.14 too (rejected - it cannot be imported there).

**3. Remove the runtime capability probe, not the capability concept.**
`ACCEPTED_ENCODINGS` becomes a constant list that always contains `b"zstd"`;
the `importlib.util.find_spec("zstandard")` check and the import of
`find_spec` disappear. The unsupported-encoding warning keeps its structure
for genuinely unknown encodings but loses the zstd-specific install hint, since
that state is no longer reachable.

**4. Keep the existing chunked streaming implementation.**
`_unzstd()` continues to read the stream in `_CHUNK_SIZE` blocks and to call
`_check_max_size()` per chunk, so the decompression-bomb guarantee and the
reported "decompressed so far" size stay the same across backends.

**5. Update packaging, tox, docs, and tests together.**
The dependency change is only coherent if `tox.ini` stops installing the old
package, the docs stop describing zstd as opt-in, and the zstd tests lose their
skip guards and drop the "unsupported zstd" expectation.

## Risks / Trade-offs

- [Backend API drift between `compression.zstd`, `backports.zstd`, and the old
  `zstandard`] -> Keep the surface used from the backend as small as possible
  (`ZstdDecompressor().stream_reader()`); verify both a static frame with a
  recorded content size and a streaming frame without one during
  implementation, and adapt `_unzstd()` if a backend lacks the streaming
  reader.
- [Mandatory dependency increases install size and may fail to resolve on some
  platforms/PyPy] -> Prefer the stdlib on 3.14+; for older interpreters rely on
  published wheels and keep an interpreter marker if the backport does not
  support PyPy, documenting the degradation instead of claiming support.
- [The backport may not provide the same streaming API or may be unavailable
  for some platforms] -> Pin `backports.zstd>=1.3.0` and validate the
  requirement in the `min-extra-deps` tox environment; if a platform such as
  PyPy cannot install a usable backport, document the degradation instead of
  claiming support.
- [Removing `test_process_response_zstd_unsupported` reduces coverage of the
  unknown-encoding warning] -> Keep/rename an equivalent case that exercises an
  encoding which is genuinely unknown, so the warning path stays tested.
- [Behavior change for users who intentionally do not install zstd] -> Call out
  the **BREAKING** dependency change in the release notes.

## Migration Plan

This is a packaging/behavior change, not a data migration. Users upgrading
Scrapy get the zstd backend pulled in automatically; users who previously
installed the `Scrapy[zstd]` extra can keep that extra name in their
requirements only until it is removed, so the release notes must mention the
removal. Rollback consists of restoring the optional import guard, the
conditional `ACCEPTED_ENCODINGS`, the `zstd` extra, and the tox dependency
entries.
