from __future__ import annotations

import secrets
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dashboard_ui import _csrf_token, _money, _order_reference, _verify_csrf
from app.core.security import hash_password
from app.database import get_db
from app.models.conversation import Conversation
from app.models.order import Order, OrderStatus
from app.models.product import Product
from app.models.store import Store
from app.models.store_user import StoreRole, StoreUser
from app.models.user import User

router = APIRouter(prefix="/super-admin", tags=["super-admin"])
templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parents[2] / "templates")
)
templates.env.filters["money"] = _money
templates.env.filters["order_reference"] = _order_reference

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


def _require_super_admin(request: Request, db: Session) -> User:
    raw_user_id = request.session.get("user_id")
    try:
        user_id = uuid.UUID(str(raw_user_id))
    except (ValueError, TypeError, AttributeError):
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/dashboard/login"},
        )
    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_active.is_(True))
        .one_or_none()
    )
    if user is None or not user.is_super_admin:
        request.session.clear()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin access required",
        )
    return user


def _render(
    request: Request,
    template: str,
    user: User,
    **context: Any,
):
    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "super_admin_user": user,
            "csrf_token": _csrf_token(request),
            "theme": request.session.get("theme", "system"),
            **context,
        },
    )


def _redirect_with_notice(message: str, kind: str = "success") -> RedirectResponse:
    from urllib.parse import urlencode

    return RedirectResponse(
        f"/super-admin?{urlencode({'notice': message, 'notice_type': kind})}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("")
def super_admin_home(
    request: Request,
    q: str = "",
    state: str = "all",
    notice: str | None = None,
    notice_type: str = "success",
    db: Session = Depends(get_db),
):
    user = _require_super_admin(request, db)
    state = state if state in {"all", "active", "suspended"} else "all"
    query = db.query(Store)
    clean_query = q.strip()
    if clean_query:
        pattern = f"%{clean_query}%"
        query = query.filter(or_(Store.name.ilike(pattern), Store.slug.ilike(pattern)))
    if state == "active":
        query = query.filter(Store.is_active.is_(True))
    elif state == "suspended":
        query = query.filter(Store.is_active.is_(False))

    stores = query.order_by(Store.created_at.desc(), Store.name).all()
    total_count = db.query(func.count(Store.id)).scalar()
    active_count = (
        db.query(func.count(Store.id))
        .filter(Store.is_active.is_(True))
        .scalar()
    )
    # Aggregate counts are deliberately independent of the current search/filter.
    suspended_count = int(total_count or 0) - int(active_count or 0)
    return _render(
        request,
        "dashboard/super_admin.html",
        user,
        stores=stores,
        query=clean_query,
        state=state,
        total_count=int(total_count or 0),
        active_count=int(active_count or 0),
        suspended_count=suspended_count,
        notice=notice,
        notice_type=notice_type if notice_type in {"success", "error", "warning"} else "success",
    )


@router.get("/stores/new")
def new_store_page(request: Request, db: Session = Depends(get_db)):
    user = _require_super_admin(request, db)
    return _render(
        request,
        "dashboard/super_admin_store_form.html",
        user,
        error=None,
        form_data={},
    )


@router.post("/stores/new")
def create_store(
    request: Request,
    name: str = Form(""),
    slug: str = Form(""),
    owner_name: str = Form(""),
    password: str = Form(""),
    email: str = Form(""),
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _require_super_admin(request, db)
    _verify_csrf(request, csrf_token)

    name = name.strip()
    slug = slug.strip().strip("-").lower()
    owner_name = owner_name.strip()
    email = email.strip().casefold()
    form_data = {
        "name": name,
        "slug": slug,
        "owner_name": owner_name,
        "email": email,
    }
    error = None
    if not name or len(name) > 255:
        error = "اسم المتجر مطلوب ويجب ألا يتجاوز 255 حرفاً."
    elif not slug or len(slug) > 255:
        error = "معرّف المتجر مطلوب ويجب ألا يتجاوز 255 حرفاً."
    elif re.fullmatch(r"[\w-]+", slug, flags=re.UNICODE) is None:
        error = "استخدم الأحرف والأرقام والشرطة فقط في معرّف المتجر."
    elif not owner_name or len(owner_name) > 255:
        error = "اسم المالك مطلوب."
    elif len(password) < 12 or len(password) > 128:
        error = "كلمة المرور يجب أن تتكون من 12 إلى 128 حرفاً."
    elif not (
        re.search(r"[a-z]", password)
        and re.search(r"[A-Z]", password)
        and re.search(r"\d", password)
        and re.search(r"[^A-Za-z0-9]", password)
    ):
        error = "يجب أن تحتوي كلمة المرور على حرف كبير وصغير ورقم ورمز."
    elif email and ("@" not in email or len(email) > 255):
        error = "البريد الإلكتروني غير صالح."
    elif db.query(Store.id).filter(Store.slug == slug).first():
        error = "معرّف المتجر مستخدم بالفعل."
    elif email and db.query(User.id).filter(func.lower(User.email) == email).first():
        error = "البريد الإلكتروني مستخدم بالفعل."

    if error:
        return _render(
            request,
            "dashboard/super_admin_store_form.html",
            user,
            error=error,
            form_data=form_data,
        )

    login_email = email or f"owner-{uuid.uuid4().hex[:16]}@local.invalid"
    store = Store(name=name, slug=slug, is_active=True)
    owner = User(
        email=login_email,
        hashed_password=hash_password(password),
        full_name=owner_name,
        is_active=True,
        is_superuser=False,
        is_super_admin=False,
    )
    db.add_all([store, owner])
    try:
        db.flush()
        db.add(
            StoreUser(
                store_id=store.id,
                user_id=owner.id,
                role=StoreRole.OWNER,
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render(
            request,
            "dashboard/super_admin_store_form.html",
            user,
            error="تعذر إنشاء المتجر: المعرّف أو البريد الإلكتروني مستخدم بالفعل.",
            form_data=form_data,
        )
    return _redirect_with_notice(
        f"تم إنشاء المتجر بنجاح. اسم دخول المالك: {login_email}"
    )


@router.get("/stores/{slug}")
def store_detail(
    slug: str,
    request: Request,
    db: Session = Depends(get_db),
):
    user = _require_super_admin(request, db)
    store = db.query(Store).filter(Store.slug == slug).one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")

    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    product_count = (
        db.query(func.count(Product.id))
        .filter(Product.store_id == store.id)
        .scalar()
    )
    order_count_30d = (
        db.query(func.count(Order.id))
        .filter(Order.store_id == store.id, Order.created_at >= cutoff)
        .scalar()
    )
    revenue_30d = (
        db.query(func.coalesce(func.sum(Order.total), 0))
        .filter(
            Order.store_id == store.id,
            Order.status == OrderStatus.CONFIRMED,
            Order.created_at >= cutoff,
        )
        .scalar()
    )
    recent_orders = (
        db.query(Order)
        .filter(Order.store_id == store.id)
        .order_by(Order.created_at.desc())
        .limit(10)
        .all()
    )
    recent_conversations = (
        db.query(Conversation)
        .filter(Conversation.store_id == store.id)
        .order_by(Conversation.updated_at.desc())
        .limit(5)
        .all()
    )
    return _render(
        request,
        "dashboard/super_admin_store_detail.html",
        user,
        store=store,
        product_count=int(product_count or 0),
        order_count_30d=int(order_count_30d or 0),
        revenue_30d=revenue_30d or 0,
        recent_orders=recent_orders,
        recent_conversations=recent_conversations,
        order_status_labels=ORDER_STATUS_LABELS,
        conversation_status_labels={
            "active": "نشطة",
            "closed": "مغلقة",
            "handoff": "محوّلة لموظف",
        },
        channel_labels={
            "facebook": "فيسبوك",
            "instagram": "إنستغرام",
            "whatsapp": "واتساب",
            "messenger": "ماسنجر",
            "api": "واجهة برمجية",
            "test": "اختبار",
        },
        notice=request.query_params.get("notice"),
        notice_type=(
            request.query_params.get("notice_type", "success")
            if request.query_params.get("notice_type")
            in {"success", "error", "warning"}
            else "success"
        ),
    )


@router.post("/stores/{store_id}/toggle")
def toggle_store(
    store_id: uuid.UUID,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    _require_super_admin(request, db)
    _verify_csrf(request, csrf_token)
    store = db.query(Store).filter(Store.id == store_id).one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    store.is_active = not store.is_active
    db.commit()
    return _redirect_with_notice(
        "تم تفعيل المتجر" if store.is_active else "تم تعليق المتجر"
    )


@router.post("/stores/{store_id}/delete")
def delete_store(
    store_id: uuid.UUID,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    _require_super_admin(request, db)
    _verify_csrf(request, csrf_token)
    store = db.query(Store).filter(Store.id == store_id).one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    db.delete(store)
    db.commit()
    return _redirect_with_notice("تم حذف المتجر")


@router.post("/stores/{store_id}/impersonate")
def impersonate_store_owner(
    store_id: uuid.UUID,
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = _require_super_admin(request, db)
    _verify_csrf(request, csrf_token)
    store = db.query(Store).filter(Store.id == store_id).one_or_none()
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if not store.is_active:
        raise HTTPException(status_code=409, detail="Cannot enter a suspended store")
    owner_link = (
        db.query(StoreUser)
        .join(User, User.id == StoreUser.user_id)
        .filter(
            StoreUser.store_id == store.id,
            StoreUser.role == StoreRole.OWNER,
            User.is_active.is_(True),
        )
        .order_by(StoreUser.created_at)
        .first()
    )
    if owner_link is None:
        raise HTTPException(status_code=409, detail="Store has no active owner")

    request.session.clear()
    request.session.update(
        {
            "user_id": str(owner_link.user_id),
            "store_id": str(store.id),
            "super_admin_user_id": str(admin.id),
            "impersonating_super_admin": True,
            "csrf_token": secrets.token_urlsafe(32),
        }
    )
    return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/stop-impersonation")
def stop_impersonation(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    if not request.session.get("impersonating_super_admin"):
        raise HTTPException(status_code=403, detail="No impersonation session")
    _verify_csrf(request, csrf_token)
    try:
        admin_id = uuid.UUID(str(request.session.get("super_admin_user_id")))
    except (ValueError, TypeError, AttributeError):
        request.session.clear()
        raise HTTPException(status_code=403, detail="Invalid admin session")
    admin = (
        db.query(User)
        .filter(
            User.id == admin_id,
            User.is_active.is_(True),
            User.is_super_admin.is_(True),
        )
        .one_or_none()
    )
    if admin is None:
        request.session.clear()
        raise HTTPException(status_code=403, detail="Super admin access required")
    request.session.clear()
    request.session.update(
        {
            "user_id": str(admin.id),
            "csrf_token": secrets.token_urlsafe(32),
        }
    )
    return RedirectResponse("/super-admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/logout")
def super_admin_logout(
    request: Request,
    csrf_token: str = Form(""),
    db: Session = Depends(get_db),
):
    _require_super_admin(request, db)
    _verify_csrf(request, csrf_token)
    request.session.clear()
    return RedirectResponse("/dashboard/login", status_code=status.HTTP_303_SEE_OTHER)
