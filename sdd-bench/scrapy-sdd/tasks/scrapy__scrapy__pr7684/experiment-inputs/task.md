# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7684`

Base commit: `185d6b9a20b7d0e77f4c60435d17e5072bd4d704`

## Title

Cleanup cookie handling in request_to_curl()

## Body

Followup to #7603 and #7675. I've rebased a WIP branch with type hints in `tests/test_utils_request.py` and found several issues:

1. The dict form of `Request.cookies` is currently type hinted as `dict[str, str]` - in fact we support bytes as both keys and values, as this form is internally converted into the verbose list form which explicitly supports bytes.This is not documented but it doesn't make sense to disable it, and there were tests for bytes values. I've upadted the hint and added tests for bytes keys.
2. The original `request_to_curl()` code supports cookies as a list of one-item dicts since it was added in #5892, this is an oversight, but the recent PRs extended this. I've removed the support and the tests for it.
3. I've extracted some helpers to reduce code duplication.
