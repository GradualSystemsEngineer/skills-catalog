---
name: api-error-messages
description: Rewrites API error responses so they say what went wrong and how the caller can fix it, in a consistent JSON shape. Use when designing or reviewing HTTP API errors or validation messages.
---

# API error messages

1. Every error has a stable machine-readable code and a human message.
2. The message says what was wrong and what to do next, in one or two sentences.
3. Validation errors list every problem at once, not just the first.
4. Never leak stack traces, SQL or internal hostnames.
5. Show the before and after for each message you change.
