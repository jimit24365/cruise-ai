# Security Policy

## Data Handling

nextmillionai runs **entirely on localhost**. It makes no outbound network calls, sends no telemetry, and uploads nothing. All scanned and derived data stays in `~/.nextmillionai/data/`.

See [DATA_COLLECTION.md](DATA_COLLECTION.md) for a full disclosure of what is read, what is derived, and what is never touched.

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Reporting a Vulnerability

If you discover a security vulnerability in nextmillionai, please report it responsibly:

1. **Email**: security@nextmillionai.dev
2. **Do not** open a public issue for security vulnerabilities.
3. Include a description of the vulnerability, steps to reproduce, and any relevant logs.

We will acknowledge receipt within 48 hours and aim to provide a fix or mitigation plan within 7 days.
