"""Product image validation, persistent storage, and metadata operations."""
import io
import logging
import os
import warnings
import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.models.product import Product
from app.models.product_image import ProductImage
from app.services.exceptions import (
    ImageStorageError,
    InvalidImageError,
    NotFoundError,
    ValidationError,
)
from app.services import product_image_storage

logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024
MAX_IMAGE_DIMENSION = 12_000
MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGES_PER_PRODUCT = 10

_FORMAT_BY_MIME = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_EXTENSION_BY_FORMAT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}


@dataclass(frozen=True)
class ValidatedImage:
    content: bytes
    mime_type: str
    width: int
    height: int
    extension: str


def process_image_file(file_content: bytes, mime_type: str) -> ValidatedImage:
    """Decode, validate, and re-encode a single safe JPEG, PNG, or WebP image."""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise InvalidImageError("Unsupported image format. Allowed: JPEG, PNG, WebP")
    if len(file_content) > MAX_FILE_SIZE:
        raise InvalidImageError(
            f"File size exceeds maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)} MB"
        )
    if not file_content:
        raise InvalidImageError("Empty file")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(file_content)) as probe:
                if probe.format != _FORMAT_BY_MIME[mime_type]:
                    raise InvalidImageError("Image content does not match the declared format")
                if getattr(probe, "n_frames", 1) != 1:
                    raise InvalidImageError("Animated images are not supported")
                probe.verify()

            with Image.open(io.BytesIO(file_content)) as source:
                source.load()
                image = ImageOps.exif_transpose(source)
                width, height = image.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_IMAGE_DIMENSION
                    or height > MAX_IMAGE_DIMENSION
                    or width * height > MAX_IMAGE_PIXELS
                ):
                    raise InvalidImageError("Image dimensions exceed the allowed limit")

                if mime_type == "image/jpeg":
                    if image.mode not in {"L", "RGB"}:
                        image = image.convert("RGB")
                    output_format = "JPEG"
                    save_options = {"quality": 90, "optimize": True}
                elif mime_type == "image/png":
                    output_format = "PNG"
                    save_options = {"optimize": True}
                else:
                    if image.mode not in {"RGB", "RGBA"}:
                        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                    output_format = "WEBP"
                    save_options = {"quality": 90, "method": 4}

                output = io.BytesIO()
                image.save(output, format=output_format, **save_options)
                normalized = output.getvalue()
    except InvalidImageError:
        raise
    except (
        OSError,
        ValueError,
        SyntaxError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
    ) as exc:
        raise InvalidImageError("Invalid or corrupted image file") from exc

    if len(normalized) > MAX_FILE_SIZE:
        raise InvalidImageError(
            f"Processed image exceeds maximum allowed: {MAX_FILE_SIZE // (1024 * 1024)} MB"
        )
    return ValidatedImage(
        content=normalized,
        mime_type=mime_type,
        width=width,
        height=height,
        extension=_EXTENSION_BY_FORMAT[output_format],
    )


def validate_image_file(file_content: bytes, mime_type: str) -> Tuple[int, int]:
    """Validate the actual image bytes and return their normalized dimensions."""
    image = process_image_file(file_content, mime_type)
    return image.width, image.height


def generate_storage_key(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    filename: str,
) -> str:
    """Generate an opaque, tenant-scoped key using a validated extension."""
    extension = os.path.splitext(filename)[1].lower()
    if extension not in _EXTENSION_BY_FORMAT.values():
        extension = ".jpg"
    unique = uuid.uuid4().hex
    return f"stores/{store_id}/products/{product_id}/{unique}{extension}"


def _get_product(db: Session, store_id: uuid.UUID, product_id: uuid.UUID) -> Product:
    product = (
        db.query(Product)
        .filter(Product.id == product_id, Product.store_id == store_id)
        .with_for_update()
        .first()
    )
    if product is None:
        raise NotFoundError("Product not found")
    return product


def _clear_primary_images(db: Session, store_id: uuid.UUID, product_id: uuid.UUID) -> None:
    (
        db.query(ProductImage)
        .filter(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
            ProductImage.is_primary.is_(True),
        )
        .update({ProductImage.is_primary: False}, synchronize_session=False)
    )


