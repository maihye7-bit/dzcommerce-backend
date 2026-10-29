import {
  Boxes,
  CircleDollarSign,
  PackageSearch,
  ShoppingCart,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { useDashboardStats } from "@/hooks/useAnalytics";
import { StatCard } from "@/components/StatCard";

export function DashboardPage() {
  const statsQuery = useDashboardStats();
  const isLoading = statsQuery.isLoading;
  const firstError = statsQuery.error;

  return (
    <section className="space-y-6" dir="rtl">
      <div className="flex items-baseline">
        <span className="bg-blue-100 text-blue-800 text-xs font-medium mr-2 px-2 rounded-md">UI TEST — MIMO</span>
        <div>
          <p className="text-sm font-medium text-primary">لوحة التحكم</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight">الرئيسية</h1>
        </div>
      </div>
      {firstError && (
        <div className="alert alert-error">
          <p>{typeof firstError === "string" ? firstError : firstError.message}</p>
        </div>
      )}
      {statsQuery.data && !isLoading && (
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard
            title="إجمالي الطلبات"
            value={statsQuery.data.total_orders.toLocaleString("ar-DZ")}
            icon={ShoppingCart}
            change={String(statsQuery.data.total_orders_change)}
            changeType={statsQuery.data.total_orders_change_type as "increase" | "decrease" | undefined}
          />
          <StatCard
            title="الإيرادات"
            value={new Intl.NumberFormat("ar-DZ", {
              style: "currency",
              currency: "DZD",
              maximumFractionDigits: 0,
            }).format(statsQuery.data.total_revenue)}
            icon={CircleDollarSign}
            change={String(statsQuery.data.total_revenue_change)}
            changeType={statsQuery.data.total_revenue_change_type as "increase" | "decrease" | undefined}
          />
          <StatCard
            title="طلبات اليوم"
            value={statsQuery.data.orders_today.toLocaleString("ar-DZ")}
            icon={Boxes}
            change={String(statsQuery.data.orders_today_change)}
            changeType={statsQuery.data.orders_today_change_type as "increase" | "decrease" | undefined}
          />
          <StatCard
            title="مخزون منخفض"
            value={statsQuery.data.low_stock_items_count.toLocaleString("ar-DZ")}
            icon={PackageSearch}
            change={String(statsQuery.data.low_stock_items_change)}
            changeType={statsQuery.data.low_stock_items_change_type as "increase" | "decrease" | undefined}
          />
        </div>
      )}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div key={index} className="h-28 animate-pulse rounded-xl border bg-card" />
          ))}
          <LoadingSpinner label="جارٍ تحميل بيانات لوحة التحكم..." />
        </div>
      )}
    </section>
  );
}