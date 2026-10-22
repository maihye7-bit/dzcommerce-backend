# 📐 الوثيقة المعمارية: نظام التجارة الذكية (DzCommerce Phase 13 & 14)

## 1. الملخص التنفيذي
تم تطوير المرحلة 13 والانتقال إلى هيكلية المرحلة 14 لضمان استقرار تدفق الطلبات ومنع هلوسة الذكاء الاصطناعي.
الفلسفة الأساسية هي **"Qwen يفهم، Backend يقرر، Database تثبت"**.

*   **Qwen (LLM):** مسؤول فقط عن استخراج النية والكيانات من نص العميل (NLU). لا يختار الأدوات مباشرة ولا يخترع معرفات (UUIDs).
*   **CommerceResolver:** طبقة منطق نقية (Pure Logic Layer) تقرأ حالة المحادثة من قاعدة البيانات وتحدد الإجراء المسموح به بدقة (State Machine).
*   **Tools & Services:** تنفذ الإجراءات المصادق عليها بواسطة الـ Resolver باستخدام بيانات موثوقة من قاعدة البيانات.
*   **Database (PostgreSQL):** مصدر الحقيقة الوحيد للمنتجات، المخزون، والأسعار.

---

## 2. التدفق العام للبيانات (Data Flow)

```mermaid
sequenceDiagram
    participant C as Client (WhatsApp/Web)
    participant W as Webhook Handler
    participant E as ConversationEngine
    participant Q as Qwen NLU Provider
    participant R as CommerceResolver
    participant DB as PostgreSQL
    participant T as Tool Registry / Services

    C->>W: Message ("عندكم Nike؟")
    W->>E: process_message(db, store_id, msg)
    
    Note over E,R: Step 1: Load State from DB
    E->>DB: SELECT conversation metadata/draft
    DB-->>E: Current State (JSON)

    Note over E,Q: Step 2: Language Understanding (No Tools Yet)
    E->>Q: Extract Intent (JSON Only)
    Q-->>E: {intent: "product_search", mention: "Nike"}

    Note over E,R: Step 3: Business Decision Gate
    E->>R: resolve(nlu_output, current_state, store_id)
    R->>DB: Validate Product Existence & Attributes
    DB-->>R: Real UUIDs & Prices
    R-->>E: ResolutionResult(action="EXECUTE_TOOL:search_products")

    Note over E,T: Step 4: Safe Execution
    E->>T: Execute Search Products Tool
    T->>DB: Query Products by Name/Store
    DB-->>T: List of Matches
    T->>DB: Update metadata_json (selected_product_id)
    T-->>E: ToolResult (Success + Data)

    Note over E,C: Step 5: Response Generation
    E->>C: Natural Language Reply (Darija/French)