def create_product_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    file_content: bytes,
    mime_type: str,
    filename: str,
    is_primary: bool = False,
    display_order: int = 0,
) -> ProductImage:
    """Validate and durably store an image, then commit its metadata."""
    product = _get_product(db, store_id, product_id)
    if display_order < 0:
        raise ValidationError("Display order cannot be negative")
    validated = process_image_file(file_content, mime_type)
    image_count = (
        db.query(ProductImage)
        .filter(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product.id,
        )
        .count()
    )
    if image_count >= MAX_IMAGES_PER_PRODUCT:
        raise ValidationError(f"Maximum {MAX_IMAGES_PER_PRODUCT} images per product allowed")

    image_id = uuid.uuid4()
    storage_key = generate_storage_key(
        store_id, product_id, f"image{validated.extension}"
    )
    image = ProductImage(
        id=image_id,
        store_id=store_id,
        product_id=product_id,
        storage_key=storage_key,
        image_url=f"/api/product-images/{image_id}/content",
        thumbnail_url=None,
        mime_type=validated.mime_type,
        file_size=len(validated.content),
        width=validated.width,
        height=validated.height,
        is_primary=is_primary or image_count == 0,
        display_order=display_order,
        processing_status="READY",
    )
    try:
        if image.is_primary:
            _clear_primary_images(db, store_id, product_id)
        product_image_storage.save_image(storage_key, validated.content)
        db.add(image)
        db.commit()
    except Exception:
        db.rollback()
        try:
            product_image_storage.delete_image(storage_key)
        except ImageStorageError:
            logger.exception("Could not clean up image file after failed database commit")
        raise
    db.refresh(image)
    return image


def replace_product_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    file_content: bytes,
    mime_type: str,
) -> ProductImage:
    """Replace image bytes without changing its identity or leaving old files behind."""
    image = get_product_image(db, store_id, product_id, image_id)
    validated = process_image_file(file_content, mime_type)
    old_storage_key = image.storage_key
    new_storage_key = generate_storage_key(
        store_id, product_id, f"image{validated.extension}"
    )
    image.storage_key = new_storage_key
    image.image_url = f"/api/product-images/{image.id}/content"
    image.thumbnail_url = None
    image.mime_type = validated.mime_type
    image.file_size = len(validated.content)
    image.width = validated.width
    image.height = validated.height
    image.processing_status = "READY"
    image.embedding_model = None
    image.embedding_version = None
    staged_old_key: str | None = None
    try:
        product_image_storage.save_image(new_storage_key, validated.content)
        staged_old_key = product_image_storage.stage_image_deletion(old_storage_key)
        db.commit()
    except Exception:
        db.rollback()
        try:
            product_image_storage.delete_image(new_storage_key)
        except ImageStorageError:
            logger.exception("Could not clean up replacement after failed database commit")
        try:
            product_image_storage.restore_staged_image(old_storage_key, staged_old_key)
        except ImageStorageError:
            logger.exception("Could not restore old image after failed replacement")
        raise

    db.refresh(image)
    try:
        product_image_storage.purge_staged_image(staged_old_key)
    except ImageStorageError:
        logger.exception("Replacement is committed but the previous image file remains")
        raise
    return image


def get_product_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
) -> ProductImage:
    """Get an image only when both the product and image belong to this store."""
    _get_product(db, store_id, product_id)
    image = (
        db.query(ProductImage)
        .filter(
            ProductImage.id == image_id,
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
        )
        .first()
    )
    if image is None:
        raise NotFoundError("Image not found")
    return image


def list_product_images(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
) -> List[ProductImage]:
    """List images only for a product owned by the requested store."""
    _get_product(db, store_id, product_id)
    return (
        db.query(ProductImage)
        .filter(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
        )
        .order_by(
            ProductImage.display_order,
            ProductImage.created_at,
            ProductImage.id,
        )
        .all()
    )


