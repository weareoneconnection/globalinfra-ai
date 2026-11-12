import { defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const apiSource = github("weareoneconnection/globalinfra-ai", {
    branch: "main",
    checkSuites: true,
    rootDirectory: "services/api",
  });
  const webSource = github("weareoneconnection/globalinfra-ai", {
    branch: "main",
    checkSuites: true,
    rootDirectory: "apps/web",
  });

  const Postgres = postgres("Postgres", { region: "asia-southeast1-eqsg3a" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "asia-southeast1-eqsg3a", sizeMB: 5000 });
  const api = service("api", {
    source: apiSource,
    healthcheck: "/readyz",
    healthcheckTimeout: 300,
    preDeploy: "alembic upgrade head",
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      API_KEY: preserve(),
      AUDIT_SIGNING_KEY: preserve(),
      AUDIT_SIGNING_KEY_ID: preserve(),
      AUDIT_VERIFICATION_KEYS: preserve(),
      COMPETITION_SIGNING_SECRET: preserve(),
      CORS_ORIGINS: preserve(),
      DATA_RESIDENCY_REGION: "asia-southeast1-eqsg3a",
      DEFAULT_ORGANIZATION_ID: preserve(),
      EVIDENCE_BUNDLE_REQUIRED: "true",
      EVIDENCE_VERIFICATION_PUBLIC_KEY: preserve(),
      ENV: "production",
      LLM_MODE: "openai",
      OBJECT_STORAGE_ENDPOINT: preserve(),
      OBJECT_STORAGE_BUCKET: preserve(),
      OPENAI_COMPAT_API_KEY: preserve(),
      OPENAI_COMPAT_BASE_URL: preserve(),
      OPENAI_COMPAT_MODEL: preserve(),
      OIDC_AUDIENCE: preserve(),
      OIDC_ISSUER: preserve(),
      OIDC_JWKS_URL: preserve(),
      PORT: "8000",
      QUEUE_URL: preserve(),
      RELEASE_EVIDENCE_PATH: preserve(),
      AUTH_MODE: "oidc",
      REQUIRE_API_KEY: "true",
      SOD_ENFORCED: "true",
    },
    replicas: { "asia-southeast1-eqsg3a": 1 },
  });
  const web = service("globalinfra-ai", {
    source: webSource,
    healthcheck: "/readyz",
    healthcheckTimeout: 300,
    env: {
      API_AUTH_MODE: "oidc",
      API_INTERNAL_URL: "http://api.railway.internal:8000",
      API_SERVICE_KEY: preserve(),
      OIDC_AUDIENCE: preserve(),
      OIDC_AUTHORIZATION_ENDPOINT: preserve(),
      OIDC_CLIENT_ID: preserve(),
      OIDC_CLIENT_SECRET: preserve(),
      OIDC_ISSUER: preserve(),
      OIDC_JWKS_URL: preserve(),
      OIDC_REDIRECT_URI: preserve(),
      OIDC_TOKEN_ENDPOINT: preserve(),
      PORT: "3000",
      WEB_SESSION_SECRET: preserve(),
    },
    replicas: { "asia-southeast1-eqsg3a": 1 },
  });

  return project("exemplary-gentleness", {
    resources: [api, Postgres, web, postgresVolume],
  });
});
