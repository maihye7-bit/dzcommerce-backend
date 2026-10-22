import os

code = """\"use client\"

import { useState } from \"react\"
import { useRouter } from \"next/navigation\"
import { apiClient } from \"@/lib/api-client\"
import { Button } from \"@/components/ui/button\"
import { Input } from \"@/components/ui/input\"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from \"@/components/ui/card\"

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState(\"\")
  const [password, setPassword] = useState(\"\")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const body = new URLSearchParams()
      body.append(\"username\", email)
      body.append(\"password\", password)
      const response = await apiClient.post(\"/api/auth/login\", body, {
        headers: { \"Content-Type\": \"application/x-www-form-urlencoded\" },
      })
      localStorage.setItem(\"access_token\", response.data.access_token)
      router.push(\"/\")
    } catch (err: any) {
      setError(err.response?.data?.detail || \"فشل تسجيل الدخول\")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className=\"min-h-screen flex items-center justify-center bg-gray-50 p-4\" dir=\"rtl\">
      <Card className=\"w-full max-w-md\">
        <CardHeader>
          <CardTitle className=\"text-2xl\">DzCommerce</CardTitle>
          <CardDescription>سجّل الدخول إلى لوحة التحكم</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className=\"space-y-4\">
            <div className=\"space-y-2\">
              <label className=\"text-sm font-medium\">البريد الإلكتروني</label>
              <Input type=\"email\" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className=\"space-y-2\">
              <label className=\"text-sm font-medium\">كلمة المرور</label>
              <Input type=\"password\" value={password} onChange={(e) => setPassword(e.target.value)} required />
            </div>
            {error && <div className=\"p-3 text-sm text-red-600 bg-red-50 rounded-md\">{error}</div>}
            <Button type=\"submit\" className=\"w-full\" disabled={loading}>
              {loading ? \"جارٍ الدخول...\" : \"دخول\"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}"""

path = "src/app/(auth)/login/page.tsx"
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)

print("✅ Login page fixed with proper line breaks!")
