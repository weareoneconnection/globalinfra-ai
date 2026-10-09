import { defineRailway, github, postgres, preserve, project, service, volume } from "railway/iac";

export default defineRailway(() => {
  const apiSource = github("weareoneconnection/globalinfra-ai", {
    branch: "main",
    checkSuites: false,
    rootDirectory: "services/api",
  });
  const webSource = github("weareoneconnection/globalinfra-ai", {
    branch: "main",
    checkSuites: false,
    rootDirectory: "apps/web",
  });

  const Postgres = postgres("Postgres", { region: "asia-southeast1-eqsg3a" });
  Postgres.networking = { privateNetworkEndpoint: "postgres" };
  const postgresVolume = volume("postgres-volume", { alerts: { usage: { "100": {}, "80": {}, "95": {} } }, allowOnlineResize: true, region: "asia-southeast1-eqsg3a", sizeMB: 5000 });
  const api = service("api", {
    source: apiSource,
    healthcheck: "/health",
    healthcheckTimeout: 300,
    preDeploy: "alembic upgrade head",
    env: {
      DATABASE_URL: Postgres.env.DATABASE_URL,
      LLM_MODE: "openai",
      OPENAI_COMPAT_API_KEY: preserve(),
      OPENAI_COMPAT_BASE_URL: preserve(),
      OPENAI_COMPAT_MODEL: preserve(),
      PORT: "8000",
      REQUIRE_API_KEY: "false",
    },
    replicas: { "asia-southeast1-eqsg3a": 1 },
  });
  const web = service("globalinfra-ai", {
    source: webSource,
    healthcheck: "/",
    healthcheckTimeout: 300,
    env: {
      API_INTERNAL_URL: "http://api.railway.internal:8000",
      DATABASE_URL: preserve(),
      LLM_MODE: preserve(),
      OPENAI_COMPAT_API_KEY: preserve(),
      OPENAI_COMPAT_BASE_URL: preserve(),
      OPENAI_COMPAT_MODEL: preserve(),
      PORT: "3000",
      POSTGRES_DB: preserve(),
      POSTGRES_PASSWORD: preserve(),
      POSTGRES_USER: preserve(),
      REDIS_URL: preserve(),
    },
    replicas: { "asia-southeast1-eqsg3a": 1 },
  });

  return project("exemplary-gentleness", {
    resources: [api, Postgres, web, postgresVolume],
  });
});
