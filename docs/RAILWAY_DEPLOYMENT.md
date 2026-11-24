# Railway deployment contract

This document defines the V6 production deployment contract. It is not proof
that a Railway environment, identity provider, signed artifact, restore drill,
or external service has been configured. Record those results separately in
the signed release evidence and production acceptance pack.

GlobalInfra AI is an isolated monorepo and must be deployed as separate
services. Railpack cannot infer an application from the repository root.

## Required services

| Railway resource | Source / provider | Root directory | Health check |
| --- | --- | --- | --- |
| `globalinfra-ai` (Web) | `weareoneconnection/globalinfra-ai` | `/apps/web` | public `/readyz` |
| `api` | `ghcr.io/weareoneconnection/globalinfra-api@sha256:<approved-digest>` | n/a | `/readyz` |
| PostgreSQL | Railway managed PostgreSQL | n/a | managed |
| durable queue / Redis | approved managed provider | n/a | provider-specific |
| object storage | approved regional provider | n/a | provider-specific |

`/healthz` deliberately performs no login redirect and discloses no tenant
data. It proves only that the Next.js process can answer. `/readyz` additionally
fails closed when the selected Web auth mode is unsupported or when OIDC and
encrypted-session configuration is missing or invalid. It performs no live
identity-provider or API call, so it does not by itself prove the OIDC flow,
API connectivity, release evidence, or production readiness.

The Web source build detects the `Dockerfile` inside its source root. A
production API release instead uses the commit-addressed image produced from
`services/api/Dockerfile.release`; the normal `Dockerfile` remains the
zero-config development and demo image. Both listen on Railway's injected
`PORT`. Do not deploy `docker-compose.yml` as one Railway service.

## API variables

The API service must explicitly set `ENV=production`; do not rely on the
Railway environment having a particular display name. Production validation
is intentionally fail-closed.

```dotenv
ENV=production
PORT=8000
DATABASE_URL=${{Postgres.DATABASE_URL}}
AUTH_MODE=oidc
REQUIRE_API_KEY=true
API_KEY=<separate high-entropy server-to-server key>
OIDC_ISSUER=https://<issuer>
OIDC_AUDIENCE=<API audience>
OIDC_JWKS_URL=https://<issuer>/.../jwks
DEFAULT_ORGANIZATION_ID=<explicit production tenant>
SOD_ENFORCED=true

COMPETITION_SIGNING_SECRET=<judge-ticket key>
AUDIT_SIGNING_KEY=<governance-receipt key>
AUDIT_SIGNING_KEY_ID=<versioned active key id>
AUDIT_VERIFICATION_KEYS={}
EVIDENCE_VERIFICATION_PUBLIC_KEY=<Ed25519 public key PEM>
EVIDENCE_BUNDLE_REQUIRED=true
RELEASE_EVIDENCE_PATH=/run/globalinfra-evidence/release-evidence.json

QUEUE_URL=<non-local durable Redis URL used by the audit outbox stream>
OBJECT_STORAGE_ENDPOINT=<regional object-store endpoint>
OBJECT_STORAGE_BUCKET=<bucket name>
DATA_RESIDENCY_REGION=<approved region>
CORS_ORIGINS=https://<web-domain>
```

Also configure the approved LLM provider, backup/RPO/RTO policy, connector
webhook secret, OIDC claim names, and any retired audit verification keys from
the production secret manager. The three signing domains above must not reuse
the API key or one another. The API runtime receives only the release-evidence
public key; the Ed25519 private key remains in CI/KMS.

## Web OIDC session variables

Set these on the Web service. Values without a literal example are deployment
secrets or environment-specific configuration and must not be committed.

```dotenv
PORT=3000
API_AUTH_MODE=oidc
API_INTERNAL_URL=http://api.railway.internal:8000
API_SERVICE_KEY=<same value as API service API_KEY>

OIDC_ISSUER=https://<issuer>
OIDC_AUDIENCE=<same API audience verified by the API>
OIDC_JWKS_URL=https://<issuer>/.../jwks
OIDC_CLIENT_ID=<registered Web OAuth client id>
OIDC_CLIENT_SECRET=<omit or leave empty for a public PKCE client>
OIDC_AUTHORIZATION_ENDPOINT=https://<issuer>/.../authorize
OIDC_TOKEN_ENDPOINT=https://<issuer>/.../token
OIDC_REDIRECT_URI=https://<web-domain>/auth/callback
WEB_SESSION_SECRET=<at least 32 characters of high-entropy random data>
```

