# Contract: SSL Key Logging

## Configuration

- Key logging is disabled unless a destination is configured through the adopted environment-variable or setting interface.
- The same configuration applies to every built-in HTTPS-capable download handler.

## Output

- Records use the NSS key-log text format.
- Records append to the destination and do not replace prior records.
- Key material is not written to Scrapy's ordinary log output.

## Behavior

- Enabling key logging does not change certificate verification, ciphers, TLS version limits, redirects, retries, or response bodies.
- The mechanism works for both stdlib and Twisted HTTPS contexts.
- If the selected TLS implementation cannot expose key material, the behavior is reported predictably rather than silently succeeding.

## Security

- The feature is explicitly opt-in.
- Documentation warns that the output can decrypt captured TLS traffic and must be protected.
