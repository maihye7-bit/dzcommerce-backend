import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.main import app
from app.models.product_image import ProductImage
from app.services import product_image_service, product_image_storage
from app.services.exceptions import ImageStorageError
from tests.helpers import auth_headers, get_first_store_id, register_and_get_token


@pytest.fixture(autouse=True)
def enable_sqlite_foreign_keys(db_engine):
    with db_engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


@pytest.fixture
def image_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", None)
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", None)
    return tmp_path


def _image_bytes(image_format="PNG", size=(12, 8), color=(200, 80, 30)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def _create_store_product(client, email=None):
    email = email or f"image-{uuid.uuid4().hex[:10]}@example.com"
    token = register_and_get_token(client, email, password="TestPassword123!")
    store_id = get_first_store_id(client, token)
    response = client.post(
        f"/api/stores/{store_id}/products",
        json={
            "name": "Image test product",
            "price": "1200.00",
            "sku": f"IMG-{uuid.uuid4().hex[:10]}",
        },
        headers=auth_headers(token),
    )
    assert response.status_code == 201, response.text
    return token, store_id, response.json()


def _upload(
    client,
    token,
    store_id,
    product_id,
    content=None,
    mime_type="image/png",
    filename="product.png",
    is_primary=False,
    display_order=0,
):
    return client.post(
        f"/api/stores/{store_id}/products/{product_id}/images",
        files={"file": (filename, content or _image_bytes(), mime_type)},
        data={"is_primary": str(is_primary).lower(), "display_order": str(display_order)},
        headers=auth_headers(token),
    )


def _storage_key(db_session, image_id):
    return (
        db_session.query(ProductImage.storage_key)
        .filter(ProductImage.id == uuid.UUID(str(image_id)))
        .scalar()
    )


def test_upload_is_persisted_served_and_survives_app_restart(
    image_storage, client, db_session
):
    token, store_id, product = _create_store_product(client)
    response = _upload(client, token, store_id, product["id"])

    assert response.status_code == 201, response.text
    image = response.json()
    assert image["image_url"] == f"/api/product-images/{image['id']}/content"
    stored_path = image_storage / _storage_key(db_session, image["id"])
    assert stored_path.is_file()
    assert image["file_size"] == stored_path.stat().st_size

    image_response = client.get(image["image_url"])
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(image_response.content)) as decoded:
        assert decoded.size == (12, 8)

    with TestClient(app) as restarted_client:
        restarted_response = restarted_client.get(image["image_url"])
    assert restarted_response.status_code == 200
    assert restarted_response.content == image_response.content


@pytest.mark.parametrize(
    ("image_format", "mime_type", "filename"),
    [
        ("JPEG", "image/jpeg", "product.jpg"),
        ("PNG", "image/png", "product.png"),
        ("WEBP", "image/webp", "product.webp"),
    ],
)
def test_upload_accepts_supported_image_formats(
    image_storage, client, image_format, mime_type, filename
):
    token, store_id, product = _create_store_product(client)
    response = _upload(
        client,
        token,
        store_id,
        product["id"],
        _image_bytes(image_format),
        mime_type,
        filename,
    )

    assert response.status_code == 201, response.text
    image = response.json()
    content_response = client.get(image["image_url"])
    assert content_response.status_code == 200
    assert content_response.headers["content-type"] == mime_type
    with Image.open(io.BytesIO(content_response.content)) as decoded:
        assert decoded.format == image_format


@pytest.mark.parametrize(
    ("content", "mime_type"),
    [
        (b"not an image", "image/png"),
        (_image_bytes("JPEG"), "image/png"),
        (b"\x89PNG\r\n\x1a\ncorrupted", "image/png"),
    ],
)
def test_upload_rejects_invalid_corrupted_and_mime_spoofed_images(
    image_storage, client, content, mime_type
):
    token, store_id, product = _create_store_product(client)
    response = _upload(
        client, token, store_id, product["id"], content, mime_type
    )
    assert response.status_code == 400
    assert client.get(
        f"/api/stores/{store_id}/products/{product['id']}/images",
        headers=auth_headers(token),
    ).json() == []


def test_upload_rejects_oversized_and_excessive_dimension_images(image_storage, client):
    token, store_id, product = _create_store_product(client)
    oversized = _upload(
        client,
        token,
        store_id,
        product["id"],
        b"x" * (product_image_service.MAX_FILE_SIZE + 1),
    )
    assert oversized.status_code == 413

    too_wide = _image_bytes(size=(product_image_service.MAX_IMAGE_DIMENSION + 1, 1))
    dimensions = _upload(client, token, store_id, product["id"], too_wide)
    assert dimensions.status_code == 400


