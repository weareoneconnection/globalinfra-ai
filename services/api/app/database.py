from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from .config import settings

def normalize_database_url(url: str) -> str:
    """Use the installed psycopg 3 driver for generic PostgreSQL URLs.

    Railway and several other managed Postgres providers expose a conventional
    ``postgresql://`` URL. SQLAlchemy otherwise interprets that scheme as the
    legacy psycopg2 driver, while this service intentionally ships psycopg 3.
    Explicit driver URLs and non-Postgres databases are left untouched.
    """
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


database_url = normalize_database_url(settings.database_url)
kwargs = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
