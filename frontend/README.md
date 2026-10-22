# DzCommerce Dashboard

لوحة تحكم DzCommerce مبنية باستخدام React 18 وVite وTypeScript وTailwind CSS ومكونات shadcn/ui.

## المتطلبات

- Node.js 18 أو أحدث.
- npm.

## التطوير المحلي

من مجلد `frontend`:

```powershell
npm install
npm run dev
```

## إعداد عنوان API

أنشئ ملف `.env` داخل مجلد `frontend` واضبط عنوان Backend:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

كل متغير يبدأ بـ`VITE_` يُضمّن في تطبيق المتصفح؛ لا تضع مفاتيح سرية أو بيانات اعتماد الخادم فيه.

## بناء الإنتاج

```powershell
npm run build
```

## أداة البناء

يعتمد خادم التطوير وبناء الإنتاج على Vite.