def test_listing_primary_selection_and_deletion_promote_next_image(
    image_storage, client, db_session
):
    token, store_id, product = _create_store_product(client)
    first = _upload(
        client, token, store_id, product["id"], display_order=3
    ).json()
    second = _upload(
        client, token, store_id, product["id"], display_order=1
    ).json()

    listing_url = f"/api/stores/{store_id}/products/{product['id']}/images"
    listed = client.get(listing_url, headers=auth_headers(token))
    assert listed.status_code == 200
    assert [image["id"] for image in listed.json()] == [second["id"], first["id"]]
    assert first["is_primary"] is True
    assert second["is_primary"] is False
    with_images = client.get(
        f"/api/stores/{store_id}/products/{product['id']}/with-images",
        headers=auth_headers(token),
    )
    assert with_images.status_code == 200
    assert [image["id"] for image in with_images.json()["images"]] == [
        second["id"],
        first["id"],
    ]

    primary = client.post(
        f"{listing_url}/{second['id']}/primary", headers=auth_headers(token)
    )
    assert primary.status_code == 200
    listed_images = client.get(listing_url, headers=auth_headers(token)).json()
    assert [image["id"] for image in listed_images if image["is_primary"]] == [
        second["id"]
    ]

    first_path = image_storage / _storage_key(db_session, first["id"])
    second_path = image_storage / _storage_key(db_session, second["id"])
    deletion = client.delete(
        f"{listing_url}/{second['id']}", headers=auth_headers(token)
    )
    assert deletion.status_code == 204
    assert not second_path.exists()
    remaining = client.get(listing_url, headers=auth_headers(token)).json()
    assert len(remaining) == 1
    assert remaining[0]["id"] == first["id"]
    assert remaining[0]["is_primary"] is True
    assert first_path.is_file()


def test_reorder_updates_the_complete_product_image_order(image_storage, client):
    token, store_id, product = _create_store_product(client)
    images = [
        _upload(client, token, store_id, product["id"], display_order=index).json()
        for index in range(3)
    ]
    endpoint = f"/api/stores/{store_id}/products/{product['id']}/images"
    reordered = client.post(
        f"{endpoint}/reorder",
        json={"image_ids": [images[2]["id"], images[0]["id"], images[1]["id"]]},
        headers=auth_headers(token),
    )
    assert reordered.status_code == 200
    assert [image["id"] for image in reordered.json()] == [
        images[2]["id"],
        images[0]["id"],
        images[1]["id"],
    ]
    assert [image["display_order"] for image in reordered.json()] == [0, 1, 2]

    partial = client.post(
        f"{endpoint}/reorder",
        json={"image_ids": [images[0]["id"]]},
        headers=auth_headers(token),
    )
    assert partial.status_code == 404


def test_replacing_an_image_removes_the_old_file(image_storage, client, db_session):
    token, store_id, product = _create_store_product(client)
    original = _upload(client, token, store_id, product["id"]).json()
    original_key = _storage_key(db_session, original["id"])
    old_path = image_storage / original_key
    assert old_path.is_file()

    replacement = client.put(
        f"/api/stores/{store_id}/products/{product['id']}/images/{original['id']}/content",
        files={"file": ("replacement.webp", _image_bytes("WEBP", color=(10, 20, 200)), "image/webp")},
        headers=auth_headers(token),
    )
    assert replacement.status_code == 200, replacement.text
    updated = replacement.json()
    assert updated["id"] == original["id"]
    assert updated["mime_type"] == "image/webp"
    updated_key = _storage_key(db_session, updated["id"])
    assert updated_key != original_key
    assert not old_path.exists()
    response = client.get(updated["image_url"])
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"


def test_store_members_cannot_read_or_mutate_another_stores_product_images(
    image_storage, client, db_session
):
    token_a, store_a, product_a = _create_store_product(client)
    token_b, store_b, product_b = _create_store_product(client)
    image_b = _upload(client, token_b, store_b, product_b["id"]).json()
    image_path = image_storage / _storage_key(db_session, image_b["id"])
    image_url_a = f"/api/stores/{store_a}/products/{product_a['id']}/images"

    assert client.get(
        f"/api/stores/{store_b}/products/{product_b['id']}/images",
        headers=auth_headers(token_a),
    ).status_code == 404
    assert _upload(
        client,
        token_a,
        store_a,
        product_b["id"],
    ).status_code == 404
    assert client.get(
        f"{image_url_a}/{image_b['id']}", headers=auth_headers(token_a)
    ).status_code == 404
    assert client.patch(
        f"{image_url_a}/{image_b['id']}",
        json={"is_primary": True, "display_order": 5},
        headers=auth_headers(token_a),
    ).status_code == 404
    assert client.delete(
        f"{image_url_a}/{image_b['id']}", headers=auth_headers(token_a)
    ).status_code == 404
    assert client.get(
        f"/api/stores/{store_b}/products/{product_b['id']}/images",
        headers=auth_headers(token_b),
    ).json()[0]["id"] == image_b["id"]
    assert image_path.is_file()


