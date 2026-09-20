## Purpose

Define how spider contract checks execute callback code, including callbacks
implemented as coroutines or asynchronous generators.

## ADDED Requirements

### Requirement: Contract hooks support asynchronous callbacks

Contract checks SHALL execute asynchronous spider callbacks to completion before
evaluating contract post-process hooks.

#### Scenario: Coroutine callback output

- **WHEN** a contracted callback is a coroutine that returns one or more items
  or requests
- **THEN** the contract check SHALL await the callback and evaluate its output
  as the callback result

#### Scenario: Asynchronous generator callback output

- **WHEN** a contracted callback is an asynchronous generator that yields items
  or requests
- **THEN** the contract check SHALL consume the asynchronous generator to
  completion and evaluate the yielded values

#### Scenario: Contract hooks retain their order

- **WHEN** a contracted asynchronous callback runs
- **THEN** all pre-process hooks SHALL run before callback execution and all
  post-process hooks SHALL run after the full callback output is available

#### Scenario: Asynchronous callback failure

- **WHEN** an asynchronous callback raises while producing output
- **THEN** the contract check SHALL record the failure as a callback error rather
  than crashing the check process

#### Scenario: Synchronous callback compatibility

- **WHEN** a contracted callback is synchronous
- **THEN** contract extraction, hook execution, output validation, and error
  reporting SHALL continue to behave as before
