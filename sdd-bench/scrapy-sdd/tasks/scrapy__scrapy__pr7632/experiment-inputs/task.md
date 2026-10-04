# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7632`

Base commit: `0a4a92e84334770a3aca3a3c44985cb08692535c`

## Title

Fix rel_has_nofollow to be case-insensitive per HTML spec

## Body

## Bug

The HTML specification states that link type keywords such as `nofollow`
are [ASCII case-insensitive](https://html.spec.whatwg.org/multipage/links.html#link-type-nofollow).
However, `rel_has_nofollow` performs a case-sensitive check, so a page
with `rel="NoFollow"` or `rel="NOFOLLOW"` is incorrectly treated as a
follow link and Scrapy will crawl it when it should not.

## Fix

Add `.lower()` before the token split in `scrapy/utils/misc.py`:

```python
# before
return rel is not None and "nofollow" in rel.replace(",", " ").split()
# after
return rel is not None and "nofollow" in rel.lower().replace(",", " ").split()
```

## Verification

```
pytest tests/test_utils_misc/ -k nofollow -v
# 1 passed
```

All 15 tests in `tests/test_utils_misc/` pass. The link extractor nofollow
test also passes.

> Note: This fix was developed with AI assistance.
