> **Language / 语言**: English · [简体中文](RELEASE_NOTES.zh-CN.md)

# GlobalInfra AI V1.0 Release Notes

This release establishes a standalone competition-ready and globally extensible foundation.

## Implemented

- Global Command Center
- Project and Case domains
- Deterministic multi-agent demo runtime
- Evidence chain and verification gate
- Human approval workflow
- Knowledge Fabric demo
- Multilingual HSE training demo
- Malaysia Country Pack plus regional pack scaffolds
- Rail Domain Pack plus five transport domain scaffolds
- Docker Compose deployment
- Kubernetes starter manifests
- Synthetic competition data and evaluation smoke harness
- Independent IP-boundary documentation
- Full-chain English/Chinese switching: browser-language auto-detection on the web, bilingual API responses, and a translation-model integration point

## V1.1 engineering hardening additions

- Real evaluation harness: `evals/run_eval.py` now runs a deterministic, rule-based classifier (`services/api/app/classify.py`, also exposed as `POST /cases/classify`) against `evals/datasets/cases.jsonl` and asserts the predicted type/risk against the expected labels, instead of only checking that the dataset rows have the right fields. A classifier regression now fails the build.
- `services/api/tests/`: a pytest suite covering i18n localization, the translation demo-table fallback, the classifier, the new API key gate, and an end-to-end check that `POST /cases/{id}/analyze` is idempotent.
- CI (`.github/workflows/ci.yml`) now runs that pytest suite on every push/PR and adds a `docker-compose-smoke-test` job that boots the real stack with `docker compose up --wait` and curls it, closing the previous gap where the Docker Compose path was never exercised by CI.
- A pilot-stage, off-by-default shared-secret API key gate (`services/api/app/security.py`, `REQUIRE_API_KEY` / `API_KEY`) that can be switched on per-environment without a code change. This is an interim network-boundary control, not a replacement for enterprise SSO/OIDC (still listed below).
- `infra/kubernetes/` manifests gained liveness/readiness probes, resource requests/limits, a `HorizontalPodAutoscaler`, an example `Secret` documenting the required keys, and an example `Ingress`.
- `infra/terraform/` is now a working (if intentionally minimal and AWS-specific) starter — VPC, encrypted RDS PostgreSQL, encrypted ElastiCache Redis, encrypted/KMS-backed S3 — validated with `terraform validate`, replacing what used to be a plain text checklist.
- Fixed a documentation bug: the Docker quick-start section pointed at port 8000, while `docker-compose.yml` maps the API container to host port 8001.

## Intentionally deferred

- enterprise SSO/OIDC/SAML + MFA and fine-grained ABAC (the pilot-stage API key gate above is a network-boundary stopgap, not an identity system)
- production object storage and document OCR/parsing pipeline
- pgvector/OpenSearch/Neo4j projections
- Temporal long-running workflow service
- regional Kubernetes control/data-plane deployment (manifests are now probe/HPA/ingress-ready; an actual regional rollout is still open)
- full offline-first field PWA sync engine
- BIM/GIS/IoT integrations

These are V1.1+ hardening/scale items, not hidden dependencies for the included demo workflow.
