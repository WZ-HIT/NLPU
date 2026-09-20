## 1. Extend browser output selection

- [ ] 1.1 Update the browser-opening utility to map non-text `Content-Type` values to filename extensions while preserving HTML and text behavior.
- [ ] 1.2 Keep a clear `TypeError` for responses with no usable type information.

## 2. Update the view command

- [ ] 2.1 Allow `scrapy view` to pass non-text responses to the browser-opening utility.

## 3. Verification

- [ ] 3.1 Add unit coverage for known non-text content types, the text fallback, and unsupported responses.
- [ ] 3.2 Add command coverage for opening a non-text response through `scrapy view`.

