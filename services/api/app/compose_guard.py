"""Fail closed before local Docker Compose touches an external database."""

from __future__ import annotations

import os

from sqlalchemy.engine import make_url


LOCAL_COMPOSE_DATABASE_HOSTS = {"postgres", "localhost", "127.0.0.1", "::1"}


def validate_compose_database(
    database_url: str,
    *,
    allow_external: bool = False,
) -> None:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required by the Compose database guard.")
    try:
        parsed = make_url(database_url)
    except Exception as exc:
        raise RuntimeError("DATABASE_URL is invalid.") from exc
    if parsed.get_backend_name() == "sqlite":
        return
    hostname = (parsed.host or "").lower()
    if hostname in LOCAL_COMPOSE_DATABASE_HOSTS or allow_external:
        return
    raise RuntimeError(
        "Refusing to run local Compose migrations against an external database. "
        "Use .env.example, or explicitly set ALLOW_EXTERNAL_COMPOSE_DATABASE=true."
    )


def main() -> None:
    validate_compose_database(
        os.getenv("DATABASE_URL", ""),
        allow_external=(
            os.getenv("ALLOW_EXTERNAL_COMPOSE_DATABASE", "").strip().lower()
            == "true"
        ),
    )
    print("Compose database guard accepted the configured database target.")


if __name__ == "__main__":
    main()
