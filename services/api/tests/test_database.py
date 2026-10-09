from app.database import normalize_database_url


def test_railway_postgres_url_uses_psycopg3_driver():
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == (
        "postgresql+psycopg://user:pass@host:5432/db"
    )


def test_explicit_driver_and_sqlite_urls_are_unchanged():
    assert normalize_database_url("postgresql+psycopg://host/db") == "postgresql+psycopg://host/db"
    assert normalize_database_url("sqlite:///demo.db") == "sqlite:///demo.db"
