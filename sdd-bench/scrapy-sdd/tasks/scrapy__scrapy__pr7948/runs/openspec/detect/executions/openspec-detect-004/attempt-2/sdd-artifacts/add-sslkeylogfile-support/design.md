## Context

Twisted's `CertificateOptions` builds the OpenSSL client context used by the built-in HTTP/1.1 and HTTP/2 handlers. pyOpenSSL exposes `SSL.Context.set_keylog_callback`, so Scrapy can register a callback while constructing its client contexts.

## Goals / Non-Goals

**Goals:**

- Support the conventional `SSLKEYLOGFILE` opt-in.
- Cover verified and non-verified TLS paths used by the built-in Twisted handlers.
- Avoid changing request or connection behavior when disabled.

**Non-Goals:**

- Adding a Scrapy setting separate from `SSLKEYLOGFILE`.
- Enabling key logging by default.
- Implementing key logging for third-party download handlers.

## Decisions

Centralize callback installation in the Scrapy OpenSSL context options/context-creation path. Read the environment variable when a client context is created, open the target file in append mode, and register a callback that writes each key-log line. Do not raise connection errors for key-log output failures; report them through logging instead.

## Risks / Trade-offs

Key-log files contain material capable of decrypting captured TLS traffic. Documentation must make the debugging-only security implication explicit. File-handle lifetime and repeated context creation need care to avoid descriptor leaks.
