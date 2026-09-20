# Data Model: Support IDNA-2003-only domains

## Hostname

**Fields**

- `display_name`: Unicode or ASCII name supplied by the user or response.
- `ascii_name`: Name passed to DNS resolution and TLS verification.

**Validation rules**

- An ASCII hostname must remain stable.
- A modern internationalized name must use the existing preferred conversion.
- An IDNA-2003-only name must fall back to the legacy conversion.
- A name rejected by both conversions must raise an error.

**State transitions**

1. User/request hostname -> preferred ASCII conversion.
2. Preferred failure for a legacy-only name -> legacy ASCII conversion.
3. Successful conversion -> resolver or TLS helper.

No persistent storage is introduced.
