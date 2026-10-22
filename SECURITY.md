# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| Latest main | ✅ |

Only the latest commit on `main` receives security updates.

## Reporting a Vulnerability

**Do not open a public issue.** Email details to the maintainer directly.

Include:
- Description of the vulnerability
- Steps to reproduce
- Impact assessment
- Suggested fix (if any)

We'll acknowledge within 48 hours and coordinate a fix.

## Known Limitations

This is a **field deployment tool**, not a hardened production system:

- **No HTTPS built-in** — Run behind a reverse proxy (nginx/Caddy) with TLS
- **Basic password auth** — No MFA, no rate limiting, no account lockout
- **Session secret default** — Change `SECRET_KEY` before deploying
- **SQLite concurrency** — Single-writer; not for high-concurrency writes
- **File uploads** — Stored on disk, served by Flask; no virus scanning
- **Weather API** — Calls external `wttr.in` via `curl` subprocess

## Recommended Hardening

For any non-local deployment:

1. Set a strong `SECRET_KEY` environment variable
2. Run behind TLS-terminating reverse proxy
3. Set `SESSION_COOKIE_SECURE=True` and `SESSION_COOKIE_HTTPONLY=True`
4. Restrict network access (VPN, Tailscale, or firewall)
5. Backup `diary.db` and `uploads/` regularly
6. Monitor disk space (uploads can grow)
7. Consider PostgreSQL for multi-writer scenarios

## Disclosure Timeline

- Day 0: Report received
- Day 1-2: Acknowledgment + initial assessment
- Day 7: Fix target for critical issues
- Day 30: Fix target for non-critical issues
- Public disclosure after fix is deployed