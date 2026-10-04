# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7520`

Base commit: `2d007bc4508423bbd57ee9017da22c16bbd576e1`

## Title

Fix certificate issuer verification on new Twisted.

## Body

It's complicated but tl;dr the "no hostname verification" path (`DOWNLOAD_VERIFY_CERTIFICATES=False`) on new Twisted  does issuer verification and so needs trusted CA roots to do it.

I've added real world website tests to catch these, they can be excluded with `-m 'not requires_internet'`
