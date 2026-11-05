# دليل نشر DzCommerce

## المتطلبات الأساسية

- Python 3.12 أو أحدث لتشغيل أدوات التطوير والاختبارات.
- Node.js 18 أو أحدث وnpm لتشغيل الواجهة الأمامية وبنائها.
- PostgreSQL 14 أو أحدث.
- Docker اختياري للنشر داخل حاوية.
- عند استخدام مزود Qwen، يلزم حساب ومفتاح لدى مزود واجهة OpenAI-compatible المحدد في `QWEN_BASE_URL` (الافتراضي الحالي DashScope).
- يلزم حساب Meta Developer وإمكانية إدارة صفحة Facebook عند تفعيل Messenger.

## متغيرات البيئة

أنشئ ملف `.env` محليًا، وضع القيم السرية فيه فقط. لا تضع أسرارًا في المستودع أو صورة Docker.

| المتغير | مطلوب؟ | الافتراضي في التطبيق | الوصف |
| --- | --- | --- | --- |
| `ENV` | مطلوب للإنتاج | `development` | بيئة التشغيل؛ استخدم `production` في الإنتاج. |
| `DATABASE_URL` | مطلوب | قيمة تطوير محددة في إعدادات التطبيق | رابط اتصال PostgreSQL. عيّن قيمة الإنتاج وفق بنية قاعدة البيانات لديك. |
| `JWT_SECRET_KEY` | مطلوب للإنتاج | قيمة تطوير غير آمنة | مفتاح توقيع JWT. يجب أن يكون قويًا وبطول 32 محرفًا على الأقل في الإنتاج. |
| `SECRET_KEY` | اختياري، بديل | — | اسم بديل لـ`JWT_SECRET_KEY`؛ استخدم الاسم الأساسي في الإعدادات الجديدة. |
| `JWT_ALGORITHM` | اختياري | `HS256` | خوارزمية توقيع JWT. |
| `ALGORITHM` | اختياري، بديل | — | اسم بديل لـ`JWT_ALGORITHM`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | اختياري | `60` | مدة صلاحية رمز الوصول بالدقائق. |
| `AGENT_PROVIDER` | اختياري | `mock` | مزود الوكيل؛ القيمة `qwen` لتفعيل Qwen، وإلا يستخدم التطبيق المزود التجريبي. |
| `QWEN_API_KEY` | مطلوب عند `AGENT_PROVIDER=qwen` | فارغ | مفتاح API لمزود Qwen المختار. |
| `QWEN_MODEL` | اختياري | `qwen-max` | اسم النموذج لدى المزود. |
| `QWEN_BASE_URL` | اختياري | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | عنوان واجهة OpenAI-compatible. |
| `QWEN_TIMEOUT` | اختياري | `60` ثانية | مهلة طلبات المزود. |
| `QWEN_RECENT_MESSAGES_LIMIT` | اختياري | `10` | الحد الأقصى للرسائل الحديثة في السياق. |
| `QWEN_MAX_CONTEXT_TOKENS` | اختياري | `32000` | الحد الأقصى لرموز السياق. |
| `META_APP_ID` | مطلوب لربط صفحة Facebook | فارغ | معرّف تطبيق Meta المستخدم للتحقق من Page Access Token. |
| `META_APP_SECRET` | مطلوب لربط الصفحة وWebhook | فارغ | سر التطبيق المستخدم للتحقق من الرمز وتوقيع Webhook. |
| `SOCIAL_TOKEN_ENCRYPTION_KEY` | مطلوب لتخزين توكنات Meta | فارغ | مفتاح Fernet ثابت لتشفير وفك تشفير اعتمادات المتاجر. |
| `META_VERIFY_TOKEN` | مطلوب عند إعداد تحقق Meta Webhook | فارغ | رمز التحقق الذي يجب أن يطابق القيمة المسجلة في إعداد Meta Webhook. |
| `FACEBOOK_VERIFY_TOKEN` | اختياري، بديل | — | اسم بديل لـ`META_VERIFY_TOKEN`. |
| `WHATSAPP_ACCESS_TOKEN` | مخطط — غير نشط | فارغ | متغير تكامل WhatsApp؛ مسار الرسائل الواردة غير مفعّل. |
| `WHATSAPP_PHONE_NUMBER_ID` | مخطط — غير نشط | فارغ | معرّف رقم WhatsApp؛ مسار الرسائل الواردة غير مفعّل. |
| `WHATSAPP_VERIFY_TOKEN` | مخطط — غير نشط | فارغ | رمز تحقق WhatsApp؛ لا يعني وجود متغير التفعيل استقبال الرسائل. |

