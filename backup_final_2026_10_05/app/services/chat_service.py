import os

import httpx

from app.core.config import \
    settings  # أو استخدم os.getenv مباشرة إذا كان config معقداً


async def generate_ai_response(
    user_message: str, conversation_history: list = None
) -> str:
    """
    Sends the user message to Qwen via OpenRouter and gets a response.
    """
    api_key = os.getenv("QWEN_API_KEY")
    base_url = os.getenv("QWEN_BASE_URL", "https://openrouter.ai/api/v1")
    model = os.getenv("QWEN_MODEL", "qwen/qwen-2.5-72b-instruct")

    if not api_key:
        return "⚠️ خطأ: مفتاح API للذكاء الاصطناعي غير موجود في ملف .env."

    # بناء سياق المحادثة (System Prompt + History + New Message)
    messages = [
        {
            "role": "system",
            "content": "أنت موظف مبيعات ذكي لمتجر إلكتروني جزائري. أجيب بأسلوب ودود ومختصر باللغة العربية الدارجة أو الفصحى المبسطة حسب لغة العميل. ركز على بيع المنتجات والإجابة عن الاستفسارات.",
        }
    ]

    # إضافة التاريخ السابق إذا وجد
    if conversation_history:
        messages.extend(conversation_history)

    # إضافة الرسالة الحالية
    messages.append({"role": "user", "content": user_message})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",  # مطلوب من OpenRouter أحياناً
        "X-Title": "DzCommerce Agent",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            )
            response.raise_for_status()
            data = response.json()

            # استخراج نص الرد من الهيكل المتوقع
            reply_text = data["choices"][0]["message"]["content"]
            return reply_text.strip()

    except Exception as e:
        print(f"❌ AI Error: {str(e)}")
        return "عذراً، واجهت مشكلة تقنية في الاتصال بالخادم. يرجى المحاولة لاحقاً."
