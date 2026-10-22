import os

code = """\"use client\"

import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle } from \"@/components/ui/card\"
import { ShoppingCart, MessageSquare, Bot, TrendingUp, Users, AlertTriangle, Package } from \"lucide-react\"
import { formatCurrency } from \"@/lib/utils\"
import { apiClient } from \"@/lib/api-client\"

interface DashboardStats {
  total_orders: number
  total_revenue: number
  total_customers: number
  total_products: number
  ai_handled_percentage: number
  active_conversations: number
  cod_risk_count: number
}

export default function DashboardPage() {
  const router = useRouter()
  const [stats, setStats] = useState<DashboardStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) {
      router.push(\"/login\")
      return
    }
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      // استدعاء الـ Endpoint الحقيقي من الباك اند
      const response = await apiClient.get(\"/api/stats/dashboard\")
      setStats(response.data)
    } catch (err: any) {
      console.error(\"Failed to load stats:\", err)
      setError(\"فشل تحميل الإحصائيات. تأكد من تشغيل السيرفر.\")
    } finally {
      setLoading(false)
    }
  }

  if (loading) return <div className=\"p-8 text-center text-gray-500\">جاري تحميل البيانات...</div>
  
  if (error || !stats) return <div className=\"p-8 text-center text-red-500\">{error || \"لا توجد بيانات متاحة\"}</div>

  const cards = [
    { label: \"الطلبات\", value: stats.total_orders, icon: ShoppingCart, color: \"text-blue-600\" },
    { label: \"الإيرادات\", value: formatCurrency(stats.total_revenue), icon: TrendingUp, color: \"text-green-600\" },
    { label: \"العملاء\", value: stats.total_customers, icon: Users, color: \"text-teal-600\" },
    { label: \"المنتجات\", value: stats.total_products, icon: Package, color: \"text-purple-600\" },
    { label: \"AI تعامل معها\", value: `${stats.ai_handled_percentage}%`, icon: Bot, color: \"text-indigo-600\" },
    { label: \"خطر COD\", value: stats.cod_risk_count, icon: AlertTriangle, color: \"text-orange-600\" },
  ]

  return (
    <div className=\"p-4 md:p-8 space-y-6\">
      <h1 className=\"text-2xl md:text-3xl font-bold text-gray-900\">لوحة التحكم</h1>
      <div className=\"grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4\">
        {cards.map((card) => {
          const Icon = card.icon
          return (
            <Card key={card.label}>
              <CardHeader className=\"flex flex-row items-center justify-between pb-2\">
                <CardTitle className=\"text-sm font-medium text-gray-600\">{card.label}</CardTitle>
                <Icon className={`w-4 h-4 ${card.color}`} />
              </CardHeader>
              <CardContent>
                <div className={`text-xl md:text-2xl font-bold ${card.color}`}>{card.value}</div>
              </CardContent>
            </Card>
          )
        })}
      </div>
    </div>
  )
}"""

path = "src/app/(dashboard)/page.tsx"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)

print("✅ Dashboard updated with REAL API calls and NO extra spaces!")
