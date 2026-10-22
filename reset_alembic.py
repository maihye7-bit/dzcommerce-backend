import psycopg2
from app.core.config import settings # أو استخدم os.getenv مباشرة

# بيانات الاتصال من ملف .env الخاص بك
DB_URL = "postgresql+psycopg2://dzcommerce:dzcommerce_dev_password@localhost:5432/dzcommerce"

try:
    # الاتصال بقاعدة البيانات
    conn = psycopg2.connect(DB_URL.replace("postgresql+psycopg2://", "postgresql://"))
    cur = conn.cursor()
    
    # حذف جدول التتبع
    cur.execute("DROP TABLE IF EXISTS alembic_version;")
    conn.commit()
    
    print("✅ تم حذف جدول alembic_version بنجاح!")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"❌ خطأ أثناء الاتصال: {e}")
    print("تأكد من تشغيل خادم PostgreSQL وأن بيانات الاتصال في الكود صحيحة.")