تُقبل أسماء البدائل للتوافق مع الإعدادات السابقة؛ يوصى باستخدام أسماء `META_*` و`JWT_*` الأساسية. متغيرات WhatsApp موثقة لأغراض الإعداد المستقبلي فقط، وWhatsApp inbound غير نشط.

## إعداد قاعدة البيانات

أنشئ قاعدة بيانات ومستخدمًا مخصصًا للتطبيق في PostgreSQL، ثم عيّن `DATABASE_URL` في `.env`. مثال إنشاء قاعدة ومستخدم من طرف مسؤول PostgreSQL:

```sql
CREATE USER dzcommerce_app WITH PASSWORD '<choose-a-strong-password>';
CREATE DATABASE dzcommerce OWNER dzcommerce_app;
```

فعّل البيئة الافتراضية وثبّت الاعتماديات ثم طبّق أحدث المخططات:

```powershell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
alembic upgrade head
alembic current
```

تحقق من أن `alembic current` يعرض أحدث revision مطبق.

## تشغيل الـ Backend

محليًا من جذر المشروع:

```powershell
uvicorn app.main:app --reload --port 8000
```

لبناء صورة Docker وتشغيلها:

```powershell
docker build -t dzcommerce-backend .
docker run --name dzcommerce-backend --env-file .env -p 8000:8000 dzcommerce-backend
```

تأكد من أن `DATABASE_URL` داخل الحاوية يشير إلى عنوان PostgreSQL الذي يمكن للحاوية الوصول إليه. ملف `.dockerignore` يستبعد `.env` من build context؛ مرّر إعدادات التشغيل عبر آلية أسرار مناسبة أو `--env-file` على المضيف، ولا تضعها في الصورة.

## تشغيل الـ Frontend

من مجلد الواجهة:

```powershell
cd frontend
npm install
npm run dev
npm run build
```

اضبط `VITE_API_BASE_URL` في `frontend/.env` على عنوان Backend، مثل عنوان التطوير المحلي الموثق في `frontend/.env.example`. لا تضع أسرار الخادم في متغيرات Vite؛ القيم المسبوقة بـ`VITE_` متاحة ضمن تطبيق المتصفح.

## إعداد Meta Webhook

راجع [META_SETUP.md](./META_SETUP.md) لخطوات إنشاء تطبيق Meta وربط صفحة Facebook بالمتجر. يتطلب ربط الصفحة `META_APP_ID` و`META_APP_SECRET` و`SOCIAL_TOKEN_ENCRYPTION_KEY`، ويتطلب إعداد Webhook عنوان HTTPS و`META_VERIFY_TOKEN`. لا يعتمد الإرسال على توكن Meta عام.

## قائمة التحقق الإنتاجية

- [ ] `ENV=production`.
- [ ] `JWT_SECRET_KEY` قوي، لا يقل عن 32 محرفًا، وليس القيمة الافتراضية.
- [ ] `DATABASE_URL` يشير إلى PostgreSQL الإنتاجي بحساب محدود الصلاحيات.
- [ ] إعداد `AGENT_PROVIDER` و`QWEN_API_KEY` صالح عند تفعيل مزود Qwen.
- [ ] `META_APP_ID` و`META_APP_SECRET` و`SOCIAL_TOKEN_ENCRYPTION_KEY` مضبوطون قبل ربط صفحة Facebook.
- [ ] `META_APP_SECRET` و`META_VERIFY_TOKEN` مضبوطتان عند تفعيل Meta Webhook.
- [ ] نقطة Webhook متاحة عبر HTTPS.
- [ ] `.env` غير موجود في صورة Docker؛ قواعد `.dockerignore` مطبقة.
- [ ] النسخ الاحتياطي لقاعدة البيانات ومراقبة الاستعادة مفعّلان.
- [ ] جدول `ai_usage_events` موجود بعد تطبيق migrations.
- [ ] مجموعة الاختبارات كاملة بنجاح قبل النشر.
- [ ] لا تُعامل متغيرات WhatsApp على أنها قناة رسائل واردة مفعلة.
