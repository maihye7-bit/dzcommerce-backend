import os

base_path = "src"

# قاموس يحتوي على الكود النظيف مع فواصل الأسطر الصحيحة
files = {
    "app/(dashboard)/page.tsx": """\"use client\"
import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle } from \"@/components/ui/card\"
import { ShoppingCart, MessageSquare, Bot, TrendingUp, Users, AlertTriangle } from \"lucide-react\"
import { formatCurrency } from \"@/lib/utils\"

export default function DashboardPage() {
  const router = useRouter()
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) { router.push(\"/login\"); return }
    setTimeout(() => {
      setStats({ orders: 12, revenue: 450000, conversations: 8, ai_handled: 95, customers: 150, cod_risk: 2 })
      setLoading(false)
    }, 500)
  }, [])

  if (loading) return <div className=\"p-8 text-center\">جاري التحميل...</div>

  const cards = [
    { label: \"الطلبات\", value: stats.orders, icon: ShoppingCart, color: \"text-blue-600\" },
    { label: \"الإيرادات\", value: formatCurrency(stats.revenue), icon: TrendingUp, color: \"text-green-600\" },
    { label: \"المحادثات\", value: stats.conversations, icon: MessageSquare, color: \"text-purple-600\" },
    { label: \"AI تعامل معها\", value: `${stats.ai_handled}%`, icon: Bot, color: \"text-indigo-600\" },
    { label: \"العملاء\", value: stats.customers, icon: Users, color: \"text-teal-600\" },
    { label: \"خطر COD\", value: stats.cod_risk, icon: AlertTriangle, color: \"text-orange-600\" },
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
}""",

    "components/layout/MobileBottomNav.tsx": """\"use client\"
import Link from \"next/link\"
import { usePathname } from \"next/navigation\"
import { Home, MessageSquare, ShoppingCart, Bot } from \"lucide-react\"
import { cn } from \"@/lib/utils\"

const navItems = [
  { href: \"/\", icon: Home, label: \"الرئيسية\" },
  { href: \"/conversations\", icon: MessageSquare, label: \"المحادثات\" },
  { href: \"/orders\", icon: ShoppingCart, label: \"الطلبات\" },
  { href: \"/ai-employee\", icon: Bot, label: \"AI Employee\" },
]

export function MobileBottomNav() {
  const pathname = usePathname()
  return (
    <nav className=\"fixed bottom-0 left-0 right-0 z-50 bg-white border-t border-gray-200 md:hidden\" dir=\"rtl\">
      <div className=\"flex items-center justify-around h-16\">
        {navItems.map((item) => {
          const Icon = item.icon
          const isActive = pathname === item.href
          return (
            <Link key={item.href} href={item.href} className={cn(\"flex flex-col items-center justify-center flex-1 h-full transition-colors\", isActive ? \"text-blue-600\" : \"text-gray-500\")}>
              <Icon className=\"w-5 h-5 mb-1\" />
              <span className=\"text-xs font-medium\">{item.label}</span>
            </Link>
          )
        })}
      </div>
    </nav>
  )
}""",

    "components/layout/DesktopSidebar.tsx": """\"use client\"
import Link from \"next/link\"
import { usePathname } from \"next/navigation\"
import { Home, MessageSquare, ShoppingCart, Bot, Users, Package, BarChart3 } from \"lucide-react\"
import { cn } from \"@/lib/utils\"

const navItems = [
  { href: \"/\", icon: Home, label: \"لوحة التحكم\" },
  { href: \"/conversations\", icon: MessageSquare, label: \"المحادثات\" },
  { href: \"/orders\", icon: ShoppingCart, label: \"الطلبات\" },
  { href: \"/ai-employee\", icon: Bot, label: \"الموظف AI\" },
  { href: \"/customers\", icon: Users, label: \"العملاء\" },
  { href: \"/products\", icon: Package, label: \"المنتجات\" },
  { href: \"/analytics\", icon: BarChart3, label: \"التحليلات\" },
]

export function DesktopSidebar() {
  const pathname = usePathname()
  return (
    <aside className=\"hidden md:flex md:w-64 md:flex-col md:fixed md:inset-y-0 bg-white border-l border-gray-200\" dir=\"rtl\">
      <div className=\"flex flex-col flex-1 min-h-0\">
        <div className=\"flex items-center h-16 px-6 border-b border-gray-200\">
          <h1 className=\"text-xl font-bold text-gray-900\">DzCommerce</h1>
        </div>
        <nav className=\"flex-1 px-4 py-6 space-y-1\">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive = pathname === item.href
            return (
              <Link key={item.href} href={item.href} className={cn(\"flex items-center px-4 py-3 text-sm font-medium rounded-lg transition-colors\", isActive ? \"bg-blue-50 text-blue-600\" : \"text-gray-700 hover:bg-gray-50\")}>
                <Icon className=\"w-5 h-5 ml-3\" />
                {item.label}
              </Link>
            )
          })}
        </nav>
      </div>
    </aside>
  )
}""",

    "app/(dashboard)/layout.tsx": """import { MobileBottomNav } from \"@/components/layout/MobileBottomNav\"
import { DesktopSidebar } from \"@/components/layout/DesktopSidebar\"

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className=\"min-h-screen bg-gray-50\" dir=\"rtl\">
      <DesktopSidebar />
      <main className=\"md:pr-64 pb-20 md:pb-0\">
        {children}
      </main>
      <MobileBottomNav />
    </div>
  )
}"""
}

for path, content in files.items():
    full_path = os.path.join(base_path, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Fixed newlines and spaces in: {full_path}")

print("\n🎉 All files are now clean with proper line breaks!")
