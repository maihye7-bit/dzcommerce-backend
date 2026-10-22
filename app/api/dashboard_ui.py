from __future__ import annotations

import json
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_password, verify_password
from app.api.auth import _enforce_rate_limit
from app.database import get_db
from app.models.conversation import Conversation, Message
from app.models.customer import Customer
from app.models.inventory import InventoryItem
from app.models.order import Order, OrderItem, OrderStatus
from app.models.product import Product, ProductVariant
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User
from app.services import inventory_service, product_service
from app.services.exceptions import DuplicateSKUError, NotFoundError, ValidationError


router = APIRouter(prefix="/dashboard", tags=["admin-dashboard"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[2] / "templates")
)

ORDER_STATUS_LABELS = {
    "draft": "مسودة",
    "waiting_confirmation": "بانتظار التأكيد",
    "confirmed": "مؤكد",
    "ready_to_ship": "جاهز للشحن",
    "shipped": "تم الشحن",
    "delivered": "تم التسليم",
    "cancelled": "ملغي",
    "human_handoff": "محوّل لموظف",
}
CONVERSATION_STATUS_LABELS = {
    "active": "نشطة",
    "closed": "مغلقة",
    "handoff": "محوّلة لموظف",
}
CHANNEL_LABELS = {
    "messenger": "ماسنجر",
    "facebook": "فيسبوك",
    "instagram": "إنستغرام",
    "whatsapp": "واتساب",
    "test": "اختبار",
}


def _money(value: Any) -> str:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return "0"
    return f"{amount:,.2f}".rstrip("0").rstrip(".")


def _order_reference(order: Order) -> str:
    return f"ORD-{order.id.hex[:8].upper()}"


def _order_status_label(value: Any) -> str:
    raw = value.value if isinstance(value, OrderStatus) else str(value)
    return ORDER_STATUS_LABELS.get(raw, raw)


def _conversation_status_label(value: Any) -> str:
    return CONVERSATION_STATUS_LABELS.get(str(value), str(value))


def _channel_label(value: Any) -> str:
    return CHANNEL_LABELS.get(str(value).casefold(), str(value))


templates.env.filters["money"] = _money
templates.env.filters["order_reference"] = _order_reference
templates.env.filters["order_status_ar"] = _order_status_label
templates.env.filters["conversation_status_ar"] = _conversation_status_label
templates.env.filters["channel_ar"] = _channel_label


@dataclass(frozen=True)
class DashboardOwner:
    user: User
    store: Store


def _csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def _verify_csrf(request: Request, submitted: str) -> None:
    expected = request.session.get("csrf_token")
    if (
        not isinstance(expected, str)
        or not submitted
        or not secrets.compare_digest(expected, submitted)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing CSRF token",
        )


def _redirect_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        headers={"Location": "/dashboard/login"},
    )


def get_dashboard_owner(
    request: Request,
    db: Session = Depends(get_db),
) -> DashboardOwner:
    user_id = request.session.get("user_id")
    store_id = request.session.get("store_id")
    try:
        parsed_user_id = uuid.UUID(str(user_id))
        parsed_store_id = uuid.UUID(str(store_id))
    except (ValueError, TypeError, AttributeError):
        request.session.clear()
        raise _redirect_login()

    user = (
        db.query(User)
        .filter(User.id == parsed_user_id, User.is_active.is_(True))
        .one_or_none()
    )
    membership = (
        db.query(StoreUser)
        .filter(
            StoreUser.user_id == parsed_user_id,
            StoreUser.store_id == parsed_store_id,
            StoreUser.role == StoreRole.OWNER,
        )
        .one_or_none()
    )
    if user is None or membership is None:
        request.session.clear()
        raise _redirect_login()
    store = db.query(Store).filter(Store.id == membership.store_id).one_or_none()
    if store is None:
        request.session.clear()
        raise _redirect_login()
    return DashboardOwner(user=user, store=store)


def _render(
    request: Request,
    template: str,
    owner: DashboardOwner | None = None,
    **context: Any,
):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "owner": owner,
            "store": owner.store if owner else None,
            "csrf_token": _csrf_token(request),
            "theme": request.session.get("theme", "system"),
            **context,
        },
    )


