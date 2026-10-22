import os

BASE_PATH = "src/app/(dashboard)"

# 1. صفحة العملاء (Customers)
CUSTOMERS_CODE = """\"use client\"

import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle } from \"@/components/ui/card\"
import { Users, Mail, Phone, MapPin, ShoppingBag } from \"lucide-react\"
import { formatCurrency } from \"@/lib/utils\"

interface Customer {
  id: string;
  name: string;
  email: string;
  phone: string;
  city: string;
  total_orders: number;
  lifetime_value: number;
}

export default function CustomersPage() {
  const router = useRouter()
  const [customers, setCustomers] = useState<Customer[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) {
      router.push(\"/login\")
      return
    }
    
    // Mock Data for Customers
    setTimeout(() => {
      setCustomers([
        {
          id: \"CUST-001\",
          name: \"أحمد بن علي\",
          email: \"ahmed.benali@example.com\",
          phone: \"+213 555 123 456\",
          city: \"الجزائر العاصمة\",
          total_orders: 5,
          lifetime_value: 15000,
        },
        {
          id: \"CUST-002\",
          name: \"فاطمة الزهراء\",
          email: \"fatima.z@example.com\",
          phone: \"+213 666 789 012\",
          city: \"وهران\",
          total_orders: 12,
          lifetime_value: 45000,
        },
        {
          id: \"CUST-003\",
          name: \"يوسف مراد\",
          email: \"youssef.m@example.com\",
          phone: \"+213 777 345 678\",
          city: \"قسنطينة\",
          total_orders: 3,
          lifetime_value: 8500,
        },
      ])
      setLoading(false)
    }, 600)
  }, [router])

  if (loading) return <div className=\"p-8 text-center\">جاري تحميل العملاء...</div>

  return (
    <div className=\"p-4 md:p-8 space-y-6\" dir=\"rtl\">
      <h1 className=\"text-2xl md:text-3xl font-bold text-gray-900\">العملاء</h1>
      
      <div className=\"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4\">
        {customers.map((customer) => (
          <Card key={customer.id} className=\"hover:shadow-md transition-shadow\">
            <CardHeader className=\"pb-2\">
              <div className=\"flex justify-between items-start\">
                <CardTitle className=\"text-lg font-semibold\">{customer.name}</CardTitle>
                <span className=\"bg-blue-100 text-blue-800 text-xs px-2 py-1 rounded-full\">#{customer.id}</span>
              </div>
            </CardHeader>
            <CardContent className=\"space-y-3\">
              <div className=\"flex items-center gap-2 text-sm text-gray-600\">
                <Mail className=\"w-4 h-4\" />
                <span>{customer.email}</span>
              </div>
              <div className=\"flex items-center gap-2 text-sm text-gray-600\">
                <Phone className=\"w-4 h-4\" />
                <span>{customer.phone}</span>
              </div>
              <div className=\"flex items-center gap-2 text-sm text-gray-600\">
                <MapPin className=\"w-4 h-4\" />
                <span>{customer.city}</span>
              </div>
              
              <div className=\"pt-4 border-t flex justify-between items-end\">
                <div>
                  <p className=\"text-xs text-gray-500\">إجمالي الطلبات</p>
                  <p className=\"text-lg font-bold text-gray-900\">{customer.total_orders}</p>
                </div>
                <div className=\"text-left\">
                  <p className=\"text-xs text-gray-500\">قيمة العمر</p>
                  <p className=\"text-lg font-bold text-green-600\">{formatCurrency(customer.lifetime_value)}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}"""

# 2. صفحة المنتجات (Products)
PRODUCTS_CODE = """\"use client\"

import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle } from \"@/components/ui/card\"
import { Package, DollarSign, AlertTriangle, CheckCircle } from \"lucide-react\"
import { formatCurrency } from \"@/lib/utils\"

interface Product {
  id: string;
  name: string;
  price: number;
  stock: number;
  status: \"active\" | \"out_of_stock\" | \"low_stock\";
}

export default function ProductsPage() {
  const router = useRouter()
  const [products, setProducts] = useState<Product[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) {
      router.push(\"/login\")
      return
    }
    
    // Mock Data for Products
    setTimeout(() => {
      setProducts([
        {
          id: \"PROD-001\",
          name: \"سماعات رأس لاسلكية Pro\",
          price: 4500,
          stock: 15,
          status: \"active\",
        },
        {
          id: \"PROD-002\",
          name: \"ساعة ذكية Series X\",
          price: 12000,
          stock: 3,
          status: \"low_stock\",
        },
        {
          id: \"PROD-003\",
          name: \"حقيبة ظهر مقاومة للماء\",
          price: 3200,
          stock: 0,
          status: \"out_of_stock\",
        },
        {
          id: \"PROD-004\",
          name: \"شاحن سريع 65W\",
          price: 1800,
          stock: 50,
          status: \"active\",
        },
      ])
      setLoading(false)
    }, 600)
  }, [router])

  if (loading) return <div className=\"p-8 text-center\">جاري تحميل المنتجات...</div>

  const getStatusBadge = (status: string) => {
    switch (status) {
      case \"active\":
        return <span className=\"flex items-center gap-1 text-green-600 text-xs bg-green-50 px-2 py-1 rounded-full\"><CheckCircle className=\"w-3 h-3\"/> متوفر</span>
      case \"low_stock\":
        return <span className=\"flex items-center gap-1 text-yellow-600 text-xs bg-yellow-50 px-2 py-1 rounded-full\"><AlertTriangle className=\"w-3 h-3\"/> مخزون منخفض</span>
      case \"out_of_stock\":
        return <span className=\"flex items-center gap-1 text-red-600 text-xs bg-red-50 px-2 py-1 rounded-full\"><Package className=\"w-3 h-3\"/> نفد المخزون</span>
      default:
        return null
    }
  }

  return (
    <div className=\"p-4 md:p-8 space-y-6\" dir=\"rtl\">
      <h1 className=\"text-2xl md:text-3xl font-bold text-gray-900\">المنتجات</h1>
      
      <div className=\"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4\">
        {products.map((product) => (
          <Card key={product.id} className=\"overflow-hidden hover:shadow-lg transition-all duration-300\">
            <div className=\"h-32 bg-gray-100 flex items-center justify-center\">
              <Package className=\"w-12 h-12 text-gray-300\" />
            </div>
            <CardHeader className=\"pb-2 pt-4\">
              <CardTitle className=\"text-base font-semibold truncate\">{product.name}</CardTitle>
            </CardHeader>
            <CardContent className=\"pb-4\">
              <div className=\"flex justify-between items-center mb-2\">
                <span className=\"text-xl font-bold text-blue-600\">{formatCurrency(product.price)}</span>
                {getStatusBadge(product.status)}
              </div>
              <div className=\"text-sm text-gray-500\">
                المخزون المتبقي: <span className=\"font-medium text-gray-900\">{product.stock}</span> قطعة
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}"""

