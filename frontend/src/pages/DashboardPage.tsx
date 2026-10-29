import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

export function DashboardPage() {
  return (
    <section className="space-y-6">
      <div className="flex items-baseline items-baseline flex-row flex-row flex-row flex-row flex-row flex-row flex-row items-baseline">
        <div className="flex items-baseline">
          <span className="bg-blue-100 text-blue-800 text-xs font-medium mr-2 px-2 rounded-md">UI TEST — MIMO</span>
        </div>
        <div>
          <p className="text-sm font-medium text-primary">لوحة التحكم</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">الرئيسية</h1>
        </div>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>مرحبًا بك في DzCommerce</CardTitle>
          <CardDescription>
            ستتوفر بيانات ومؤشرات متجرك في المرحلة 15.2-B.
          </CardDescription>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground">
          تم تسجيل الدخول بنجاح. استخدم القائمة للتنقل بين أقسام لوحة التحكم.
        </CardContent>
      </Card>
    </section>
  );
}
