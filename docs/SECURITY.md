> **Language / 语言**: English · [简体中文](SECURITY.zh-CN.md)

# Security baseline

## Principles

- Treat uploaded documents as untrusted data, never as system instructions.
- Apply tool allowlists and least privilege.
- Separate project/tenant access by authorization policy.
- Require human approval for contractual, regulatory, payment, schedule-commitment, safety shutdown and external correspondence actions.
- Preserve evidence provenance and audit context.
- Never put secrets into prompts, logs or demo files.

## Implemented so far

- **Three-mode identity boundary** (`services/api/app/security.py`): `disabled` preserves the public demo, `api_key` provides a timing-safe pilot service boundary, and `oidc` validates issuer-signed JWTs through JWKS. OIDC claims are normalized into organization, roles and project scope; mutation routes apply RBAC and the audit plane records actor, request and outcome. The Web authorization-code + PKCE flow verifies ID-token signatures and binding claims through issuer JWKS, keeps the access token in an encrypted HTTP-only session, requires the registered Web origin on cookie-authenticated mutations, and does not use the service credential as a browser identity.
- **HTTP and intake boundary controls:** explicit `CORS_ORIGINS` allowlist; browser security headers; request text limits; configurable upload size cap; PDF/DOCX signature checks and binary-TXT rejection. Malware scanning and DLP remain production backlog items.
- **Dependency baseline:** Next.js is pinned to the latest patched 15.x release used by this project, with patched PostCSS/source-map transitive versions locked and verified by `npm audit`.
- Kubernetes manifests (`infra/kubernetes/`) use public `/healthz` for Web liveness and fail-closed `/readyz` for Web auth/session configuration readiness, plus resource requests/limits, a `HorizontalPodAutoscaler`, an `api-secret.example.yaml` documenting API keys, and an example `Ingress` with TLS. Web OIDC/session values must be supplied separately as `globalinfra-web-secrets`; none of this is deployment evidence or a substitute for the items below.
- A Terraform starter (`infra/terraform/`) provisions a private VPC, encrypted RDS PostgreSQL, encrypted ElastiCache Redis and an encrypted/KMS-backed S3 bucket as a reviewable (not production-certified) AWS reference.

## Production backlog

- Activate the customer identity tenant, conditional access and MFA; validate the final claim mapping and role-assignment governance.
- RBAC + ABAC
- row-level tenant/project security
- KMS-backed secret encryption
- signed audit log chain
- malware scanning for uploads
- DLP and sensitive-data classification
- prompt-injection test suite
- CSP/HSTS and full API rate limiting (baseline anti-framing/content-type/referrer/permissions headers are already enabled)
- SIEM integration
- backup/restore drills
