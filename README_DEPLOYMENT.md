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

### 4. إعداد تخزين صور المنتجات
- أضف **Volume** إلى خدمة التطبيق، واضبط Mount Path على `/data`.
- يحدد Railway المتغير `RAILWAY_VOLUME_MOUNT_PATH` تلقائيًا؛ سيحفظ التطبيق الصور في `product-images` داخل هذا الـ Volume.
- يتوقف التطبيق عند بدء التشغيل على Railway إذا لم يجد Volume دائمًا، حتى لا يقبل صورًا ستُفقد عند إعادة النشر.
- لا يحتاج التخزين المحلي إلى خدمة صور خارجية مدفوعة. استخدم نسخة تشغيل واحدة عند الاعتماد على Volume محلي؛ التخزين المحلي غير مشترك بين النسخ المتعددة. عند الحاجة إلى التوسع الأفقي، انقل التخزين إلى خدمة كائنات مشتركة متوافقة مع S3.

### 5. إضافة المتغيرات
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
- PRODUCT_IMAGE_STORAGE_DIR اختياري؛ إن ضُبط على Railway فيجب أن يكون داخل مسار الـ Volume

⚠️ لا تضف DATABASE_URL يدوياً (Railway يضيفه).

### 6. تشغيل الترحيلات
افتح تبويب Shell لخدمة التطبيق ونفّذ:
```bash
alembic upgrade head
```
لا يشغّل التطبيق الترحيلات تلقائيًا. راجع الإصدار الحالي في قاعدة البيانات ومخرجات الترحيل قبل تشغيله على الإنتاج.

### 7. إنشاء المالك
```bash
python scripts/create_owner.py --store-slug dzcommerce --username admin --password "كلمة_سر_قوية"
```

### 8. الحصول على الرابط
Settings → Production Domain → انسخ الرابط (مثال: dzcommerce-backend-production.up.railway.app)

### 9. تحديث Meta Webhook
في developers.facebook.com → تطبيقك → Messenger → Webhooks:
- Callback URL: https://رابطك.up.railway.app/webhooks/meta
- Verify Token: نفس قيمة META_VERIFY_TOKEN
- اضغط Vérifier et enregistrer
- فعّل: messages, messaging_postbacks, feed

### 10. اختبار البوت
افتح Messenger وأرسل رسالة لصفحتك.

### 11. النشر الرسمي
App Review → طلب الصلاحيات → الموافقة → Publier (Live Mode).

## استكشاف الأخطاء
- خطأ 502: التطبيق لم يبدأ، راجع Logs في Railway
- خطأ DATABASE_URL: تأكد أن PostgreSQL مضافة
- Webhook لا يتحقق: تأكد أن الرابط صحيح و META_VERIFY_TOKEN مطابق
