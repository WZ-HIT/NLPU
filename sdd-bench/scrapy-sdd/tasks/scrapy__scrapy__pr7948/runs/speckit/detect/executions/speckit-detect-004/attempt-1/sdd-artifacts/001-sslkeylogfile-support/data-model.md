# Data Model: SSLKEYLOGFILE Support

## Key Log Destination

**Represents**: The file receiving NSS-format TLS key material.

**Attributes**:

- Path: supplied through the selected opt-in configuration.
- Exists: whether the file already contains earlier records.
- Writable: whether records can be appended.

**Validation**:

- No destination means key logging is disabled.
- A configured path that cannot be opened is a predictable configuration error.

## Key Log Record

**Represents**: One TLS secret emitted by the TLS implementation.

**Attributes**:

- Label: the standard TLS key label.
- Client random: the connection identifier for the secret.
- Secret: encoded TLS key material.

**Validation**:

- Must be written as one complete text line.
- Must be consumable by standard TLS analysis tools.

## TLS Context

**Represents**: A stdlib `ssl.SSLContext` or Twisted/pyOpenSSL context used for HTTPS downloads.

**Relationships**:

- May write zero or more key-log records.
- Receives destination policy from the shared SSL utility.

**State transitions**:

- Disabled: no callback or output file is installed.
- Enabled: a callback or key-log filename is installed before the connection is created.
