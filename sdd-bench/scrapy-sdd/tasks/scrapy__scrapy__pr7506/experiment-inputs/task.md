# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7506`

Base commit: `a8a8f20d9c49ae7f611cbdc90676b64f6349dba2`

## Title

fix open_in_browser() logic issue plus add new tests

## Body

In the open_in_browser() function inside scrapy/utils/response.py, _remove_html_comments(body) was being called with the results thrown away. The `if b"<base" not in body` condition is supposed to skip the <base> tag injection when the response already contains a real <base> element, and not just in a comment somewhere. That has been fixed, with the relevant tests being added to tests/test_utils_response.py.
