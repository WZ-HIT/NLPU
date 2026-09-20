# Phase 1 Data Model: Stop Sleeping 100 ms Before Callbacks and Media Results

This feature has no persistent storage; the "entities" below are runtime concurrency
states that the change must preserve.

## Entity: Pending I/O yield

| Field | Meaning |
|-------|---------|
| `yields` | Number of consecutive zero-delay yields required (2) |
| `delay` | Delay per yield (0 seconds) |
| `guarantee` | On resume, callbacks of ready readers/writers have had the chance to run |

**Rules**: may not be zero yields (nothing would be scheduled); may not reintroduce a
fixed delay; must work with both the asyncio reactor and the Twisted-only reactor.

**Transitions**: `called` → `first yield scheduled` → `second yield scheduled` →
`resumed` → caller continues (invoke callback / raise / cache media result).

## Entity: Callback invocation

| Field | Meaning |
|-------|---------|
| `response` | Downloaded response or `Failure` being handed to the spider |
| `callback` | `request.callback` (or `spider._parse`) / `request.errback` |
| `cb_kwargs` | Keyword arguments bound on the request |
| `output` | Callback return value (iterable, async iterator, awaitable) |

**Rules**: the pending-I/O yield happens first; the callback identity, kwargs and
output processing are unchanged; failures are raised the same way as before.

**Transitions**: `queued` → `yield pending I/O` → `callback invoked` → `output processed`.

## Entity: Media request fingerprint lifecycle

| Field | Meaning |
|-------|---------|
| `fingerprint` | Identity of the media request used for de-duplication |
| `downloading` | Fingerprints with an in-flight download |
| `waiting` | Fingerprint → list of deferreds to resolve when the result arrives |
| `downloaded` | Fingerprint → cached `FileInfo` or `Failure` |

**Rules**: at most one download per fingerprint per spider; the first successful
transition caches exactly one result; every waiter in `waiting[fp]` is resolved once;
cached failures are replayed through the request errback when one is set.

**Transitions**:

1. `new` → (fingerprint in `downloaded`) → yield pending I/O → `returned from cache`
2. `new` → add to `waiting` → (fingerprint in `downloading`) → `await shared result`
3. `new` → add to `downloading` → yield pending I/O → `media_to_download`/download →
   yield pending I/O → `cache result` + `resolve all waiters` → `downloaded`/`failed`

## Entity: Deprecated delayed helper

| Field | Meaning |
|-------|---------|
| `delay` | `_DEFER_DELAY` (0.1 s), unchanged |
| `warning` | `ScrapyDeprecationWarning`, unchanged |
| `call sites` | Public, deprecated; not migrated by this feature |
