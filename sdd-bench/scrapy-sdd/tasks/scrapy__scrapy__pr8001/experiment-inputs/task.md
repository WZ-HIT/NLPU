# Pull request task

Repository: `scrapy/scrapy`

Pull request: `8001`

Base commit: `c31602aca319f4203cbda24c41673f658ad4284b`

## Title

Move the parsel version check to _deps_compat, drop the w3lib ones

## Body

A botocore check remains in `tests.test_feedexport_batch.TestBatchDeliveries.test_s3_export()` but as botocore is not a hard dep it may complicate the code too much.
