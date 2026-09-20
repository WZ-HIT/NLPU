# Data Model: Mandatory zstd decompression

This feature changes capability selection and dependency availability; it
introduces no persistent data model.

## Runtime Dependency

| Field | Rule |
|-------|------|
| Package | `backports-zstd` |
| Version | `>=1.3.0` |
| Marker | `python_version < '3.14'` |
| Scope | Core runtime dependency |

## Accepted Encodings

| Value | Availability | Decoder |
|-------|--------------|---------|
| `gzip` | Always | gzip utility |
| `x-gzip` | Accepted input alias | gzip utility |
| `deflate` | Always | zlib utility |
| `br` | Always | Brotli dependency |
| `zstd` | Always | standard library or backport |

## Decompression State

| Field | Meaning | Validation |
|-------|---------|------------|
| input bytes | Compressed response body | Existing response body |
| decoded size | Bytes produced so far | Must remain within configured maximum |
| remaining input | Data not yet consumed | Advances each decompression step |
| truncated input | Incomplete zstd stream | Existing truncated-response behavior |