def _owned_product(
    db: Session, store_id: uuid.UUID, product_id: uuid.UUID
) -> Product:
    try:
        return product_service.get_product(db, store_id, product_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")


def _form_decimal(value: str, field_name: str) -> Decimal:
    try:
        amount = Decimal(value.strip())
    except (InvalidOperation, AttributeError):
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}")
    if not amount.is_finite():
        raise HTTPException(status_code=422, detail=f"Invalid {field_name}")
    return amount


@router.get("")
def dashboard_home(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    store_id = owner.store.id
    orders_today = (
        db.query(func.count(Order.id))
        .filter(
            Order.store_id == store_id,
            func.date(Order.created_at) == date.today(),
        )
        .scalar()
    )
    confirmed = db.query(Order).filter(
        Order.store_id == store_id,
        Order.status == OrderStatus.CONFIRMED,
    )
    confirmed_count = confirmed.count()
    confirmed_total = (
        db.query(func.coalesce(func.sum(Order.total), 0))
        .filter(
            Order.store_id == store_id,
            Order.status == OrderStatus.CONFIRMED,
        )
        .scalar()
    )
    low_stock = (
        db.query(Product.name, ProductVariant.name, InventoryItem.quantity)
        .join(ProductVariant, ProductVariant.product_id == Product.id)
        .join(InventoryItem, InventoryItem.variant_id == ProductVariant.id)
        .filter(
            Product.store_id == store_id,
            Product.is_active.is_(True),
            InventoryItem.store_id == store_id,
            InventoryItem.quantity < 3,
        )
        .order_by(InventoryItem.quantity, Product.name)
        .limit(20)
        .all()
    )
    return _render(
        request,
        "dashboard/home.html",
        owner,
        orders_today=int(orders_today or 0),
        confirmed_count=confirmed_count,
        confirmed_total=Decimal(confirmed_total or 0),
        low_stock=low_stock,
    )


def _require_super_admin(request: Request, db: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise _redirect_login()
    try:
        parsed_user_id = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        request.session.clear()
        raise _redirect_login()

    user = (
        db.query(User)
        .filter(User.id == parsed_user_id, User.is_active.is_(True))
        .one_or_none()
    )
    if user is None or not user.is_super_admin:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return user


@router.get("/login")
def dashboard_login_page(request: Request):
    return _render(request, "dashboard/login.html", error=None)


@router.get("/super-admin")
def super_admin_dashboard(request: Request, db: Session = Depends(get_db)):
    _require_super_admin(request, db)
    return RedirectResponse("/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/login")
def dashboard_login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    email = username.strip().casefold()
    _enforce_rate_limit("dashboard_login", email)
    user = (
        db.query(User)
        .filter(func.lower(User.email) == email, User.is_active.is_(True))
        .one_or_none()
    )
    if user is None or not verify_password(password, user.hashed_password):
        return _render(
            request,
            "dashboard/login.html",
            error="اسم المستخدم أو كلمة المرور غير صحيحة.",
        )
    if user.is_super_admin:
        request.session.clear()
        request.session.update(
            {
                "user_id": str(user.id),
                "csrf_token": secrets.token_urlsafe(32),
            }
        )
        return RedirectResponse(
            "/super-admin",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    membership = (
        db.query(StoreUser)
        .join(Store, Store.id == StoreUser.store_id)
        .filter(
            StoreUser.user_id == user.id,
            StoreUser.role == StoreRole.OWNER,
            Store.is_active.is_(True),
        )
        .order_by(Store.created_at, Store.id)
        .first()
    )
    if membership is None:
        return _render(
            request,
            "dashboard/login.html",
            error="لا يوجد متجر مالك نشط مرتبط بهذا الحساب.",
        )
    request.session.clear()
    request.session.update(
        {
            "user_id": str(user.id),
            "store_id": str(membership.store_id),
            "csrf_token": secrets.token_urlsafe(32),
        }
    )
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def dashboard_logout(
    request: Request,
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
):
    del owner
    _verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/dashboard/login", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/appearance")
def save_appearance(
    request: Request,
    theme: str = Form("system"),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
):
    _verify_csrf(request, csrf_token)
    if theme not in {"system", "light", "dark"}:
        raise HTTPException(status_code=422, detail="Unknown appearance setting")
    request.session["theme"] = theme
    referer = request.headers.get("referer", "")
    return_to = (
        referer
        if referer.startswith("/dashboard") and not referer.startswith("//")
        else "/dashboard"
    )
    return RedirectResponse(return_to, status_code=303)


@router.get("/account")
def account_page(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    saved: str | None = None,
    error: str | None = None,
):
    return _render(
        request,
        "dashboard/account.html",
        owner,
        saved=saved,
        error=error,
    )


@router.post("/account/username")
def update_account_username(
    request: Request,
    username: str = Form(""),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    normalized = username.strip().casefold()
    if not normalized or len(normalized) > 255:
        return _render(
            request,
            "dashboard/account.html",
            owner,
            saved=None,
            error="اسم المستخدم مطلوب ويجب ألا يتجاوز 255 حرفاً.",
        )
    duplicate = (
        db.query(User.id)
        .filter(func.lower(User.email) == normalized, User.id != owner.user.id)
        .first()
    )
    if duplicate is not None:
        return _render(
            request,
            "dashboard/account.html",
            owner,
            saved=None,
            error="اسم المستخدم مستخدم بالفعل.",
        )
    owner.user.email = normalized
    db.commit()
    db.refresh(owner.user)
    return _render(
        request,
        "dashboard/account.html",
        owner,
        saved="تم تحديث اسم المستخدم.",
        error=None,
    )


@router.post("/account/password")
def update_account_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    confirm_password: str = Form(""),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    error = None
    if not verify_password(current_password, owner.user.hashed_password):
        error = "كلمة المرور الحالية غير صحيحة."
    elif len(new_password) < 12 or len(new_password) > 128:
        error = "يجب أن تتكون كلمة المرور الجديدة من 12 إلى 128 حرفاً."
    elif not (
        re.search(r"[a-z]", new_password)
        and re.search(r"[A-Z]", new_password)
        and re.search(r"\d", new_password)
        and re.search(r"[^A-Za-z0-9]", new_password)
    ):
        error = "استخدم حرفاً كبيراً وصغيراً ورقماً ورمزاً واحداً على الأقل."
    elif new_password != confirm_password:
        error = "كلمتا المرور الجديدتان غير متطابقتين."
    if error:
        return _render(
            request,
            "dashboard/account.html",
            owner,
            saved=None,
            error=error,
        )
    owner.user.hashed_password = hash_password(new_password)
    db.commit()
    db.refresh(owner.user)
    return _render(
        request,
        "dashboard/account.html",
        owner,
        saved="تم تحديث كلمة المرور.",
        error=None,
    )


@router.get("/products")
def products_page(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    products = (
        db.query(Product)
        .options(joinedload(Product.variants).joinedload(ProductVariant.inventory_item))
        .filter(Product.store_id == owner.store.id)
        .order_by(Product.name)
        .all()
    )
    return _render(request, "dashboard/products.html", owner, products=products)


@router.get("/products/new")
def new_product_page(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
):
    return _render(
        request, "dashboard/product_form.html", owner, product=None, error=None
    )


@router.post("/products")
def create_product(
    request: Request,
    name: str = Form(...),
    description: str = Form(""),
    base_price: str = Form(...),
    sku: str = Form(""),
    initial_quantity: int = Form(0),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    try:
        product_service.create_product(
            db,
            owner.store.id,
            name=name.strip(),
            description=description.strip() or None,
            base_price=_form_decimal(base_price, "price"),
            sku=sku.strip() or None,
            initial_quantity=initial_quantity,
        )
    except (DuplicateSKUError, ValidationError) as exc:
        return _render(
            request,
            "dashboard/product_form.html",
            owner,
            product=None,
            error=str(exc),
        )
    return RedirectResponse("/dashboard/products", status_code=303)


@router.get("/products/{product_id}")
def product_detail_page(
    request: Request,
    product_id: uuid.UUID,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    product = _owned_product(db, owner.store.id, product_id)
    db.refresh(product)
    variants = (
        db.query(ProductVariant)
        .options(joinedload(ProductVariant.inventory_item))
        .filter(ProductVariant.product_id == product.id)
        .order_by(ProductVariant.name)
        .all()
    )
    return _render(
        request,
        "dashboard/product_detail.html",
        owner,
        product=product,
        variants=variants,
        error=None,
    )


@router.post("/products/{product_id}")
def update_product(
    request: Request,
    product_id: uuid.UUID,
    name: str = Form(...),
    description: str = Form(""),
    base_price: str = Form(...),
    sku: str = Form(""),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    try:
        product_service.update_product(
            db,
            owner.store.id,
            product_id,
            name=name.strip(),
            description=description.strip() or None,
            base_price=_form_decimal(base_price, "price"),
            sku=sku.strip() or None,
            update_sku=True,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except (DuplicateSKUError, ValidationError) as exc:
        product = _owned_product(db, owner.store.id, product_id)
        variants = db.query(ProductVariant).filter(
            ProductVariant.product_id == product.id
        ).all()
        return _render(
            request,
            "dashboard/product_detail.html",
            owner,
            product=product,
            variants=variants,
            error=str(exc),
        )
    return RedirectResponse(
        f"/dashboard/products/{product_id}", status_code=303
    )


@router.post("/products/{product_id}/toggle")
def toggle_product(
    request: Request,
    product_id: uuid.UUID,
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    product = _owned_product(db, owner.store.id, product_id)
    product_service.update_product(
        db, owner.store.id, product.id, is_active=not product.is_active
    )
    return RedirectResponse("/dashboard/products", status_code=303)


@router.post("/products/{product_id}/variants")
def create_variant(
    request: Request,
    product_id: uuid.UUID,
    name: str = Form(...),
    price_adjustment: str = Form("0"),
    attributes_json: str = Form("{}"),
    sku: str = Form(""),
    initial_quantity: int = Form(0),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    try:
        try:
            attributes = json.loads(attributes_json or "{}")
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422, detail="Invalid variant attributes JSON"
            )
        if not isinstance(attributes, dict):
            raise HTTPException(
                status_code=422, detail="Variant attributes must be a JSON object"
            )
        product_service.create_variant(
            db,
            owner.store.id,
            product_id,
            name=name.strip(),
            price_adjustment=_form_decimal(price_adjustment, "price adjustment"),
            attributes=attributes,
            sku=sku.strip() or None,
            initial_quantity=initial_quantity,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Product not found")
    except (DuplicateSKUError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RedirectResponse(
        f"/dashboard/products/{product_id}", status_code=303
    )


@router.post("/products/{product_id}/variants/{variant_id}")
def update_variant(
    request: Request,
    product_id: uuid.UUID,
    variant_id: uuid.UUID,
    name: str = Form(...),
    price_adjustment: str = Form("0"),
    attributes_json: str = Form("{}"),
    sku: str = Form(""),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    try:
        try:
            attributes = json.loads(attributes_json or "{}")
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=422, detail="Invalid variant attributes JSON"
            )
        if not isinstance(attributes, dict):
            raise HTTPException(
                status_code=422, detail="Variant attributes must be a JSON object"
            )
        product_service.update_variant(
            db,
            owner.store.id,
            product_id,
            variant_id,
            name=name.strip(),
            price_adjustment=_form_decimal(price_adjustment, "price adjustment"),
            attributes=attributes,
            sku=sku.strip() or None,
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Variant not found")
    except (DuplicateSKUError, ValidationError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return RedirectResponse(
        f"/dashboard/products/{product_id}", status_code=303
    )


@router.post("/variants/{variant_id}/stock")
def update_variant_stock(
    request: Request,
    variant_id: uuid.UUID,
    quantity: int = Form(...),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    try:
        inventory_service.set_variant_stock(
            db, owner.store.id, variant_id, quantity
        )
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Variant not found")
    product_id = (
        db.query(ProductVariant.product_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .filter(
            ProductVariant.id == variant_id,
            Product.store_id == owner.store.id,
        )
        .scalar()
    )
    if product_id is None:
        raise HTTPException(status_code=404, detail="Variant not found")
    return RedirectResponse(
        f"/dashboard/products/{product_id}", status_code=303
    )


@router.get("/orders")
def orders_page(
    request: Request,
    status_filter: str | None = None,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    query = db.query(Order).options(joinedload(Order.items)).filter(
        Order.store_id == owner.store.id
    )
    if status_filter:
        try:
            query = query.filter(Order.status == OrderStatus(status_filter))
        except ValueError:
            raise HTTPException(status_code=422, detail="Unknown order status")
    orders = query.order_by(Order.created_at.desc()).limit(200).all()
    customer_ids = {order.customer_id for order in orders if order.customer_id}
    customers = (
        {
            customer.id: customer.name
            for customer in db.query(Customer)
            .filter(
                Customer.store_id == owner.store.id,
                Customer.id.in_(customer_ids),
            )
            .all()
        }
        if customer_ids
        else {}
    )
    return _render(
        request,
        "dashboard/orders.html",
        owner,
        orders=orders,
        customers=customers,
        statuses=list(OrderStatus),
        selected_status=status_filter or "",
    )


@router.get("/orders/{order_id}")
def order_detail_page(
    request: Request,
    order_id: uuid.UUID,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    order = (
        db.query(Order)
        .options(joinedload(Order.items))
        .filter(Order.id == order_id, Order.store_id == owner.store.id)
        .one_or_none()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    customer = (
        db.query(Customer)
        .filter(
            Customer.id == order.customer_id,
            Customer.store_id == owner.store.id,
        )
        .one_or_none()
        if order.customer_id
        else None
    )
    item_details = []
    for item in order.items:
        product = (
            db.query(Product)
            .filter(
                Product.id == item.product_id,
                Product.store_id == owner.store.id,
            )
            .one_or_none()
            if item.product_id
            else None
        )
        variant = (
            db.query(ProductVariant)
            .filter(
                ProductVariant.id == item.variant_id,
                ProductVariant.product_id == product.id,
            )
            .one_or_none()
            if product is not None and item.variant_id
            else None
        )
        item_details.append((item, product, variant))
    return _render(
        request,
        "dashboard/order_detail.html",
        owner,
        order=order,
        customer=customer,
        item_details=item_details,
    )


@router.get("/settings")
def store_settings_page(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
):
    return _render(request, "dashboard/settings.html", owner, saved=False)


@router.post("/settings")
def save_store_settings(
    request: Request,
    name: str = Form(...),
    address: str = Form(""),
    delivery_policy_text: str = Form(""),
    served_wilayas: str = Form(""),
    csrf_token: str = Form(""),
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    _verify_csrf(request, csrf_token)
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=422, detail="Store name cannot be empty")
    owner.store.name = clean_name
    owner.store.address = address.strip() or None
    owner.store.delivery_policy_text = delivery_policy_text.strip() or None
    owner.store.served_wilayas = served_wilayas.strip() or None
    db.commit()
    db.refresh(owner.store)
    return _render(request, "dashboard/settings.html", owner, saved=True)


@router.get("/conversations")
def conversations_page(
    request: Request,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    conversations = (
        db.query(Conversation, Customer)
        .join(Customer, Customer.id == Conversation.customer_id)
        .filter(Conversation.store_id == owner.store.id)
        .order_by(Conversation.updated_at.desc())
        .limit(30)
        .all()
    )
    return _render(
        request,
        "dashboard/conversations.html",
        owner,
        conversations=conversations,
        selected=None,
        messages=[],
    )


@router.get("/conversations/{conversation_id}")
def conversation_detail_page(
    request: Request,
    conversation_id: uuid.UUID,
    owner: DashboardOwner = Depends(get_dashboard_owner),
    db: Session = Depends(get_db),
):
    row = (
        db.query(Conversation, Customer)
        .join(Customer, Customer.id == Conversation.customer_id)
        .filter(
            Conversation.id == conversation_id,
            Conversation.store_id == owner.store.id,
            Customer.store_id == owner.store.id,
        )
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(100)
        .all()
    )
    return _render(
        request,
        "dashboard/conversations.html",
        owner,
        conversations=[],
        selected=row,
        messages=list(reversed(messages)),
    )
