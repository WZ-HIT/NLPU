# Research: Open Non-Text Responses in Browser via Content-Type

## Decision 1: Use `Content-Type` as the generic response source of truth

**Decision**: For generic responses that are neither HTML responses nor non-HTML textual responses, choose the local-file extension from the effective `Content-Type` header.

**Rationale**: The PR title and issue scope explicitly name `Content-Type` as the mechanism. Downloaded binary responses already carry this declaration, while URL suffixes may be absent or misleading. It also avoids guessing from arbitrary bytes.

**Alternatives considered**:

- Use the URL suffix. Rejected because many download endpoints do not end in a file extension and a suffix can disagree with the actual media type.
- Guess from the body. Rejected because binary content detection is unreliable and outside the feature scope.
- Use `Content-Disposition`. Rejected as an additional source of ambiguity; the scoped mechanism is `Content-Type`.

## Decision 2: Normalize the header before extension lookup

**Decision**: Treat the header value as HTTP metadata, decode it without depending on the response body encoding, take the media type before the first semicolon, trim surrounding whitespace, and compare it case-insensitively. Resolve conventional extensions through the standard library media-type mapping.

**Rationale**: `Content-Type` commonly includes parameters such as `charset`. Header values are case-insensitive and may include whitespace. Normalizing the media type before lookup makes behavior deterministic while preserving the parameter portion as out of scope.

**Alternatives considered**:

- Pass the full header value to extension lookup. Rejected because parameters are not part of the media type and would prevent matches.
- Maintain a custom fixed extension table. Rejected because the standard mapping already covers common web media types and avoids an unnecessary maintenance surface.
- Decode the header as UTF-8. Rejected because HTTP header bytes and Scrapy's existing content-type handling use a Latin-1-compatible path.

## Decision 3: Preserve response-class precedence

**Decision**: Continue to handle HTML response objects first, using `.html` and base-link injection. Continue to handle other textual response objects next, using `.txt`. Apply `Content-Type` extension mapping only to generic responses.

**Rationale**: Existing tests and users depend on HTML-specific base-link correction and on textual responses producing text files regardless of their textual media type. This ordering makes the new behavior additive.

**Alternatives considered**:

- Let `Content-Type` override HTML and text response handling. Rejected because it would regress base-link injection and change established extensions.
- Remove the textual response branch. Rejected because it would change existing user-visible behavior.

## Decision 4: Fail explicitly when no usable extension can be resolved

**Decision**: If `Content-Type` is missing, malformed, or maps to no extension, raise the existing unsupported-response error and do not call the browser opener.

**Rationale**: Opening a file with an arbitrary extension can cause the wrong application or renderer to handle it. Explicit failure is safer, testable, and consistent with the current contract for unsupported responses.

**Alternatives considered**:

- Fall back to `.bin`. Rejected because it hides an unusable media type and may produce a worse browser experience.
- Fall back to `.html`. Rejected because it can cause binary data to be parsed as active markup.
- Open with no extension. Rejected because behavior becomes platform-dependent and gives the browser no useful type hint.

## Decision 5: Update the command workflow to delegate

**Decision**: Remove the command's early check that rejects every response which is not a textual response. Let the browser-opening utility decide whether the effective media type can produce a browser target.

**Rationale**: The command currently prevents the utility from applying the new generic-response behavior. A single resolution path in the utility avoids duplicated media-type logic.

**Alternatives considered**:

- Duplicate extension logic in the command. Rejected because it would create inconsistent behavior between the utility and the command.
- Keep rejecting non-text responses in the command. Rejected because it would leave issue 3902 unresolved for the primary command-line workflow.

## Decision 6: Validate at utility and command levels

**Decision**: Extend `tests/test_utils_response.py` for extension selection, byte preservation, normalization, error behavior, and existing HTML/text regressions. Update `tests/test_commands.py` so image viewing succeeds and supplies a `.png` browser target.

**Rationale**: The utility tests pin the behavior matrix and edge cases. The command test proves the user-facing workflow no longer rejects non-text responses before the utility runs.

**Alternatives considered**:

- Utility tests only. Rejected because they would not catch the command's premature guard.
- Command tests only. Rejected because they would not cover header normalization and unsupported-response edges precisely.

## Decision 7: Retain existing HTML performance and preservation guarantees

**Decision**: Do not change the HTML base-link algorithm or its comments, doctype handling, or performance tests while adding generic response support.

**Rationale**: The feature is additive. Existing safeguards were added deliberately and should remain covered.

**Alternatives considered**:

- Refactor HTML handling during this change. Rejected because it broadens risk without being required by the feature.
