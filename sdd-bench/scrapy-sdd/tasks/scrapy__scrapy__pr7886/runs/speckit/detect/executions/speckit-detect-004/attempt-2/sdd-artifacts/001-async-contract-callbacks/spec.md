# Feature Specification: Asynchronous Callbacks in Spider Contracts

**Feature Branch**: `001-async-contract-callbacks`

**Created**: 2026-09-20

**Status**: Draft

**Input**: User description: "Support asynchronous callbacks in contracts (scrapy/scrapy pull request #7886, fixes issue #6681)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Contract checks accept asynchronous callbacks (Priority: P1)

A spider author writes a callback using `async def` (a coroutine that returns items,
requests, or a dict) and annotates it with contracts such as `@url` and `@returns`.
Running the contract check for that spider runs the callback, counts the objects it
produces, and reports success or failure instead of refusing to run because the
callback is asynchronous.

**Why this priority**: This is the core gap reported in issue #6681. Scrapy already
supports asynchronous callbacks at crawl time, so contract checking is the only
place where the same spider code is rejected. Without this, authors cannot use
contracts to validate modern asynchronous spiders.

**Independent Test**: Run the contract check against a spider whose callback is
`async def` and returns an item/request that satisfies its `@returns` contract.
The check must report a passing result, and must report a failing result when the
contract expectation is not met.

**Acceptance Scenarios**:

1. **Given** a spider callback defined with `async def` that returns the expected
   number of items, **When** the contract check runs that callback, **Then** the
   check reports success and no error about asynchronous callbacks.
2. **Given** a spider callback defined with `async def` that returns fewer objects
   than the contract expects, **When** the contract check runs, **Then** the check
   reports a contract failure (not an error, and not a crash).
3. **Given** a spider callback defined with `async def` that raises an exception,
   **When** the contract check runs, **Then** the exception is reported as a
   contract error for that callback.

---

### User Story 2 - Contract checks accept asynchronous generator callbacks (Priority: P2)

A spider author writes a callback using `async def` with `yield`, producing items or
requests incrementally, and annotates it with contracts. The contract check
consumes the produced objects and evaluates the contracts against them.

**Why this priority**: Asynchronous generators are the idiomatic way to write
modern Scrapy callbacks, and they are the second asynchronous shape that the
current implementation refuses. It shares the same root cause as User Story 1 but
exercises a different result type, so it is validated separately.

**Independent Test**: Run the contract check against a spider whose callback is an
asynchronous generator yielding the expected number of items; the check must pass,
and must fail when fewer objects are yielded than the contract requires.

**Acceptance Scenarios**:

1. **Given** an asynchronous generator callback that yields the expected objects,
   **When** the contract check runs, **Then** the check reports success.
2. **Given** an asynchronous generator callback that yields fewer objects than the
   contract expects, **When** the contract check runs, **Then** the check reports a
   contract failure that names the expected range.

---

### User Story 3 - Contract hooks run around asynchronous callbacks (Priority: P3)

A spider author defines a custom contract with a `pre_process` and/or
`post_process` hook and applies it to an asynchronous callback. The hooks must
still run in the documented order relative to the callback, and hook assertion
failures or exceptions must be attributed to the hook rather than to the callback.

**Why this priority**: Custom contracts are the extension point for teams with
project-specific expectations. Keeping hooks working for asynchronous callbacks
prevents a silent behavioural regression once asynchronous callbacks are allowed.

**Independent Test**: Apply a custom contract with a passing hook, an asserting
hook, and an exception-raising hook to an asynchronous callback; confirm that each
case reports success, failure, and error respectively.

**Acceptance Scenarios**:

1. **Given** a custom contract whose `pre_process` hook raises `AssertionError` and
   an asynchronous callback, **When** the check runs, **Then** the failure is
   reported against the pre-hook test case.
