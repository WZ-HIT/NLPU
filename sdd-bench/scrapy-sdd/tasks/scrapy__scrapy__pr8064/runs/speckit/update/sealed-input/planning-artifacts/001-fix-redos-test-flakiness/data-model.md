# Phase 1 Data Model: Fix open_in_browser ReDoS Test Flakiness and a Broken Exploit Input

This feature has no persisted data. The entities below describe the test
fixtures and the decision inputs that the regression tests manipulate.

## ExploitBody

A crafted response body used to prove that a removed pattern is not reachable.

| Field | Type | Description / validation |
|-------|------|--------------------------|
| `payload` | bytes | Body passed to `HtmlResponse(..., body=payload)` |
| `target_pattern` | string | The removed pattern this body is meant to attack, e.g. `<!--.*?-->` or `(<head(?:>|\s.*?>))` |
| `repetition_unit` | bytes | The repeated fragment, e.g. `b"<head\t"` |
| `repetition_count` | int | Derived from the scaling measurement (D3), not hardcoded |
| `terminates_target_early` | bool | Validity flag: true when the target pattern can match inside the body without scanning to the end |

**Validation rules**

- `terminates_target_early` MUST be false for an accepted body (FR-003, D2).
- `len(payload)` MUST stay small enough that assembling it cannot fail the
  suite on a memory-constrained worker (D3).

**State transitions**

1. *Candidate* → body authored from the removed pattern's attack shape.
2. *Validated* → structural predicate (D2) confirms no early match for the
   target pattern.
3. *Accepted* → used by a regression test; reverting to *Candidate* is required
   if the predicate becomes true.

## RemovedPattern

The historical catastrophic pattern that a regression test guards against.

| Field | Type | Description |
|-------|------|-------------|
| `pattern` | string | Pattern source, e.g. `<!--.*?-->` (comments) or `(<head(?:>|\s.*?>))` (head lookup) |
| `category` | enum | `comment-stripping` or `head-lookup` |
| `replaced_by` | string | Description of the shipped replacement behaviour (no comment stripping; no head search) |

**Validation rules**: each category MUST be covered by at least one accepted
`ExploitBody` (FR-002).

## CostBudget

The machine-independent criterion used to separate a vulnerable implementation
from the shipped one.

| Field | Type | Description |
|-------|------|-------------|
| `base_size` | int | Body size at which the shipped implementation is measured first |
| `size_multiplier` | int | Factor applied to obtain the larger size |
| `max_growth_factor` | float | Upper bound on measured time growth between the two sizes; generous and well below quadratic growth |
| `smoke_limit_seconds` | float | Wide absolute ceiling kept only as a coarse sanity check |

**Validation rules**

- `max_growth_factor` MUST be far above the expected linear growth for
  `size_multiplier` and far below the expected quadratic growth (D1).
- `smoke_limit_seconds` MUST be derived from the measured baseline rather than
  hardcoded to a machine-specific constant (FR-001).

## RenderedViewerOutput

The temporary document handed to the browser, used by the behavioural
assertions.

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Temporary file path passed to the browser callable (`file://…`) |
| `body` | bytes | File contents |
| `base_tag_count` | int | MUST be exactly 1 for HTML responses (FR-005) |
| `base_tag_index` | int | MUST follow any doctype declaration and precede head contents (FR-005) |
| `comments_preserved` | bool | MUST be true; comment text survives (FR-004) |
| `extension` | string | `.html` for HTML responses, `.txt` for text responses (FR-006) |

**Relationships**: each `RenderedViewerOutput` is produced from one response
body, which may itself be an `ExploitBody` (for the timing tests the injected
base tag is irrelevant, but the same code path is used).
