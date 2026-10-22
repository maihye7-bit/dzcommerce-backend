import os

code = """\"use client\"

import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from \"@/components/ui/card\"
import { Bot, BrainCircuit, ShieldCheck, Zap, MessageSquare, Clock } from \"lucide-react\"
import { cn } from \"@/lib/utils\"

interface AgentStatus {
  is_active: boolean
  model_version: string
  total_interactions_today: number
  avg_response_time_ms: number
  success_rate: number
}

export default function AIEmployeePage() {
  const router = useRouter()
  const [status, setStatus] = useState<AgentStatus | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) {
      router.push(\"/login\")
      return
    }
    
    // محاكاة جلب حالة الموظف الذكي
    setTimeout(() => {
      setStatus({
        is_active: true,
        model_version: \"Qwen-2.5-72B-Instruct\",
        total_interactions_today: 142,
        avg_response_time_ms: 850,
        success_rate: 96.5,
      })
      setLoading(false)
    }, 600)
  }, [router])

  if (loading) return <div className=\"p-8 text-center\">جاري تحميل حالة الموظف...</div>
  
  if (!status) return <div className=\"p-8 text-center text-red-500\">تعذر تحميل البيانات.</div>

  return (
    <div className=\"p-4 md:p-8 space-y-6\" dir=\"rtl\">
      <div className=\"flex flex-col md:flex-row justify-between items-start md:items-center gap-4\">
        <div>
          <h1 className=\"text-2xl md:text-3xl font-bold text-gray-900\">الموظف الذكي (AI Employee)</h1>
          <p className=\"text-gray-500 mt-1\">إدارة وتكوين وكيل المبيعات الذكي الخاص بمتجرك</p>
        </div>
        <div className={cn(
          \"px-3 py-1 rounded-full text-sm font-medium flex items-center gap-2\",
          status.is_active ? \"bg-green-100 text-green-700\" : \"bg-red-100 text-red-700\"
        )}>
          <span className={cn(\"w-2 h-2 rounded-full animate-pulse\", status.is_active ? \"bg-green-500\" : \"bg-red-500\")}></span>
          {status.is_active ? \"نشط الآن\" : \"متوقف\"}
        </div>
      </div>

      {/* Grid for Key Metrics */}
      <div className=\"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4\">
        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">النموذج المستخدم</CardTitle>
            <BrainCircuit className=\"h-4 w-4 text-purple-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-xl font-bold text-gray-900 truncate\">{status.model_version}</div>
            <p className=\"text-xs text-gray-500 mt-1\">آخر تحديث: اليوم</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">تفاعلات اليوم</CardTitle>
            <MessageSquare className=\"h-4 w-4 text-blue-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-blue-600\">{status.total_interactions_today}</div>
            <p className=\"text-xs text-gray-500 mt-1\">محادثات مكتملة</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">سرعة الاستجابة</CardTitle>
            <Clock className=\"h-4 w-4 text-indigo-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-indigo-600\">{(status.avg_response_time_ms / 1000).toFixed(2)}s</div>
            <p className=\"text-xs text-gray-500 mt-1\">متوسط زمن الرد</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">نسبة النجاح</CardTitle>
            <ShieldCheck className=\"h-4 w-4 text-green-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-green-600\">{status.success_rate}%</div>
            <p className=\"text-xs text-gray-500 mt-1\">رضا العملاء المتوقع</p>
          </CardContent>
        </Card>
      </div>

      {/* Capabilities Section */}
      <div className=\"mt-8\">
        <h2 className=\"text-xl font-semibold mb-4 text-gray-900\">قدرات الموظف الحالي</h2>
        <div className=\"grid grid-cols-1 md:grid-cols-3 gap-4\">
          <Card className=\"border-l-4 border-l-blue-500\">
            <CardHeader>
              <CardTitle className=\"flex items-center gap-2\">
                <Bot className=\"w-5 h-5 text-blue-500\" />
                رد تلقائي ذكي
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className=\"text-sm text-gray-600\">
                يجيب على استفسارات المنتجات، الأسعار، والتوفر فوراً وبدقة عالية بناءً على قاعدة معرفتك.
              </p>
            </CardContent>
          </Card>

          <Card className=\"border-l-4 border-l-purple-500\">
            <CardHeader>
              <CardTitle className=\"flex items-center gap-2\">
                <Zap className=\"w-5 h-5 text-purple-500\" />
                إدارة الطلبات (COD)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className=\"text-sm text-gray-600\">
                يساعد في تأكيد طلبات الدفع عند الاستلام ويقلل من نسبة إلغاء الطرود عبر التواصل المبكر.
              </p>
            </CardContent>
          </Card>

          <Card className=\"border-l-4 border-l-green-500\">
            <CardHeader>
              <CardTitle className=\"flex items-center gap-2\">
                <BrainCircuit className=\"w-5 h-5 text-green-500\" />
                تحليل المشاعر
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className=\"text-sm text-gray-600\">
                يكشف عن غضب العميل أو حماسه ويقترح تدخلاً بشرياً فورياً عندما تكون الحاجة ماسة.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Action Buttons Placeholder */}
      <div className=\"flex gap-4 pt-6 border-t\">
        <button className=\"px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors\">
          تكوين الشخصية
        </button>
        <button className=\"px-4 py-2 bg-white border text-gray-700 rounded-md hover:bg-gray-50 transition-colors\">
          عرض سجل المحادثات
        </button>
      </div>
    </div>
  )
}"""

path = "src/app/(dashboard)/ai-employee/page.tsx"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)

print("✅ AI Employee page created successfully!")
