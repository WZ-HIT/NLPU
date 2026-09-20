## Context

See `proposal.md` for motivation. Current state of the code that matters:

- `scrapy/utils/response.py` writes the response body to a temporary file and
  injects a base tag with a single substitution:
  `re.sub(rb"<head(?:[^<>]*?>)", repl, body, count=1)`, guarded by
  `b"<base" not in _remove_html_comments(body)`.
- `_remove_html_comments()` is a small byte scanner used only to decide whether
  a base tag exists in real markup; it does not rewrite the body that is
  written to disk.
- The pattern was recently changed from `(<head(?:>|\s.*?>))` to
  `[^<>]*?` to avoid catastrophic backtracking, and
  `tests/test_utils_response.py` now contains regression tests
  (`test_open_in_browser_redos_comment`, `test_open_in_browser_redos_head`)
  that fail if a vulnerable pattern is reintroduced.
- `open_in_browser()` is shared by `scrapy view`, the shell `view` shortcut and
  user code, so the change must stay dependency-free and cheap: no HTML parser
  dependency, no meaningful slowdown for large bodies.

## Goals / Non-Goals

**Goals:**

- Produce a base tag for every `HtmlResponse`, including bodies without a
  `<head>` element.
- Keep the injected tag inside a `<head>` element so the generated document is
  well formed.
- Keep the existing guarantees: no duplicate base tag, base tags inside
  comments ignored, comments preserved, predictable performance.

**Non-Goals:**

- Parsing or normalizing arbitrary HTML, or fixing unrelated malformed markup.
- Changing the `.txt` behavior for text responses or the `TypeError` for other
  response types.
- Introducing a new public API or a new dependency.

## Decisions

**Decision 1: Keep the byte/regex approach, add an insertion fallback instead
of parsing.**

When no base tag exists and the comment-stripped body has no `<head>`
element, insert `<head><base href="<response url>"></head>`; otherwise keep the
existing substitution that places the base tag at the start of the real
`<head>`. Considered and rejected: parsing the body with `lxml`/`w3lib` and
serializing it, which would reformat the user's markup, add parsing cost to a
debugging helper, and change bytes the user expects to see.

**Decision 2: Choose the fallback insertion point from the markup itself.**

Insert the synthesized `<head>` immediately after the `<html …>` open tag when
the body contains one, and at the very start of the body otherwise. Considered
and rejected: emitting a bare `<base>` element at the start of the body (the
HTML specification requires `base` inside `head`), and always prepending
(which would put `<head>` before an existing `<html>`/`<!DOCTYPE>`).

**Decision 3: Detect on the comment-stripped body, insert into the original
body.**

Comment stripping changes byte offsets, so it stays a detection-only step, as
it already is for the base-tag check. Head existence is decided with
`re.search(rb"<head(?:[^<>]*?)>", _remove_html_comments(body))`, and the actual
insertion happens on the untouched body. This keeps commented-out head or base
tags from suppressing the injection, and keeps existing HTML comments in the
output.

**Decision 4: Keep the patterns linear.**

The new `<html(?:[^<>]*?)>` search mirrors the existing `<head(?:[^<>]*?)>`
pattern: a negated character class with no nested quantifier, so it cannot
exhibit catastrophic backtracking. The existing ReDoS regression tests must
keep passing; the new fallback path is also exercised with a large headless
body.

## Risks / Trade-offs

- [Browsers may relocate a synthesized `<head>` when the body starts with text
  or a fragment] → The tag is emitted in the document prologue, which browsers
  parse into the head anyway; tests assert that the base tag is present exactly
  once and sits inside a `<head>` element.
- [Commented-out `<html>`/`<head>` markup could mislead the search] → Head
  detection ignores comments; the `<html …>` fallback anchor uses the same
  non-backtracking pattern and degrades to "prepend", which is still valid.
- [Extra regex pass on large bodies could slow `open_in_browser()`] → The
  searches are linear and only run when a base tag must be injected; the
  existing timing guard in `tests/test_utils_response.py` (0.2 s CPU budget)
  covers the adversarial inputs.

## Migration Plan

None. This is a behavior fix released as a patch: update
`docs/news.rst` with the bug fix entry (referencing #6550) and revert the
commit to roll back.
