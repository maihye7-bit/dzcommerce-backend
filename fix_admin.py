import os
from app.database import SessionLocal
from app.models.user import User
from app.core.security import hash_password

db = SessionLocal()
email = "admin@dzcommerce.com"
password = "123456"
full_name = "Super Admin"  # <-- هذا هو السطر الذي كان ينقصنا

# البحث عن المستخدم
user = db.query(User).filter(User.email == email).first()

if user:
    # تحديث المستخدم الموجود
    user.hashed_password = hash_password(password)
    user.is_super_admin = True
    user.is_active = True
    user.full_name = full_name
    print("✅ تم تحديث حساب موجود بنجاح.")
else:
    # إنشاء مستخدم جديد إذا لم يكن موجوداً
    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,  # <-- تمرير الاسم الكامل
        is_active=True,
        is_super_admin=True
    )
    db.add(user)
    print("✅ تم إنشاء حساب جديد بنجاح.")

db.commit()
print("🎉 نجاح كامل! بيانات الدخول:")
print(f"البريد الإلكتروني: {email}")
print(f"كلمة المرور: {password}")
db.close()
