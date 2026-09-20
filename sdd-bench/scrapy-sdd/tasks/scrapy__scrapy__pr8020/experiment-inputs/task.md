# Pull request task

Repository: `scrapy/scrapy`

Pull request: `8020`

Base commit: `ed98aafd0f6301647916c86811acacd0a1b59dbd`

## Title

Speed up the PyPy CI job and the tests that wait on the engine heartbeat

## Body

The PyPy job speed-up is by disabling coverage for subprocess there, which was responsible for most of the slowdown, and does not provide anything PyPy-specific that would report coverage gaps in Codecov.
