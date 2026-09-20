# Data Model: Stabilize Storage Expiry Test

## Test Scenario State

### Cache Entry

- **Represents**: A response associated with a request in the selected storage backend.
- **Key attributes**: Request identity, response value, stored timestamp or persisted age.
- **Validation**: A fresh entry returns the stored response; an expired entry returns no response.

### Controlled Reference Time

- **Represents**: The time value used by the test when storing and checking the cache entry.
- **Key attributes**: Initial value for the fresh phase, later value beyond the expiration threshold.
- **Validation**: The fresh value precedes expiration, and the later value exceeds it.

### Expiration Interval

- **Represents**: The configured maximum age of a cache entry.
- **Key attributes**: Positive finite value for the expiring scenario; zero for the never-expire scenario.
- **Validation**: Positive values permit a transition from fresh to expired; zero leaves the entry readable indefinitely.

## State Transitions

1. **Empty**: No cache entry exists for the request.
2. **Stored and fresh**: The entry exists at the controlled reference time and is retrievable.
3. **Expired**: The controlled reference time is beyond the configured interval and retrieval returns no response.
