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

- **Pilot-stage API key gate** (`services/api/app/security.py`, off by default via `REQUIRE_API_KEY=false`): a timing-safe shared-secret check on every request except `/health`; it fails closed when enabled without a key. The Next.js proxy injects the server-only `API_SERVICE_KEY`, so browser code never receives the credential. This remains a stopgap for a pilot network boundary, **not** a replacement for SSO/OIDC — it has no per-user identity, roles or audit trail.
- **HTTP and intake boundary controls:** explicit `CORS_ORIGINS` allowlist; browser security headers; request text limits; configurable upload size cap; PDF/DOCX signature checks and binary-TXT rejection. Malware scanning and DLP remain production backlog items.
- **Dependency baseline:** Next.js is pinned to the latest patched 15.x release used by this project, with patched PostCSS/source-map transitive versions locked and verified by `npm audit`.
- Kubernetes manifests (`infra/kubernetes/`) now include liveness/readiness probes, resource requests/limits, a `HorizontalPodAutoscaler`, an `api-secret.example.yaml` documenting the required secret keys, and an example `Ingress` with TLS — none of this is a substitute for the items below, but it closes the gap between "Deployment only" and an actually operable cluster rollout.
- A Terraform starter (`infra/terraform/`) provisions a private VPC, encrypted RDS PostgreSQL, encrypted ElastiCache Redis and an encrypted/KMS-backed S3 bucket as a reviewable (not production-certified) AWS reference.

## Production backlog

- SSO/OIDC/SAML + MFA (the API key gate above is an interim network-boundary control, not an identity system)
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
