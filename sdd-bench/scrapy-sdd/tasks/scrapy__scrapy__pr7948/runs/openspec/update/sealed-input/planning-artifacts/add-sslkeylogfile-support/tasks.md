## 1. Implement TLS key logging

- [ ] 1.1 Add non-empty `SSLKEYLOGFILE` detection and NSS-format output to the built-in TLS context implementation.
- [ ] 1.2 Cover both certificate-verifying and non-verifying client paths used by HTTP/1.1 and HTTP/2.
- [ ] 1.3 Document the environment variable and its security implications.

## 2. Verify behavior

- [ ] 2.1 Add context-factory tests for enabled, unset, empty, and invalid-path cases.
- [ ] 2.2 Add HTTPS download-handler coverage showing key-log output after a successful TLS request.
