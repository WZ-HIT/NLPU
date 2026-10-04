# Pull request task

Repository: `scrapy/scrapy`

Pull request: `6546`

Base commit: `58af57a3ea3a109f05c5b3e9f7b6e1e24adc9834`

## Title

Add settings for TLS min/max version as a replacement for the TLS method

## Body

Fixes #3288, fixes #4821

Deprecates:
* Setting the `DOWNLOADER_CLIENT_TLS_METHOD` setting to anything other than `TLS`
* `scrapy.core.downloader.tls.METHOD_*` constants
* `scrapy.core.downloader.tls.openssl_methods` dict

It also directly removes support for `DOWNLOADER_CLIENT_TLS_METHOD` from `HttpxDownloadHandler` (especially as the docs falsely claimed that it's not supported).
