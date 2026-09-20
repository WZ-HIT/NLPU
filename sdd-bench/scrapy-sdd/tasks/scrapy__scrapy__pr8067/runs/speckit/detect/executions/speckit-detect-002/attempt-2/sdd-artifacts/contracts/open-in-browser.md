# Contract: Browser Opening for Non-Text Responses

## Public Utility

The public browser-opening utility accepts a response plus an optional injected opener. Support is defined by observable behavior rather than a specific implementation.

### Input

- `response`: A Scrapy response with a URL, headers, and bytes body.
- `open_function` (optional): A callable used instead of the system browser opener. Tests use this to capture the local file path without launching a browser.

### Behavior Matrix

| Response classification | Effective media type | Browser target extension | Body preparation | Browser-opener call |
|-------------------------|----------------------|--------------------------|-------------------|---------------------|
| HTML response | Any | `.html` | Existing base-link injection and preservation behavior | Yes, when preparation succeeds |
| Non-HTML textual response | Any | `.txt` | Exact response bytes | Yes |
| Generic response | Supported known media type | Conventional extension for that media type | Exact response bytes | Yes |
| Generic response | Missing, malformed, or unknown | None | None | No |

### Extension Resolution Contract

- Use only the media type portion of `Content-Type`; parameters are ignored.
- Treat surrounding whitespace and ASCII case differences as non-significant.
- Use the effective response header value when multiple values exist.
- Do not use the URL suffix, body contents, or response class name to override a usable generic media type.
- The response body must not be decoded or re-encoded as text.

### Error Contract

- Missing, malformed, or unknown media types produce a clear unsupported-response error.
- No temporary browser target is produced for a failed resolution.
- The browser opener is not called for a failed resolution.

## Command-Line View Workflow

The command-line view workflow has the same support boundary as the public utility.

### Contract

- Fetch the requested URL through the existing downloader workflow.
- Pass the resulting response to the public browser-opening utility without rejecting it solely because it is not a textual response.
- On a supported image, document, or other generic response, complete successfully and provide the browser opener with a local file whose extension reflects the media type.
- On an unsupported response, report the utility's unsupported-response failure rather than the previous blanket non-text warning.

### Required Validation

- A PNG resource fetched through the command workflow produces a `.png` browser target.
- An HTML resource continues to produce a `.html` browser target with working relative links.
- Existing command success and error semantics remain otherwise unchanged.

## Compatibility Boundary

- Existing HTML behavior is unchanged and remains specialized.
- Existing non-HTML textual behavior is unchanged.
- Shell access to the utility inherits the new behavior without a separate contract.
- No new dependency, configuration option, or persistent artifact is introduced.
