# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7846`

Base commit: `488a762d7173922190ea027e0fb6f6d9d3b59880`

## Title

Support IDNA-2003-only domains by monkey-patching Twisted IDNA helpers

## Body

Resolves #4330, also fixes #3321

I took a stab at it from the Scrapy side by monkey-patching the Twisted functions at import time. I'm opening this PR to gauge whether the trade-off is worth it. I'm happy to drop it if blocking on Twisted is preferred, but here's some food for thought either way 🧠