Register the exact `OIDC_REDIRECT_URI` with the identity provider. The Web flow
uses `/auth/login`, `/auth/callback`, and `/auth/logout`; a successful callback
creates a server-managed, encrypted HTTP-only session. Tenant API requests are
proxied with that user's access token. `API_SERVICE_KEY` stays server-side and
is only a compatibility credential for explicitly public competition routes;
it must never substitute for a user's OIDC identity on tenant routes.

Do not expose the client secret, session secret, service key, or access token
through `NEXT_PUBLIC_*` variables. Rotate `WEB_SESSION_SECRET` through a
planned session invalidation because existing cookies cannot be decrypted
after an uncoordinated rotation.

## Signed evidence and immutable API image

The protected `release-signing` GitHub Environment gates two default-branch
jobs in `.github/workflows/ci.yml`:

1. `release-evidence` runs the evaluations and API tests, signs the envelope
   with Ed25519, exports only the public key, and uploads the complete raw
   evidence bundle;
2. `release-image` cryptographically verifies that envelope against the
   checked-out commit and current datasets, builds
   `services/api/Dockerfile.release`, pushes the single commit tag to GHCR,
   creates GitHub build provenance for the image digest, and emits a
   `globalinfra.release-manifest.v1` artifact.

The release image stores the signed envelope at
`/run/globalinfra-evidence/release-evidence.json`, embeds the source commit and
evidence SHA-256 as OCI metadata, and runs as a non-root user that cannot
replace the root-owned evidence file. The manifest binds the evidence digest,
public-key fingerprint, source commit, CI run and immutable registry digest
without creating a circular image digest.

Before starting the API for a release, the promotion operator must:

1. download the release manifest produced for the intended commit;
2. verify the GitHub artifact and build-provenance attestation;
3. configure Railway with the manifest's exact `image.reference` containing
   `@sha256:...`—never a mutable tag;
4. set the matching public key in `EVIDENCE_VERIFICATION_PUBLIC_KEY` and never
   provide `EVIDENCE_SIGNING_PRIVATE_KEY` to Railway;
5. verify that the runtime reports the same commit and evidence digest before
   directing traffic to it.

With `ENV=production` and `EVIDENCE_BUNDLE_REQUIRED=true`, a missing artifact
path or invalid production configuration must stop startup. A present but
invalid, mismatched, or incomplete envelope remains `NOT_READY`; never convert
that state into a deployment success claim. Railway promotion remains an
explicit approval step because repository pushes must not silently replace a
production digest.

Before merging the first V6.1 release to the default branch, disconnect the
legacy API service from GitHub `main` autodeploy. Otherwise Railway may start a
source build before the protected evidence image has been approved.

## Deployment order

1. Run the V6 CI on the intended commit and approve the protected
   `release-signing` jobs.
2. Verify the GHCR provenance and release manifest, then record the immutable
   API image digest.
3. Provision PostgreSQL, durable queue/Redis, object storage, backup policy,
   and approved regional networking.
4. Provision API and Web secrets from a secret manager.
5. Stage the exact manifest image digest as the API source.
6. Deploy `api`; run `alembic upgrade head` as the pre-deploy command.
7. Deploy `globalinfra-ai` and create its public HTTPS domain.
8. Register the final `/auth/callback` URI with the identity provider and test
   login, logout, expiry, invalid state/nonce, and role/project denial.

## Post-deploy verification

At minimum, retain output or screenshots for these checks:

```bash
curl -fsS https://<web-domain>/healthz
curl -fsS https://<web-domain>/readyz
curl -fsS https://<api-domain>/readyz
curl -fsS https://<api-domain>/platform/production-readiness
```

Also verify in a browser that a protected route redirects through
`/auth/login`, returns to `/auth/callback`, and can call `/identity/me` with the
expected organization, roles, and project grants. Confirm that an identity
without a project grant is denied and that `/healthz` and `/readyz` remain
public without disclosing secret values.

`/platform/production-readiness` can only attest the controls implemented by
the service. Restore drills, queue replay/dead-letter tests, object-retention
proof, SLO history, data-residency approval, and external penetration testing
remain separate acceptance evidence.
