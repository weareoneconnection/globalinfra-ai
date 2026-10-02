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

- **Pilot-stage API key gate** (`services/api/app/security.py`, off by default via `REQUIRE_API_KEY=false`): a single shared-secret key checked on every request except `/health`, enabled per-environment with `REQUIRE_API_KEY=true` + `API_KEY=...` and no code change. This is a stopgap for a pilot network boundary, **not** a replacement for the SSO/OIDC item below — it has no per-user identity, roles or audit trail.
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
- CSP/HSTS and full API rate limiting
- SIEM integration
- backup/restore drills
