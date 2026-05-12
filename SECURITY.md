# Security Policy

## Scope

VanillaDB is a local desktop application. All data stays on your machine — no cloud sync unless you explicitly configure a git remote. The Python sidecar binds to a localhost-only port and is not accessible over the network.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.

Report privately via GitHub's [Security Advisory](../../security/advisories/new) feature, or email the maintainers directly (address in the GitHub profile).

Include:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof of concept
- The version or commit you tested against

We'll acknowledge within 72 hours and aim to release a fix within 14 days for critical issues.

## Threat model

| Area | Notes |
|------|-------|
| **LLM API keys** | Stored in `~/.vanilla/config.json` (local, user-owned). Never transmitted except to the configured LLM provider. |
| **Vault contents** | Read/written only by the local sidecar process. Never uploaded anywhere by default. |
| **Sidecar HTTP port** | Bound to `127.0.0.1` only. Not reachable from other machines. |
| **Git remote (optional)** | If you configure a remote, vault contents are pushed there. Use HTTPS with a personal access token scoped to that repo only. |
| **Ingested URLs** | Content is fetched server-side by the sidecar, not the browser. The sidecar does not follow redirects to local addresses. |

## Out of scope

- Social engineering
- Attacks requiring physical access to the machine
- Issues in third-party LLM providers (OpenAI, Anthropic, etc.)
- Vulnerabilities that require the attacker to already have write access to `~/.vanilla/`
