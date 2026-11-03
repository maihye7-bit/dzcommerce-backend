import {
  Boxes,
  CircleDollarSign,
  LayoutDashboard,
  PackageSearch,
  ShoppingCart,
} from "lucide-react";
import { ErrorMessage } from "@/components/ErrorMessage";
import { StatCard } from "@/components/StatCard";
import { useDashboardStats } from "@/hooks/useAnalytics";

const currency = new Intl.NumberFormat("ar-DZ", {
  style: "currency",
  currency: "DZD",
  maximumFractionDigits: 0,
});

export function DashboardPage() {
  const statsQuery = useDashboardStats();

  return (
    <section className="space-y-6" dir="rtl" aria-busy={statsQuery.isLoading}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="flex items-center gap-2 text-sm font-medium text-primary">
            <LayoutDashboard size={16} aria-hidden="true" />
            نظرة عامة
          </p>
          <h2 className="mt-2 text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
            أداء متجرك
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            ملخص الطلبات والإيرادات والمخزون من بيانات متجرك الحالية.
          </p>
        </div>
      </div>

      {statsQuery.isError && (
        <ErrorMessage
          error={statsQuery.error}
          onRetry={() => {
            void statsQuery.refetch();
          }}
        />
      )}

      {statsQuery.isLoading && (
        <div
          className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4"
          aria-hidden="true"
        >
          {Array.from({ length: 4 }, (_, index) => (
            <div
              key={index}
              className="h-36 animate-pulse rounded-xl border border-border bg-card"
            />
          ))}
        </div>
      )}
      {statsQuery.isLoading && (
        <p role="status" className="sr-only">
          جارٍ تحميل بيانات لوحة التحكم...
        </p>
      )}

      {statsQuery.data && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            title="إجمالي الطلبات"
            value={statsQuery.data.total_orders.toLocaleString("ar-DZ")}
            icon={ShoppingCart}
          />
          <StatCard
            title="الإيرادات"
            value={currency.format(statsQuery.data.total_revenue)}
            icon={CircleDollarSign}
          />
          <StatCard
            title="طلبات اليوم"
            value={statsQuery.data.orders_today.toLocaleString("ar-DZ")}
            icon={Boxes}
          />
          <StatCard
            title="مخزون منخفض"
            value={statsQuery.data.low_stock_items_count.toLocaleString("ar-DZ")}
            icon={PackageSearch}
          />
        </div>
      )}
    </section>
  );
}
