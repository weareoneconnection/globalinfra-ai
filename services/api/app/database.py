from contextlib import contextmanager
from contextvars import ContextVar

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, declarative_base, sessionmaker
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
if database_url.startswith("sqlite"):
    kwargs, pool = {"check_same_thread": False}, {}
else:
    kwargs = {}
    pool = {"pool_size": settings.db_pool_size, "max_overflow": settings.db_max_overflow,
            "pool_timeout": settings.db_pool_timeout}
engine = create_engine(database_url, future=True, pool_pre_ping=True, connect_args=kwargs, **pool)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# --- handing a connection back while a model answers --------------------------
#
# A session keeps its pooled connection until its transaction ends. A model
# call takes seconds, so a request that has only read from the database
# should not sit on a connection while it waits: twenty such requests would
# drain the pool and stall every other request, health checks included.
# ``release_idle_connection`` (called before every model call) ends the
# transaction of the session registered with ``releasing_connection`` when
# that transaction has written nothing; a session with pending or flushed
# writes keeps its connection, so a write is never committed half-way.

_releasable: ContextVar[Session | None] = ContextVar("releasable_session", default=None)


@event.listens_for(Session, "after_flush")
def _flushed(session, _context):
    session.info["wrote"] = True


@event.listens_for(Session, "do_orm_execute")
def _executed(state):
    if not state.is_select:
        state.session.info["wrote"] = True


@event.listens_for(Session, "after_transaction_end")
def _transaction_ended(session, transaction):
    if transaction.parent is None:
        session.info.pop("wrote", None)


@contextmanager
def releasing_connection(db: Session):
    """Let model calls made inside this block hand back ``db``'s connection.

    The session should be built with ``expire_on_commit=False`` so objects
    already loaded stay readable after the connection is returned.
    """
    token = _releasable.set(db)
    try:
        yield db
    finally:
        _releasable.reset(token)


def release_idle_connection() -> bool:
    """Return the registered session's connection to the pool if it holds only reads."""
    db = _releasable.get()
    if db is None or not db.in_transaction():
        return False
    if db.new or db.dirty or db.deleted or db.info.get("wrote"):
        return False
    db.commit()
    return True
