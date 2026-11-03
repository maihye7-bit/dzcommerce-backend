"""Local filesystem storage for product images."""
import logging
import os
import tempfile
import uuid
from pathlib import Path

from app.config import settings
from app.services.exceptions import ImageStorageError

logger = logging.getLogger(__name__)


def get_storage_root() -> Path:
    """Resolve the image directory, requiring a mounted volume on Railway."""
    railway_mount = settings.RAILWAY_VOLUME_MOUNT_PATH
    configured_root = settings.PRODUCT_IMAGE_STORAGE_DIR

    if settings.RAILWAY_ENVIRONMENT:
        if not railway_mount:
            raise ImageStorageError(
                "Railway image storage requires a mounted persistent volume "
                "and RAILWAY_VOLUME_MOUNT_PATH."
            )
        mount_root = Path(railway_mount).resolve()
        root = Path(configured_root).resolve() if configured_root else mount_root / "product-images"
        try:
            root.relative_to(mount_root)
        except ValueError as exc:
            raise ImageStorageError(
                "PRODUCT_IMAGE_STORAGE_DIR must be inside the Railway volume."
            ) from exc
        return root

    if configured_root:
        return Path(configured_root).resolve()
    return Path(__file__).resolve().parents[2] / "var" / "product-images"


def ensure_storage_ready() -> None:
    """Create the storage directory and fail early when it is not writable."""
    root = get_storage_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=root, prefix=".write-check-", delete=True):
            pass
    except OSError as exc:
        raise ImageStorageError(f"Product image storage is not writable: {root}") from exc


def path_for_key(storage_key: str) -> Path:
    """Resolve a database key without permitting paths outside the storage root."""
    root = get_storage_root()
    path = (root / storage_key).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ImageStorageError("Invalid product image storage key.") from exc
    return path


def save_image(storage_key: str, content: bytes) -> None:
    """Atomically persist image bytes under the configured storage root."""
    destination = path_for_key(storage_key)
    temporary_path: Path | None = None
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=".upload-",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, destination)
    except OSError as exc:
        logger.exception("Could not persist product image key %s", storage_key)
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Could not remove incomplete product image upload")
        raise ImageStorageError("Could not save product image to persistent storage.") from exc


def delete_image(storage_key: str) -> None:
    """Remove a stored image; a missing file is already deleted."""
    try:
        path_for_key(storage_key).unlink(missing_ok=True)
    except OSError as exc:
        raise ImageStorageError("Could not remove product image from storage.") from exc


def stage_image_deletion(storage_key: str) -> str | None:
    """Atomically hide an image until its database deletion commits."""
    source = path_for_key(storage_key)
    if not source.exists():
        return None
    staged_key = f".trash/{uuid.uuid4().hex}"
    staged = path_for_key(staged_key)
    try:
        staged.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, staged)
    except OSError as exc:
        raise ImageStorageError("Could not stage product image deletion.") from exc
    return staged_key


def restore_staged_image(storage_key: str, staged_key: str | None) -> None:
    """Restore a staged image if its database transaction rolls back."""
    if staged_key is None:
        return
    try:
        os.replace(path_for_key(staged_key), path_for_key(storage_key))
    except OSError as exc:
        raise ImageStorageError("Could not restore product image after rollback.") from exc


def purge_staged_image(staged_key: str | None) -> None:
    """Permanently remove a staged image after its database transaction commits."""
    if staged_key is None:
        return
    try:
        path_for_key(staged_key).unlink(missing_ok=True)
    except OSError as exc:
        raise ImageStorageError("Could not finish removing product image.") from exc


def read_image(storage_key: str) -> Path:
    """Return a stored image path or fail with a storage error."""
    path = path_for_key(storage_key)
    if not path.is_file():
        raise ImageStorageError("Stored product image is missing.")
    return path
