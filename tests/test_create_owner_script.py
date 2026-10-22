import pytest
from sqlalchemy.orm import Session

from app.core.security import verify_password
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from scripts import create_owner as owner_script
from scripts.create_owner import BootstrapError, create_owner


def test_create_owner_uses_bcrypt_sha256_and_links_store(db_session: Session):
    store = Store(name="Bootstrap test", slug="bootstrap-test")
    db_session.add(store)
    db_session.commit()

    user = create_owner(
        db_session,
        store_slug="bootstrap-test",
        username="Admin",
        password="bootstrap-secret",
    )

    assert user.email == "admin"
    assert user.hashed_password.startswith("$bcrypt-sha256$")
    assert verify_password("bootstrap-secret", user.hashed_password)
    membership = (
        db_session.query(StoreUser)
        .filter(StoreUser.store_id == store.id, StoreUser.user_id == user.id)
        .one()
    )
    assert membership.role == StoreRole.OWNER
    assert user.is_superuser is False


def test_create_owner_rejects_same_owner_duplicate(db_session: Session):
    store = Store(name="Bootstrap duplicate", slug="bootstrap-duplicate")
    db_session.add(store)
    db_session.commit()
    create_owner(
        db_session,
        store_slug=store.slug,
        username="admin",
        password="first-secret",
    )

    with pytest.raises(BootstrapError, match="already linked"):
        create_owner(
            db_session,
            store_slug=store.slug,
            username="ADMIN",
            password="second-secret",
        )


def test_create_owner_rejects_missing_store_and_reused_username(db_session: Session):
    with pytest.raises(BootstrapError, match="No store"):
        create_owner(
            db_session,
            store_slug="missing-store",
            username="admin",
            password="secret",
        )

    store = Store(name="Other store", slug="other-store")
    db_session.add(store)
    db_session.commit()
    create_owner(
        db_session,
        store_slug=store.slug,
        username="admin",
        password="first-secret",
    )
    second_store = Store(name="Second store", slug="second-store")
    db_session.add(second_store)
    db_session.commit()

    with pytest.raises(BootstrapError, match="already in use"):
        create_owner(
            db_session,
            store_slug=second_store.slug,
            username="admin",
            password="second-secret",
        )


def test_cli_prints_username_but_never_password(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    store = Store(name="CLI bootstrap", slug="cli-bootstrap")
    db_session.add(store)
    db_session.commit()

    class SessionProxy:
        def __getattr__(self, name):
            return getattr(db_session, name)

        def close(self):
            return None

    monkeypatch.setattr(owner_script, "SessionLocal", SessionProxy)
    password = "do-not-print-this-password"
    exit_code = owner_script.main(
        [
            "--store-slug",
            store.slug,
            "--username",
            "cli-admin",
            "--password",
            password,
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert "cli-admin" in captured.out
    assert password not in captured.out
    assert password not in captured.err
