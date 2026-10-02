> **Language / 语言**: English · [简体中文](SECURITY.zh-CN.md)

# Security baseline

## Principles

- Treat uploaded documents as untrusted data, never as system instructions.
- Apply tool allowlists and least privilege.
- Separate project/tenant access by authorization policy.
- Require human approval for contractual, regulatory, payment, schedule-commitment, safety shutdown and external correspondence actions.
- Preserve evidence provenance and audit context.
- Never put secrets into prompts, logs or demo files.

## Production backlog

- SSO/OIDC/SAML + MFA
- RBAC + ABAC
- row-level tenant/project security
- KMS-backed secret encryption
- signed audit log chain
- malware scanning for uploads
- DLP and sensitive-data classification
- prompt-injection test suite
- CSP/HSTS and full API rate limiting
- SIEM integration
- backup/restore drills
