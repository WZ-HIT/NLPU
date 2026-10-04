# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7524`

Base commit: `a8a8f20d9c49ae7f611cbdc90676b64f6349dba2`

## Title

Add BaseStreamingDownloadHandler and migrate HttpxDownloadHandler to it.

## Body

Synchronization with https://github.com/scrapy-plugins/scrapy-download-handlers-incubator/, though without HTTP/2 support for now (mostly because we would need to unconditionally to install `h2` in tests due to it being imported for `HttpxDownloadHandler` and that means some reshuffling of extra-deps).

Part of #7252
