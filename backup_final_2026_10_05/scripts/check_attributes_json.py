--- scripts/check_attributes_json.py (原始)


+++ scripts/check_attributes_json.py (修改后)
"""
خطوة التحقق (Step 1) — هل يوجد attributes_json في ProductVariant؟

الاستخدام (من جذر مجلد backend على جهازك):
    python scripts/check_attributes_json.py

أو بدون قاعدة بيانات إطلاقاً (التحقق من الموديل فقط):
    python scripts/check_attributes_json.py --model-only
"""
import sys

# ---------- 1) التحقق من تعريف الموديل (لا يحتاج اتصال DB) ----------
try:
    from app.models.product import ProductVariant
    from sqlalchemy import inspect as sa_inspect
except ImportError as e:
    print("IMPORT ERROR:", e)
    print("تأكد أنك تشغّل السكربت من جذر مجلد backend حيث يوجد مجلد app/")
    sys.exit(1)

mapper = sa_inspect(ProductVariant)
cols = [c.key for c in mapper.columns]
print("Model class module :", ProductVariant.__module__)
print("Mapped columns     :", cols)
has_attr = "attributes_json" in cols
print("Has attributes_json (MODEL)?", has_attr)

if "--model-only" in sys.argv:
    sys.exit(0)

# ---------- 2) التحقق من قاعدة البيانات الفعلية (يتطلب DATABASE_URL صالح) ----------
try:
    from app.database import SessionLocal
    from sqlalchemy import text
    db = SessionLocal()
    try:
        # اسم الجدول كما في المشروع: product_variants
        res = db.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'product_variants' ORDER BY ordinal_position;"
        ))
        rows = res.fetchall()
        db_cols = [r[0] for r in rows]
        print("\nDB table 'product_variants' columns:", db_cols)
        print("Has attributes_json (DATABASE)?", "attributes_json" in db_cols)
        if rows:
            for name, dtype in rows:
                print(f"  - {name}: {dtype}")
    finally:
        db.close()
except Exception as e:
    print("\nDB CHECK FAILED (لا مشكلة، نتيجة الموديل أعلاه كافية للقرار):", type(e).__name__, str(e)[:200])

print("\n=== الخلاصة ===")
print("MODEL_HAS_ATTRIBUTES_JSON =", has_attr)

