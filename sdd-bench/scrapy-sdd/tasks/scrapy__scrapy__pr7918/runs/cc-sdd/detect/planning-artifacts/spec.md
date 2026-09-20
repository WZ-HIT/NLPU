# ScrapyJSONEncoder ISO 8601 serialization

## Scope

PR 7918 changes `scrapy.utils.serialize.ScrapyJSONEncoder` so Python
`datetime.datetime`, `datetime.date`, and `datetime.time` values are encoded
with their ISO 8601 representations instead of the current space-separated
date/time formatting.

## Detection target

Identify repository-relative test files that exercise these encoder branches
directly or through JSON item exporters.

## Relevant production surface

- `scrapy/utils/serialize.py`: `ScrapyJSONEncoder.default`
- `scrapy/exporters.py`: `JsonItemExporter` and `JsonLinesItemExporter`

## Constraints

- Detection only; no tests are run.
- Project code and tests are not modified.
- Detection output is written to the mounted planning directory.