def test_database_rejects_image_referencing_product_from_another_store(
    image_storage, client, db_session
):
    token_a, store_a, _ = _create_store_product(client)
    token_b, store_b, product_b = _create_store_product(client)
    assert store_a != store_b
    del token_a, token_b
    image = ProductImage(
        id=uuid.uuid4(),
        store_id=uuid.UUID(store_a),
        product_id=uuid.UUID(product_b["id"]),
        storage_key=f"stores/{store_a}/products/{product_b['id']}/invalid.png",
        image_url="/api/product-images/invalid/content",
        mime_type="image/png",
        file_size=1,
        is_primary=False,
        display_order=0,
    )
    db_session.add(image)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_database_enforces_at_most_one_primary_image(image_storage, client, db_session):
    token, store_id, product = _create_store_product(client)
    primary = _upload(client, token, store_id, product["id"]).json()
    duplicate = ProductImage(
        id=uuid.uuid4(),
        store_id=uuid.UUID(store_id),
        product_id=uuid.UUID(product["id"]),
        storage_key=f"stores/{store_id}/products/{product['id']}/duplicate.png",
        image_url="/api/product-images/duplicate/content",
        mime_type="image/png",
        file_size=1,
        is_primary=True,
        display_order=1,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()
    assert (
        db_session.query(ProductImage)
        .filter_by(id=uuid.UUID(primary["id"]))
        .count()
        == 1
    )


def test_storage_failure_is_reported_without_creating_image_metadata(
    image_storage, client, monkeypatch
):
    token, store_id, product = _create_store_product(client)

    def fail_save(_storage_key, _content):
        raise ImageStorageError("simulated storage failure")

    monkeypatch.setattr(product_image_storage, "save_image", fail_save)
    response = _upload(client, token, store_id, product["id"])
    assert response.status_code == 503
    assert client.get(
        f"/api/stores/{store_id}/products/{product['id']}/images",
        headers=auth_headers(token),
    ).json() == []


def test_database_rollback_removes_new_file_after_failed_upload(
    image_storage, client, db_session, monkeypatch
):
    token, store_id, product = _create_store_product(client)
    original_commit = db_session.commit

    def fail_commit():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        product_image_service.create_product_image(
            db_session,
            uuid.UUID(store_id),
            uuid.UUID(product["id"]),
            _image_bytes(),
            "image/png",
            "product.png",
        )
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert (
        db_session.query(ProductImage)
        .filter_by(product_id=uuid.UUID(product["id"]))
        .count()
        == 0
    )
    assert not [path for path in image_storage.rglob("*") if path.is_file()]
    del token


def test_database_rollback_restores_replaced_image_files(
    image_storage, client, db_session, monkeypatch
):
    token, store_id, product = _create_store_product(client)
    original = _upload(client, token, store_id, product["id"]).json()
    original_key = _storage_key(db_session, original["id"])
    original_path = image_storage / original_key
    old_bytes = original_path.read_bytes()
    original_commit = db_session.commit

    def fail_commit():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        product_image_service.replace_product_image(
            db_session,
            uuid.UUID(store_id),
            uuid.UUID(product["id"]),
            uuid.UUID(original["id"]),
            _image_bytes("WEBP"),
            "image/webp",
        )
    monkeypatch.setattr(db_session, "commit", original_commit)
    current = (
        db_session.query(ProductImage)
        .filter_by(id=uuid.UUID(original["id"]))
        .one()
    )
    assert current.storage_key == original_key
    assert original_path.read_bytes() == old_bytes
    assert len([path for path in image_storage.rglob("*") if path.is_file()]) == 1


def test_database_rollback_restores_staged_file_after_failed_delete(
    image_storage, client, db_session, monkeypatch
):
    token, store_id, product = _create_store_product(client)
    image = _upload(client, token, store_id, product["id"]).json()
    image_path = image_storage / _storage_key(db_session, image["id"])
    original_commit = db_session.commit

    def fail_commit():
        raise RuntimeError("simulated database failure")

    monkeypatch.setattr(db_session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="simulated database failure"):
        product_image_service.delete_product_image(
            db_session,
            uuid.UUID(store_id),
            uuid.UUID(product["id"]),
            uuid.UUID(image["id"]),
        )
    monkeypatch.setattr(db_session, "commit", original_commit)
    assert image_path.is_file()
    assert (
        db_session.query(ProductImage)
        .filter_by(id=uuid.UUID(image["id"]))
        .count()
        == 1
    )


def test_railway_storage_requires_a_persistent_volume(image_storage, monkeypatch):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", None)
    with pytest.raises(ImageStorageError, match="persistent volume"):
        product_image_storage.ensure_storage_ready()


def test_railway_storage_rejects_a_directory_outside_the_mounted_volume(
    image_storage, monkeypatch
):
    monkeypatch.setattr(settings, "RAILWAY_ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "RAILWAY_VOLUME_MOUNT_PATH", str(image_storage))
    monkeypatch.setattr(settings, "PRODUCT_IMAGE_STORAGE_DIR", str(image_storage.parent))
    with pytest.raises(ImageStorageError, match="inside the Railway volume"):
        product_image_storage.ensure_storage_ready()


def test_product_image_count_is_limited(image_storage, client):
    token, store_id, product = _create_store_product(client)
    for index in range(product_image_service.MAX_IMAGES_PER_PRODUCT):
        response = _upload(
            client,
            token,
            store_id,
            product["id"],
            display_order=index,
        )
        assert response.status_code == 201, response.text

    over_limit = _upload(client, token, store_id, product["id"])
    assert over_limit.status_code == 400
