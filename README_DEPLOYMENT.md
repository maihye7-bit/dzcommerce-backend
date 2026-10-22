# نشر DzCommerce على Railway

## المتطلبات
- حساب GitHub
- حساب Railway (railway.app)
- ملف .env محلي يحتوي كل المتغيرات

## الخطوات

### 1. رفع الكود على GitHub
```bash
cd C:\Users\Win10LTSC\Documents\backend
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/USERNAME/dzcommerce-backend.git
git push -u origin main
```

### 2. إنشاء مشروع Railway
- ادخل railway.app وسجّل بـ GitHub
- New Project → Deploy from GitHub repo
- اختر مستودع dzcommerce-backend

### 3. إضافة PostgreSQL
- داخل المشروع: New → Database → Add PostgreSQL
- Railway سيضيف DATABASE_URL تلقائياً في Variables

### 4. إضافة المتغيرات
في تبويب Variables لخدمة التطبيق، أضف من .env المحلي:
- OPENROUTER_API_KEY
- QWEN_MODEL
- QWEN_API_KEY
- META_PAGE_ACCESS_TOKEN
- META_APP_SECRET
- META_VERIFY_TOKEN
- APP_SECRET
- SESSION_SECRET
- SOCIAL_TOKEN_ENCRYPTION_KEY
- ENVIRONMENT=production
- ALLOWED_HOSTS=.railway.app

⚠️ لا تضف DATABASE_URL يدوياً (Railway يضيفه).

### 5. تشغيل الترحيلات
افتح تبويب Shell لخدمة التطبيق ونفّذ:
```bash
alembic upgrade head
```

### 6. إنشاء المالك
```bash
python scripts/create_owner.py --store-slug dzcommerce --username admin --password "كلمة_سر_قوية"
```

### 7. الحصول على الرابط
Settings → Production Domain → انسخ الرابط (مثال: dzcommerce-backend-production.up.railway.app)

### 8. تحديث Meta Webhook
في developers.facebook.com → تطبيقك → Messenger → Webhooks:
- Callback URL: https://رابطك.up.railway.app/webhooks/meta
- Verify Token: نفس قيمة META_VERIFY_TOKEN
- اضغط Vérifier et enregistrer
- فعّل: messages, messaging_postbacks, feed

### 9. اختبار البوت
افتح Messenger وأرسل رسالة لصفحتك.

### 10. النشر الرسمي
App Review → طلب الصلاحيات → الموافقة → Publier (Live Mode).

## استكشاف الأخطاء
- خطأ 502: التطبيق لم يبدأ، راجع Logs في Railway
- خطأ DATABASE_URL: تأكد أن PostgreSQL مضافة
- Webhook لا يتحقق: تأكد أن الرابط صحيح و META_VERIFY_TOKEN مطابق
