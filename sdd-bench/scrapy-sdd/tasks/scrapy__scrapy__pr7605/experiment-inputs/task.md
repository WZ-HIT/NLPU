# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7605`

Base commit: `a8ffdcf8517a8973391a14635234b6993b15a86a`

## Title

Fix strip_url() removing default port from password.

## Body

### summary
fixes `strip_url()` stripping default ports from passwords when `strip_credentials=False`.

```python
strip_url("http://user:80@example.com:80/p", strip_credentials=False)
# before: 'http://user@example.com/p'
# after:  'http://user:80@example.com/p'
```
fixes #7604

### root cause

`netloc.replace(f":{parsed_url.port}", "")` is a global substring replace and matches `:80` inside `user:password@` too.

### fix

split netloc on the rightmost `@` with `rpartition("@")` and strip the `:port` suffix from the host side only.

### changes

- `scrapy/utils/url.py` — strip default port from host only
- `tests/test_utils_url.py` — regression tests for passwords `80`, `443`, `21`
- `docs/news.rst` — bug fix entry

### test plan

```
pytest tests/test_utils_url.py
pytest tests/test_spidermiddleware_referer.py
```

edge cases verified: no credentials, non-default ports, IPv6 with and without credentials, `strip_credentials=True` path.
