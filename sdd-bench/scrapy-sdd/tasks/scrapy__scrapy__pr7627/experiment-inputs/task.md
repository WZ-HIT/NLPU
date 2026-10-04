# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7627`

Base commit: `e74647572d692598ca943db539d45aefdc4956ac`

## Title

Document scrapy-lint, remove start_url check

## Body

Resolves #4421.

Not 100% sure about the URL check removal. I had originally planned to remove it as part of this change, but seeing how trivial it is, and that not all users will install scrapy-lint. Should we keep it?
