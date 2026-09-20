# Quickstart: Validate mandatory zstd support

This guide is for later implementation validation. Tests were not run during
the planning task.

## Prerequisites

- Supported Python version.
- Project development dependencies.
- On Python before 3.14, `backports.zstd` installed from project metadata.

## Checks

1. Confirm the project metadata declares the backport for Python before 3.14
   and no longer exposes a `zstd` extra.
2. Confirm a default middleware request advertises `gzip, deflate, br, zstd`.
3. Decode each existing zstd fixture and compare it with the expected HTML.
4. Exercise zstd frames with and without a declared content size, including a
   streaming frame.
5. Exercise `DOWNLOAD_MAXSIZE`, spider attributes, and request metadata against
   the zstd compression-bomb fixture.
6. Exercise `DOWNLOAD_WARNSIZE` for settings, spider attributes, and request
   metadata.
7. Confirm a truncated zstd response is handled like the other truncated
   encodings and does not stall.

## Expected Result

All zstd scenarios run without optional-dependency skips, decode successfully
where valid, and retain the existing limit and warning behavior.