# 3. صفحة التحليلات (Analytics)
ANALYTICS_CODE = """\"use client\"

import { useEffect, useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { Card, CardContent, CardHeader, CardTitle } from \"@/components/ui/card\"
import { TrendingUp, DollarSign, ShoppingCart, Eye, MousePointerClick } from \"lucide-react\"
import { formatCurrency } from \"@/lib/utils\"

interface AnalyticsData {
  revenue_growth: number;
  conversion_rate: number;
  avg_order_value: number;
  page_views: number;
  clicks: number;
}

export default function AnalyticsPage() {
  const router = useRouter()
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem(\"access_token\")
    if (!token) {
      router.push(\"/login\")
      return
    }
    
    // Mock Data for Analytics
    setTimeout(() => {
      setData({
        revenue_growth: 12.5,
        conversion_rate: 3.8,
        avg_order_value: 4200,
        page_views: 15420,
        clicks: 2340,
      })
      setLoading(false)
    }, 600)
  }, [router])

  if (loading) return <div className=\"p-8 text-center\">جاري تحميل التحليلات...</div>
  
  if (!data) return <div className=\"p-8 text-center text-red-500\">فشل تحميل البيانات.</div>

  return (
    <div className=\"p-4 md:p-8 space-y-6\" dir=\"rtl\">
      <h1 className=\"text-2xl md:text-3xl font-bold text-gray-900\">التحليلات والأداء</h1>
      
      {/* Key Metrics Grid */}
      <div className=\"grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4\">
        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">نمو الإيرادات</CardTitle>
            <TrendingUp className=\"h-4 w-4 text-green-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-green-600\">+{data.revenue_growth}%</div>
            <p className=\"text-xs text-gray-500 mt-1\">مقارنة بالشهر الماضي</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">معدل التحويل</CardTitle>
            <MousePointerClick className=\"h-4 w-4 text-blue-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-blue-600\">{data.conversion_rate}%</div>
            <p className=\"text-xs text-gray-500 mt-1\">من زوار إلى مشترين</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">متوسط قيمة الطلب</CardTitle>
            <DollarSign className=\"h-4 w-4 text-purple-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-purple-600\">{formatCurrency(data.avg_order_value)}</div>
            <p className=\"text-xs text-gray-500 mt-1\">لكل طلب ناجح</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className=\"flex flex-row items-center justify-between space-y-0 pb-2\">
            <CardTitle className=\"text-sm font-medium text-gray-600\">مشاهدات الصفحة</CardTitle>
            <Eye className=\"h-4 w-4 text-orange-600\" />
          </CardHeader>
          <CardContent>
            <div className=\"text-2xl font-bold text-orange-600\">{data.page_views.toLocaleString()}</div>
            <p className=\"text-xs text-gray-500 mt-1\">آخر 30 يوم</p>
          </CardContent>
        </Card>
      </div>

      {/* Simple Chart Placeholder / Table */}
      <div className=\"mt-8 bg-white p-6 rounded-lg border shadow-sm\">
        <h2 className=\"text-xl font-semibold mb-4 text-gray-900\">أفضل المنتجات أداءً</h2>
        <div className=\"space-y-4\">
          {[
            { name: \"سماعات رأس لاسلكية Pro\", sales: 120, revenue: 540000 },
            { name: \"ساعة ذكية Series X\", sales: 85, revenue: 1020000 },
            { name: \"حقيبة ظهر مقاومة للماء\", sales: 60, revenue: 192000 },
          ].map((item, idx) => (
            <div key={idx} className=\"flex items-center justify-between p-3 bg-gray-50 rounded-md\">
              <div className=\"flex items-center gap-3\">
                <span className=\"w-6 h-6 flex items-center justify-center bg-blue-100 text-blue-800 rounded-full text-xs font-bold\">{idx + 1}</span>
                <span className=\"font-medium text-gray-900\">{item.name}</span>
              </div>
              <div className=\"text-left\">
                <p className=\"text-sm font-bold text-gray-900\">{formatCurrency(item.revenue)}</p>
                <p className=\"text-xs text-gray-500\">{item.sales} مبيعات</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}"""

files_to_create = {
    "customers/page.tsx": CUSTOMERS_CODE,
    "products/page.tsx": PRODUCTS_CODE,
    "analytics/page.tsx": ANALYTICS_CODE,
}

for filename, content in files_to_create.items():
    full_path = os.path.join(BASE_PATH, filename)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✅ Created: {full_path}")

print("\n🎉 All remaining pages created successfully!")
