# Research: SSLKEYLOGFILE Support

## Decision: Use the established `SSLKEYLOGFILE` file convention

**Rationale**: The environment-variable name and NSS line format are understood by Wireshark and other TLS debugging tools, matching the linked issue's request.

**Alternatives considered**: A Scrapy-only setting would be discoverable inside Scrapy but would not follow the familiar diagnostic workflow. Supporting both adds surface area; a setting can be added later if project review requires it.

## Decision: Centralize destination handling in `scrapy.utils.ssl`

**Rationale**: Both stdlib and pyOpenSSL contexts need identical defaults, destination resolution, append behavior, and record format. One utility avoids divergent handler behavior.

**Alternatives considered**: Implement separately in each handler. Rejected because it duplicates security-sensitive behavior and risks inconsistent output.

## Decision: Opt in only when the destination is configured

**Rationale**: Key material allows decryption of captured sessions and must not be emitted during ordinary crawls.

**Alternatives considered**: Always create a temporary key log. Rejected because it leaks secrets and adds needless I/O.

## Decision: Append standard records without using Scrapy logging

**Rationale**: Key material is diagnostic data intended for a file consumed by traffic-analysis software, not an application log stream.

**Alternatives considered**: Emit through the logging subsystem. Rejected because it can expose secrets and corrupt record formatting.

## Decision: Cover the shared Twisted context factory and stdlib HTTPX path

**Rationale**: HTTP/1.1 and HTTP/2 share Scrapy's Twisted context factory, while the experimental HTTPX handler creates a stdlib context directly. Testing these two paths protects all built-in HTTPS handlers.

**Alternatives considered**: Test only one handler. Rejected because it would leave an implementation path unverified.