def update_product_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    is_primary: Optional[bool] = None,
    display_order: Optional[int] = None,
) -> ProductImage:
    """Update primary state or display order for an owned image."""
    image = get_product_image(db, store_id, product_id, image_id)
    if display_order is not None and display_order < 0:
        raise ValidationError("Display order cannot be negative")
    if is_primary is True and not image.is_primary:
        _clear_primary_images(db, store_id, product_id)
        image.is_primary = True
    elif is_primary is False:
        image.is_primary = False

    if display_order is not None:
        image.display_order = display_order

    db.commit()
    db.refresh(image)
    return image


def delete_product_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
) -> None:
    """Delete an owned image and promote the next ordered image if necessary."""
    image = get_product_image(db, store_id, product_id, image_id)
    storage_key = image.storage_key
    staged_key = product_image_storage.stage_image_deletion(storage_key)
    if image.is_primary:
        next_image = (
            db.query(ProductImage)
            .filter(
                ProductImage.store_id == store_id,
                ProductImage.product_id == product_id,
                ProductImage.id != image_id,
            )
            .order_by(
                ProductImage.display_order,
                ProductImage.created_at,
                ProductImage.id,
            )
            .first()
        )
        image.is_primary = False
        db.flush()
        if next_image is not None:
            next_image.is_primary = True

    db.delete(image)
    try:
        db.commit()
    except Exception:
        db.rollback()
        try:
            product_image_storage.restore_staged_image(storage_key, staged_key)
        except ImageStorageError:
            logger.exception("Could not restore image file after failed database deletion")
        raise

    product_image_storage.purge_staged_image(staged_key)


def set_primary_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
) -> ProductImage:
    """Set one image as primary, clearing any previous primary."""
    return update_product_image(db, store_id, product_id, image_id, is_primary=True)


def reorder_images(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_ids: List[uuid.UUID],
) -> List[ProductImage]:
    """Set a deterministic order using every image of the owned product once."""
    _get_product(db, store_id, product_id)
    images = (
        db.query(ProductImage)
        .filter(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
        )
        .all()
    )
    image_ids_set = set(image_ids)
    if len(image_ids_set) != len(image_ids) or image_ids_set != {image.id for image in images}:
        raise NotFoundError("Image order must contain each product image exactly once")

    images_by_id = {image.id: image for image in images}
    for index, image_id in enumerate(image_ids):
        images_by_id[image_id].display_order = index
    db.commit()
    return list_product_images(db, store_id, product_id)


def get_primary_image(
    db: Session,
    store_id: uuid.UUID,
    product_id: uuid.UUID,
) -> Optional[ProductImage]:
    """Get the primary image for an owned product."""
    _get_product(db, store_id, product_id)
    return (
        db.query(ProductImage)
        .filter(
            ProductImage.store_id == store_id,
            ProductImage.product_id == product_id,
            ProductImage.is_primary.is_(True),
        )
        .first()
    )


def get_image_by_id(db: Session, image_id: uuid.UUID) -> ProductImage:
    """Load image metadata for the public image-content URL."""
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if image is None:
        raise NotFoundError("Image not found")
    return image


def mark_image_processing(
    db: Session,
    image_id: uuid.UUID,
    status: str,
    embedding_model: Optional[str] = None,
    embedding_version: Optional[str] = None,
) -> ProductImage:
    """Update image processing status (called by a background worker)."""
    image = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if image is None:
        raise NotFoundError("Image not found")
    image.processing_status = status
    if embedding_model:
        image.embedding_model = embedding_model
    if embedding_version:
        image.embedding_version = embedding_version
    db.commit()
    db.refresh(image)
    return image


def get_images_pending_processing(
    db: Session,
    store_id: Optional[uuid.UUID] = None,
    limit: int = 50,
) -> List[ProductImage]:
    """Get images that need visual embedding processing."""
    query = db.query(ProductImage).filter(ProductImage.processing_status == "PENDING")
    if store_id:
        query = query.filter(ProductImage.store_id == store_id)
    return query.order_by(ProductImage.created_at, ProductImage.id).limit(limit).all()
