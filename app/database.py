from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        engine = create_engine(database_url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(conn, _record):  # SQLite ignores ON DELETE CASCADE otherwise
            conn.execute("PRAGMA foreign_keys=ON")

        return engine

    return create_engine(
        database_url,
        # Free Postgres tiers allow few connections; keep the pool small
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=300,
        # Supabase's transaction pooler (port 6543) doesn't support prepared statements
        connect_args={"prepare_threshold": None},
    )


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)
