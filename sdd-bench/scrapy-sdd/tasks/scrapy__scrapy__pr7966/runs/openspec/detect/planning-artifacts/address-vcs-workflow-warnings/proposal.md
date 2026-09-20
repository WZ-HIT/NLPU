## Why

The scheduled "VCS dependencies" workflow runs Scrapy against development branches of its dependencies, so it surfaces deprecation and runtime warnings that stable-dependency jobs do not. Those warnings obscure real failures and make the workflow's signal noisy.

## What Changes

- Identify the warnings emitted by the VCS dependency workflow.
- Update Scrapy code or tests where a warning indicates an avoidable use of a deprecated dependency API.
- Narrowly filter warnings only when they originate in third-party code and cannot yet be avoided by Scrapy.
- Keep the change behavior-preserving: no public API, setting, or crawler behavior changes.

## Capabilities

This is test and dependency-maintenance work with no spec-level behavior change, so the change declares `skip_specs: true` instead of inventing a capability requirement.

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

Affected areas are the warning-sensitive test paths and their compatibility helpers, particularly download-handler TLS tests, certificate handling tests, reactor/asyncio tests, and dependency-version compatibility branches. The VCS dependency workflow and pytest warning filters may change, but runtime behavior does not.
