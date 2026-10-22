"""
Test setup.

We run tests against an in-memory SQLite database instead of PostgreSQL
so the suite is fast and has no external dependency.

No UUID monkey-patching is needed: as of SQLAlchemy 2.0, the generic
`Uuid` type (which `sqlalchemy.dialects.postgresql.UUID` is built on top
of, and which our models use) already knows how to represent Python
`uuid.UUID` values on backends without a native UUID column type — it
falls back to CHAR(32)/CHAR(36) and converts automatically. This means
`app/models` can be used completely unchanged against SQLite here; only
the test engine differs from the PostgreSQL one used in production.

IMPORTANT: `poolclass=StaticPool` is required. A SQLite `:memory:`
database lives entirely inside the DBAPI connection that created it --
it is NOT shared across different connections the way a real file or a
PostgreSQL database is. Without StaticPool, SQLAlchemy is free to hand
out a different underlying connection for later Session/TestClient
usage than the one `Base.metadata.create_all()` used, and that later
connection then sees a completely empty, table-less database (raising
"no such table: users" etc.) even though table creation itself
succeeded moments earlier. StaticPool forces every checkout from this
engine, for its entire lifetime, to reuse the exact same connection.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 ensure models are registered on Base.metadata
from app.database import Base, get_db
from app.main import app


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture(scope="function")
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    TestingSessionLocal = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
