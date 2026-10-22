"use client"

import { useState } from "react"

export default function TestWebhookPage() {
  const [message, setMessage] = useState("مرحبا، هل تتوفر سماعات رأس لاسلكية؟")
  const [response, setResponse] = useState("")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const sendMessage = async () => {
    setLoading(true)
    setError("")
    setResponse("")

    // بناء الحمولة (Payload) كما يفعل فيسبوك
    const payload = {
      object: "page",
      entry: [
        {
          id: "test_page_id_123",
          time: Math.floor(Date.now() / 1000),
          messaging: [
            {
              sender: { id: "user_test_browser" },
              recipient: { id: "test_page_id_123" },
              timestamp: Date.now(),
              message: { text: message }
            }
          ]
        }
      ]
    }

    try {
      // إرسال الطلب إلى الباكند المحلي
      const res = await fetch("http://localhost:8000/webhooks/meta", {
        method: "POST",
        headers: {
          "Content-Type": "application/json; charset=utf-8",
        },
        body: JSON.stringify(payload),
      })

      if (!res.ok) {
        throw new Error(`Server returned ${res.status}: ${res.statusText}`)
      }

      const data = await res.json()
      
      // عرض الرد الكامل من الخادم
      setResponse(JSON.stringify(data, null, 2))
      
    } catch (err: any) {
      setError(err.message || "Failed to connect to backend")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ 
      minHeight: '100vh', 
      backgroundColor: '#f9fafb', 
      padding: '2rem', 
      fontFamily: 'sans-serif',
      direction: 'rtl' 
    }}>
      <h1 style={{ fontSize: '2rem', fontWeight: 'bold', marginBottom: '1.5rem', color: '#2563eb' }}>
        🧪 DzCommerce Webhook Tester
      </h1>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '2rem', maxWidth: '1200px', margin: '0 auto' }}>
        
        {/* قسم الإدخال */}
        <div style={{ background: 'white', padding: '1.5rem', borderRadius: '0.5rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 'semibold', marginBottom: '1rem' }}>إرسال رسالة للعميل</h2>
          
          <label style={{ display: 'block', marginBottom: '0.5rem', fontSize: '0.875rem', fontWeight: 'medium' }}>نص الرسالة:</label>
          <textarea 
            value={message} 
            onChange={(e) => setMessage(e.target.value)}
            rows={4}
            style={{ 
              width: '100%', 
              padding: '0.5rem', 
              border: '1px solid #d1d5db', 
              borderRadius: '0.375rem',
              marginBottom: '1rem',
              resize: 'vertical'
            }}
            placeholder="اكتب رسالتك هنا..."
          />
          
          <button 
            onClick={sendMessage} 
            disabled={loading}
            style={{ 
              width: '100%', 
              backgroundColor: loading ? '#9ca3af' : '#2563eb', 
              color: 'white', 
              padding: '0.75rem', 
              border: 'none', 
              borderRadius: '0.375rem',
              cursor: loading ? 'not-allowed' : 'pointer',
              fontWeight: 'medium'
            }}
          >
            {loading ? "جارٍ الإرسال والمعالجة..." : "🚀 إرسال إلى AI Agent"}
          </button>

          {error && (
            <div style={{ marginTop: '1rem', padding: '0.75rem', backgroundColor: '#fef2f2', border: '1px solid #fecaca', color: '#dc2626', borderRadius: '0.375rem', fontSize: '0.875rem' }}>
              ❌ خطأ: {error}
            </div>
          )}
        </div>

        {/* قسم العرض */}
        <div style={{ background: '#111827', color: '#4ade80', padding: '1.5rem', borderRadius: '0.5rem', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1)', minHeight: '400px' }}>
          <h2 style={{ fontSize: '1.25rem', fontWeight: 'semibold', marginBottom: '1rem', color: 'white' }}>استجابة الخادم</h2>
          
          {loading ? (
            <div style={{ textAlign: 'center', paddingTop: '2rem', color: '#6b7280' }}>
              جاري الاتصال بـ OpenRouter...
            </div>
          ) : response ? (
            <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: '0.875rem', lineHeight: '1.5', overflowAuto: 'scroll', maxHeight: '500px' }}>
              {response}
            </pre>
          ) : (
            <div style={{ textAlign: 'center', paddingTop: '2rem', fontStyle: 'italic', color: '#6b7280' }}>
              لم يتم إرسال أي طلب بعد.<br/>
              اضغط على زر الإرسال لرؤية رد الذكاء الاصطناعي.
            </div>
          )}
        </div>

      </div>

      <div style={{ marginTop: '2rem', textAlign: 'center', color: '#6b7280', fontSize: '0.875rem' }}>
        💡 ملاحظة: تأكد من تشغيل الباكند على المنفذ 8000 وأن مفتاح API موجود في ملف .env
      </div>
    </div>
  )
}