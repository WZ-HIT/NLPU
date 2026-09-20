# Quickstart Validation: Fix open_in_browser base insertion without a head

## Prerequisites

- A Scrapy development environment with the project dependencies installed.
- No production service or external endpoint is required.

## Scenario 1: Headless HTML

Prepare an `HtmlResponse` whose body has no real head or base element, call `open_in_browser` with a capturing opener, and inspect the captured file. Expected: exactly one effective base element uses the response URL, and the original body content remains.

## Scenario 2: Existing Head

Repeat with a normal `<head>` document. Expected: the base remains inside the existing head.

## Scenario 3: Existing or Commented Markup

Repeat with an existing real base and with only commented head/base markup. Expected: a real base is not duplicated, while a commented base does not block insertion and comments remain.

## Scenario 4: Non-HTML and Malformed Input

Repeat with a plain `TextResponse` and with malformed or large head-like input. Expected: text behavior is unchanged and preview preparation remains fast.

## Verification Scope

This is a validation guide only. Run tests and repository checks only during an explicitly requested implementation phase.
