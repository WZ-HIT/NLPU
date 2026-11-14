# Pull request task

Repository: `scrapy/scrapy`

Pull request: `7853`

Base commit: `a499dc9511005e026860c5ce72296ba1ff3aae1b`

## Title

Simplify cmdline settings test

## Body

This replaces the manual string rewriting in the command line settings test with `ast.literal_eval()`, which can parse the Python literal printed by the command directly. The existing truncation assertion is kept.
