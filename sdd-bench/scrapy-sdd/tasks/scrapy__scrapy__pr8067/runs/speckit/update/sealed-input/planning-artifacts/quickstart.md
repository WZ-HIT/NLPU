# Quickstart Validation: Open Non-Text Responses in Browser via Content-Type

This guide describes validation for the implementation phase. The artifacts were generated during a planning-only pass; no tests or project code were run or modified while producing them.

## Prerequisites

- Install the repository in a development environment with its test dependencies.
- Use a supported Python version from `pyproject.toml`.
- Keep the browser opener injected or redirected to a recording command during automated validation.

## Scenario 1: Open a PNG Response Through the Utility

1. Create a generic response whose body is a small PNG byte sequence.
2. Set the effective `Content-Type` header to `image/png`.
3. Call the browser-opening utility with an opener that records the local path and reads the file bytes.
4. Verify:
   - The recorded path ends in `.png`.
   - The recorded file bytes equal the original response body.

Expected result: the opener is called once with a local `.png` file containing the exact response body.

## Scenario 2: Normalize a Parameterized Media Type

1. Repeat Scenario 1 with `Content-Type: IMAGE/PNG; charset=binary`.
2. Verify that the recorded path still ends in `.png`.

Expected result: header casing, whitespace, and parameters do not affect extension selection.

## Scenario 3: Preserve HTML and Text Behavior

1. Open an HTML response whose body contains relative links and an optional doctype.
2. Verify that the local file ends in `.html` and contains exactly one effective base link.
3. Open a non-HTML textual response.
4. Verify that the local file ends in `.txt` and contains the expected text.

Expected result: existing HTML and text behavior is unchanged.

## Scenario 4: Reject an Unusable Media Type

1. Create a generic response with no `Content-Type`.
2. Attempt to open it with a recording opener.
3. Repeat with a malformed media type and with an unknown media type.
4. Verify that every attempt reports a clear unsupported-response error and the opener is never called.

Expected result: unsupported generic responses fail explicitly instead of opening a misleading local file.

## Scenario 5: Validate the Command Workflow

1. Start the repository's mock HTTP server.
2. Use a recording browser command for the `view` command.
3. View the PNG fixture at `tests/sample_data/test_site/files/images/scrapy.png`.
4. Verify that the command succeeds and the recorded local path ends in `.png`.
5. View the HTML endpoint and verify that the command still succeeds with an `.html` target.

Expected result: the command-line workflow delegates non-text responses to the utility and preserves HTML behavior.

## Focused Validation Commands

Run these only during implementation, not during this planning phase:

```bash
pytest tests/test_utils_response.py -k open_in_browser
pytest tests/test_commands.py -k TestViewCommand
```

Expected result: all selected tests pass, including the updated image-viewing case and existing HTML, text, error, and performance cases.
