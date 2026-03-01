# Security Policy

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 0.1.x   | ✅        |

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security vulnerabilities by emailing the maintainers directly, or by using GitHub's private vulnerability reporting feature:

1. Go to the **Security** tab of this repository
2. Click **"Report a vulnerability"**
3. Fill in the details

### What to include
- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested fix (optional)

### Response timeline
- Acknowledgement within **72 hours**
- Assessment within **7 days**
- Patch released within **30 days** for critical issues

## Security measures implemented

- JWT tokens with strict validation (sub, exp, iss claims required)
- Probe authentication via bcrypt-hashed API keys
- HTTP security headers (CSP, X-Frame-Options, HSTS, etc.)
- Rate limiting on authentication and sensitive endpoints
- Input validation at all API boundaries (Pydantic)
- No secrets stored in code or logs
- Dependabot automated dependency updates
- CodeQL static analysis on every PR
- pip-audit security audit in CI pipeline
- TLS 1.2+ enforced via Nginx configuration
