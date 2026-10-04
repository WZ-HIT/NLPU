# Pull request task

Repository: `scrapy/scrapy`

Pull request: `6604`

Base commit: `f7db039d1ca2bcfee003453ddbb2210578ed9b62`

## Title

Add Python 3.14 to CI.

## Body

- [x] Wait until Twisted supports 3.14 asyncio loop changes, is released and is supported by Scrapy
- [x] Update `tests.test_squeues.PickleFifoDiskQueueTest.test_non_pickable_object()`
- [x] Update `tests/CrawlerProcess/asyncio_enabled_reactor.py`
- [x] Update `tests/test_utils_asyncio.py::TestAsyncio::test_install_asyncio_reactor`
- [x] Check `tests/test_command_check.py::TestCheckCommand::test_printSummary_with_unsuccessful_test_result*`
- [x] Check `tests/test_feedexport.py` failures on Linux
- [x] Check `tests/test_feedexport.py` failures on Windows
- [x] Update `tests/test_pipeline_files.py::TestFilesPipeline::test_file_path`
- [x] Improve the `tests/test_feedexport.py::TestFeedExporterSignals` fix for Windows
- [x] Fix/work around deprecated asyncio loop policies
- [x] Check the pytest-cov message
- [x] Investigate #5306
- [x] [python-zstandard](https://github.com/indygreg/python-zstandard/issues/238)
- [x] [uvloop](https://github.com/MagicStack/uvloop/issues/637)

Resolves https://github.com/scrapy/scrapy/pull/6604.
