import uuid
from typing import List

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.deps import get_current_store_owner, get_store_membership
from app.database import get_db
from app.models.store_user import StoreUser
from app.schemas.product_image import (
    ProductImageOut,
    ProductImageReorder,
    ProductImageUpdate,
    ProductWithImagesOut,
)
from app.services import product_image_storage
from app.services import product_image_service, product_service
from app.services.exceptions import (
    ImageStorageError,
    InvalidImageError,
    NotFoundError,
    ValidationError,
)

router = APIRouter(prefix="/stores/{store_id}/products", tags=["product-images"])
media_router = APIRouter(tags=["product-images"])


# --- Product Image Endpoints ---

@router.post(
    "/{product_id}/images",
    response_model=ProductImageOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    file: UploadFile = File(...),
    is_primary: bool = Form(False),
    display_order: int = Form(0),
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """
    Upload an image for a product.
    The file is validated and metadata is stored.
    """
    # Verify product exists and belongs to store
    try:
        product_service.get_product(db, store_id, product_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    # Validate file
    if not file.content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content-Type is required")

    file_content = await file.read(product_image_service.MAX_FILE_SIZE + 1)
    if len(file_content) > product_image_service.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed: {product_image_service.MAX_FILE_SIZE // (1024 * 1024)} MB",
        )

    try:
        image = product_image_service.create_product_image(
            db=db,
            store_id=store_id,
            product_id=product_id,
            file_content=file_content,
            mime_type=file.content_type,
            filename=file.filename or "image.jpg",
            is_primary=is_primary,
            display_order=display_order,
        )
        return image
    except InvalidImageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    except ImageStorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.put(
    "/{product_id}/images/{image_id}/content",
    response_model=ProductImageOut,
)
async def replace_product_image_content(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    file: UploadFile = File(...),
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Replace image bytes while retaining the image ID and display metadata."""
    file_content = await file.read(product_image_service.MAX_FILE_SIZE + 1)
    if len(file_content) > product_image_service.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds maximum allowed: {product_image_service.MAX_FILE_SIZE // (1024 * 1024)} MB",
        )
    if not file.content_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Content-Type is required")
    try:
        return product_image_service.replace_product_image(
            db,
            store_id,
            product_id,
            image_id,
            file_content,
            file.content_type,
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except InvalidImageError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except ImageStorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))


@router.get("/{product_id}/images", response_model=List[ProductImageOut])
def list_product_images(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    """List all images for a product."""
    try:
        return product_image_service.list_product_images(db, store_id, product_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


@router.get("/{product_id}/images/primary", response_model=ProductImageOut)
def get_primary_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    """Get the primary image for a product."""
    try:
        image = product_image_service.get_primary_image(db, store_id, product_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No primary image found")
    return image


@router.get("/{product_id}/images/{image_id}", response_model=ProductImageOut)
def get_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    """Get a specific product image."""
    try:
        return product_image_service.get_product_image(db, store_id, product_id, image_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")


@router.patch("/{product_id}/images/{image_id}", response_model=ProductImageOut)
def update_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    payload: ProductImageUpdate,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Update image metadata (primary flag, display order)."""
    try:
        update_data = payload.model_dump(exclude_unset=True)
        return product_image_service.update_product_image(
            db,
            store_id,
            product_id,
            image_id,
            is_primary=update_data.get("is_primary"),
            display_order=update_data.get("display_order"),
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.delete("/{product_id}/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Delete a product image."""
    try:
        product_image_service.delete_product_image(db, store_id, product_id, image_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except ImageStorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    return None


@router.post("/{product_id}/images/reorder", response_model=List[ProductImageOut])
def reorder_product_images(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    payload: ProductImageReorder,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Reorder product images."""
    try:
        return product_image_service.reorder_images(db, store_id, product_id, payload.image_ids)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="One or more images not found")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post("/{product_id}/images/{image_id}/primary", response_model=ProductImageOut)
def set_primary_product_image(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    image_id: uuid.UUID,
    membership: StoreUser = Depends(get_current_store_owner),
    db: Session = Depends(get_db),
):
    """Set an image as the primary image for a product."""
    try:
        return product_image_service.set_primary_image(db, store_id, product_id, image_id)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")


# --- Enhanced Product Endpoints with Images ---

@router.get("/{product_id}/with-images", response_model=ProductWithImagesOut)
def get_product_with_images(
    store_id: uuid.UUID,
    product_id: uuid.UUID,
    membership: StoreUser = Depends(get_store_membership),
    db: Session = Depends(get_db),
):
    """Get a product with all its images."""
    try:
        product = product_service.get_product(db, store_id, product_id)
        images = product_image_service.list_product_images(db, store_id, product_id)
        return ProductWithImagesOut(
            id=product.id,
            store_id=product.store_id,
            name=product.name,
            description=product.description,
            sku=product.sku,
            price=product.base_price,
            is_active=product.is_active,
            created_at=product.created_at,
            updated_at=product.updated_at,
            images=images,
        )
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")


@media_router.get(
    "/product-images/{image_id}/content",
    name="serve_product_image",
    include_in_schema=False,
)
def serve_product_image(image_id: uuid.UUID, db: Session = Depends(get_db)):
    """Serve a validated product image by its unguessable ID."""
    try:
        image = product_image_service.get_image_by_id(db, image_id)
        path = product_image_storage.read_image(image.storage_key)
    except NotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except ImageStorageError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))

    return FileResponse(
        path,
        media_type=image.mime_type,
        filename=path.name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )