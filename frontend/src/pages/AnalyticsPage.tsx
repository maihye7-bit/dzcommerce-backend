import {
  Boxes,
  CircleDollarSign,
  PackageSearch,
  ShoppingCart,
} from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { StatCard } from "@/components/StatCard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDashboardStats, useTopProducts } from "@/hooks/useAnalytics";
import { useStoreId } from "@/hooks/useStoreId";
import type { TopProduct } from "@/types/api";

const currency = new Intl.NumberFormat("ar-DZ", {
  style: "currency",
  currency: "DZD",
  maximumFractionDigits: 0,
});

const columns: DataTableColumn<TopProduct>[] = [
  { key: "product", header: "المنتج", render: (item) => item.product_name },
  {
    key: "variant",
    header: "المتغير",
    render: (item) => item.variant_name ?? "—",
  },
  { key: "count", header: "الوحدات المباعة", render: (item) => item.count },
  {
    key: "revenue",
    header: "الإيرادات",
    render: (item) => currency.format(item.revenue),
  },
];

export function AnalyticsPage() {
  const storeQuery = useStoreId();
  const statsQuery = useDashboardStats();
  const productsQuery = useTopProducts();
  const isLoading =
    storeQuery.isLoading || statsQuery.isLoading || productsQuery.isLoading;
  const firstError =
    storeQuery.error ?? statsQuery.error ?? productsQuery.error;

  return (
    <section className="space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">نظرة عامة</p>
        <h1 className="mt-2 text-3xl font-bold">التحليلات</h1>
      </div>
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <div
              key={index}
              className="h-28 animate-pulse rounded-xl border bg-card"
            />
          ))}
          <LoadingSpinner label="جارٍ تحميل التحليلات..." />
        </div>
      )}
      {firstError && (
        <ErrorMessage
          error={firstError}
          onRetry={() => {
            void storeQuery.refetch();
            void statsQuery.refetch();
            void productsQuery.refetch();
          }}
        />
      )}
      {statsQuery.data && !isLoading && (
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
      {!isLoading && !firstError && productsQuery.data && (
        <Card>
          <CardHeader>
            <CardTitle>أفضل المنتجات</CardTitle>
            <p className="text-sm text-muted-foreground">
              مرتبة حسب عدد الوحدات المباعة.
            </p>
          </CardHeader>
          <CardContent>
            {productsQuery.data.length === 0 ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                لا توجد بيانات متاحة بعد.
              </p>
            ) : (
              <DataTable
                ariaLabel="أفضل المنتجات"
                columns={columns}
                rows={productsQuery.data}
                getRowKey={(item) => item.product_id + (item.variant_name ?? "")}
              />
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}
