import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.database import SessionLocal
from app.models.product import ProductVariant
from sqlalchemy import inspect

def check_attributes_column():
    db = SessionLocal()
    try:
        mapper = inspect(ProductVariant)
        columns = [c.key for c in mapper.columns]
        print("="*60)
        print("📊 ProductVariant Columns:", columns)
        print("="*60)
        
        if 'attributes_json' in columns:
            print("✅ النتيجة: عمود 'attributes_json' موجود بالفعل في النموذج!")
            print("➡️  لا حاجة لإضافة عمود جديد.")
        else:
            print("❌ النتيجة: عمود 'attributes_json' غير موجود في النموذج.")
            print("➡️  يجب إضافته قبل المتابعة.")
    except Exception as e:
        print(f"❌ خطأ أثناء الفحص: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    check_attributes_column()
