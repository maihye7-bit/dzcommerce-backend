"""
Regression tests for the store_role enum binding.

Background: SQLAlchemy's `Enum(SomePythonEnum, ...)` binds/reads using the
enum MEMBER NAME by default, not `.value`, unless `values_callable` is
given. Our Postgres enum type `store_role` was created by Alembic
migration 0001 with the lowercase values ("owner", "staff"), so the model
must explicitly bind on `.value` to match it.

A plain ORM round-trip test (insert a StoreUser, read back `.role`, assert
it equals `StoreRole.OWNER`) can NOT catch a regression here: if the
binding reverts to using member names, encoding and decoding are still
symmetric with each other, so the round trip still "passes" even though
the raw stored string ("OWNER") would be rejected by the real Postgres
enum type. These tests inspect the raw string explicitly instead.
"""
from sqlalchemy import text

from app.models.store_user import StoreUser, StoreRole


def _register(client, email, password="supersecret1", store_name="Store"):
    resp = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Test User",
            "store_name": store_name,
        },
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


def test_store_role_enum_values_match_migration_0001():
    """
    Pins the exact on-the-wire values the `role` column will bind/compare
    against. Alembic migration 0001 creates the Postgres enum type
    `store_role` with values ("owner", "staff") -- if this test ever
    fails, migration 0001 and this model have drifted apart and a new
    migration is needed to reconcile them.
    """
    enum_values = list(StoreUser.__table__.c.role.type.enums)
    assert enum_values == ["owner", "staff"]


def test_registering_owner_stores_lowercase_role_value(client, db_session):
    """
    Registration creates a StoreUser with role=StoreRole.OWNER. This test
    reads the raw stored string directly (bypassing the ORM's
    Python-Enum decoding) to make sure it is literally "owner", which is
    what the real Postgres `store_role` enum type actually accepts.
    """
    _register(client, "owner_raw_check@example.com", store_name="Raw Check Store")

    raw_role = db_session.execute(text("SELECT role FROM store_users")).scalar()
    assert raw_role == "owner"


def test_store_membership_round_trips_as_owner_enum(client, db_session):
    _register(client, "owner_orm_check@example.com", store_name="ORM Check Store")

    membership = db_session.query(StoreUser).one()
    assert membership.role == StoreRole.OWNER
    assert membership.role.value == "owner"
