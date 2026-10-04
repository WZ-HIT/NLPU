# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7459`

Base commit: `4e25686b20b9f9c31e4917fb3509dbc538925624`

## Title

Fix the substitution pattern in open_in_browser().

## Body

Surprisingly, `\0` is not supported as a reference (https://stackoverflow.com/questions/58134893/why-doesnt-0-work-in-python-regexp-substitutions-i-e-with-sub-or-expand) and so the head tag was being replaced by a literal zero byte :)
