# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7466`

Base commit: `068aa69b350ab7e06df5d4cb372cfd15b256ea39`

## Title

Clarify dataloss/http2 tests.

## Body

* Split `broken` and `broken-chunked` tests back into separate functions
* Keep only one `broken-chunked` test as  `cause_data_loss`, `allow_data_loss` and `allow_data_loss_via_setting` only differ in code that runs after the dataloss state has been detected and so there is no need for 3x2 tests
* Skip `broken-chunked` on HTTP/2 as it's not supported by design
* Skip dataloss tests for `H2DownloadHandler` in a better documented way
* Add instead a test that the dataloss state causes `DownloadFailedError` with `H2DownloadHandler` 
* Remove `test_duplicate_header()` from the `H2DownloadHandler` tests as a similar test now exists in the base class

