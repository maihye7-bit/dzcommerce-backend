import { useState } from "react";
import { useOrders } from "@/hooks/useOrders";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { OrderDetailDrawer } from "@/components/OrderDetailDrawer";
import { PaginationControls } from "@/components/PaginationControls";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStoreId } from "@/hooks/useStoreId";
import type { Order } from "@/types/api";

const PAGE_SIZE = 20;
const currency = new Intl.NumberFormat("ar-DZ", {
  style: "currency",
  currency: "DZD",
  maximumFractionDigits: 0,
});

export function OrdersPage() {
  const [page, setPage] = useState(1);
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null);
  const storeQuery = useStoreId();
  const ordersQuery = useOrders({
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  });

  const columns: DataTableColumn<Order>[] = [
    {
      key: "id",
      header: "رقم الطلب",
      render: (order) => (
        <span className="font-mono text-xs">{order.id.slice(0, 8)}</span>
      ),
    },
    {
      key: "customer",
      header: "العميل",
      render: (order) => order.customer_id?.slice(0, 8) ?? "—",
    },
    {
      key: "total",
      header: "الإجمالي",
      render: (order) => currency.format(order.total),
    },
    { key: "status", header: "الحالة", render: (order) => order.status },
    {
      key: "created",
      header: "تاريخ الإنشاء",
      render: (order) =>
        order.created_at
          ? new Date(order.created_at).toLocaleString("ar-DZ")
          : "—",
    },
  ];

  return (
    <section className="space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">إدارة المتجر</p>
        <h1 className="mt-2 text-3xl font-bold">الطلبات</h1>
      </div>
      <Card>
        <CardHeader>
          <CardTitle>كل الطلبات</CardTitle>
        </CardHeader>
        <CardContent>
          {storeQuery.isError && (
            <ErrorMessage
              error={storeQuery.error}
              onRetry={() => void storeQuery.refetch()}
            />
          )}
          {(ordersQuery.isLoading || storeQuery.isLoading) && (
            <LoadingSpinner label="جارٍ تحميل الطلبات..." />
          )}
          {ordersQuery.isError && (
            <ErrorMessage
              error={ordersQuery.error}
              onRetry={() => void ordersQuery.refetch()}
            />
          )}
          {ordersQuery.data?.items.length === 0 && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              لا توجد طلبات بعد.
            </p>
          )}
          {ordersQuery.data && ordersQuery.data.items.length > 0 && (
            <>
              <DataTable
                ariaLabel="قائمة الطلبات"
                columns={columns}
                rows={ordersQuery.data.items}
                getRowKey={(order) => order.id}
                onRowClick={(order) => setSelectedOrderId(order.id)}
              />
              <PaginationControls
                page={page}
                pageSize={PAGE_SIZE}
                total={ordersQuery.data.total}
                onPageChange={setPage}
              />
            </>
          )}
        </CardContent>
      </Card>
      <OrderDetailDrawer
        orderId={selectedOrderId}
        onClose={() => setSelectedOrderId(null)}
      />
    </section>
  );
}
