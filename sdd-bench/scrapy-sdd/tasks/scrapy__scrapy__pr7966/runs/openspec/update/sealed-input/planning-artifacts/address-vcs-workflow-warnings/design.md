## Context

The VCS workflow installs unreleased versions of Scrapy's dependencies and runs the normal suite on Python 3.14. Warnings therefore reflect upstream deprecations before they reach stable releases. The suite already contains several targeted warning filters and dependency-version gates, so the change should extend that pattern rather than introduce broad global suppression.

## Goals

- Remove avoidable warnings reported by the VCS workflow.
- Keep warning handling narrow and tied to a specific dependency/API.
- Preserve behavior across the minimum, stable, and VCS dependency environments.

## Non-Goals

- Changing crawler, downloader, reactor, or public API behavior.
- Upgrading or pinning development dependencies permanently.
- Making all warnings fatal globally.

## Approach

1. Reproduce or inspect the VCS workflow's warning summary and map each warning to the test or runtime path that emits it.
2. Where the warning comes from Scrapy or test code calling a superseded dependency API, migrate to the supported API and keep version-compatibility gates where older supported releases need the old path.
3. Where the warning comes from dependency internals, add the narrowest practical pytest filter, with a comment linking the upstream cause.
4. Run the smallest relevant test modules under both installed and VCS-like dependency versions, then broaden only if a shared warning source is involved.

## Risks

- Over-broad filters can hide new warnings from Scrapy itself, so filters must include a message or module constraint.
- Dependency-version gates can drift; shared helpers in `scrapy/utils/_deps_compat.py` and the warning-sensitive test bases should remain the single source of truth.
- Warnings may differ between Python 3.14 and local versions, so verification should include the VCS workflow's Python version where possible.

## Validation

- Focused runs of the candidate test modules with warnings displayed.
- A clean VCS-workflow run with no new warning summary entries attributable to Scrapy.
- No changes to test outcomes in the minimum or stable dependency environments.