2. **Given** a custom contract whose `post_process` hook inspects callback output
   and an asynchronous callback, **When** the check runs, **Then** the hook
   receives the objects produced by the asynchronous callback.

### Edge Cases

- A callback returns a coroutine that resolves to a single item, to a list of
  items/requests, or to `None`; each shape must be counted exactly as the
  synchronous equivalent would be.
- A callback returns an already-scheduled result (for example a `Deferred`) or a
  custom awaitable; the check must not misclassify it as a plain iterable.
- An asynchronous callback that raises after producing some objects must report an
  error rather than a partial success.
- An asynchronous generator that is never fully consumed must not leave an
  un-awaited coroutine or an unretrieved failure behind.
- A callback that mixes yielded requests and yielded items under `@returns` and
  `@scrapes` must keep the existing "ignore other types" counting semantics.
- The synchronous contract paths must behave exactly as before, including existing
  error and failure reporting.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The contract check MUST run callbacks defined as `async def`
  (coroutines) and evaluate their contracts, instead of rejecting them with an
  error stating that asynchronous callbacks are unsupported.
- **FR-002**: The contract check MUST run callbacks defined as asynchronous
  generators and evaluate contracts against the objects they yield.
- **FR-003**: Objects produced by asynchronous callbacks MUST be counted by the
  `@returns` and `@scrapes` contracts with the same semantics as objects returned
  by synchronous callbacks.
- **FR-004**: An exception raised while awaiting an asynchronous callback MUST be
  reported as a contract error for that callback, and MUST NOT be reported as a
  success or swallowed.
- **FR-005**: Custom contract `pre_process` and `post_process` hooks MUST run for
  asynchronous callbacks, and their assertion failures MUST be reported as
  failures and their other exceptions as errors, attributed to the hook test case.
- **FR-006**: The `post_process` hook MUST receive the objects produced by an
  asynchronous callback in the same form in which it receives them for a
  synchronous callback.
- **FR-007**: The contract check command MUST report a non-zero exit status when a
  contract evaluated against an asynchronous callback fails or errors, and a zero
  exit status when all contracts pass.
- **FR-008**: Behaviour for synchronous callbacks, including existing failure and
  error reporting formats, MUST remain unchanged.
- **FR-009**: Result objects that are already awaitable at the point the callback
  returns MUST be awaited rather than treated as plain iterables.

### Key Entities *(include if data involved)*

- **Spider callback**: The callable attached to a sample request by a contract; may
  be synchronous, a coroutine, or an asynchronous generator.
- **Contract**: An annotation extracted from a callback docstring that declares an
  expectation about the sample request or about the objects the callback produces.
- **Contract hook**: The optional `pre_process` / `post_process` methods of a
  contract that wrap the callback during a check.
- **Contract check result**: The per-contract outcome (success, failure, or error)
  collected by the check run and summarised in the command output and exit status.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All existing contract checks continue to pass with no change to
  their reported outcomes.
- **SC-002**: A spider with an asynchronous (coroutine) callback annotated with
  contracts completes a contract check with the same pass/fail outcome as the
  equivalent synchronous callback in 100% of the covered cases.
- **SC-003**: A spider with an asynchronous generator callback annotated with
  contracts completes a contract check with the same pass/fail outcome as the
  equivalent synchronous generator callback in 100% of the covered cases.
- **SC-004**: No contract check run against an asynchronous callback ends with an
  error whose message states that asynchronous callbacks are unsupported.
- **SC-005**: A failing or erroring contract evaluated against an asynchronous
  callback produces a non-zero command exit status.

## Assumptions

- Only the contract-checking feature is in scope; crawl-time handling of
  asynchronous callbacks is already supported and is not changed here.
- The user-facing documentation for contracts gains an asynchronous example; no
  new configuration option is introduced.
- Asynchronous callbacks are awaited exactly once, and the ordering guarantee that
  a `pre_process` hook observes the response before the callback runs is preserved.
