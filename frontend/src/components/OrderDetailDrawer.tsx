import { useOrder } from "@/hooks/useOrders";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ErrorMessage } from "@/components/ErrorMessage";

interface OrderDetailDrawerProps {
  orderId: string | null;
  onClose: () => void;
}

const currency = new Intl.NumberFormat("ar-DZ", {
  style: "currency",
  currency: "DZD",
  maximumFractionDigits: 0,
});

export function OrderDetailDrawer({
  orderId,
  onClose,
}: OrderDetailDrawerProps) {
  const orderQuery = useOrder(orderId);
  if (!orderId) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" role="presentation">
      <button
        className="absolute inset-0 cursor-default"
        aria-label="إغلاق تفاصيل الطلب"
        onClick={onClose}
      />
      <aside
        aria-labelledby="order-detail-title"
        aria-modal="true"
        className="relative h-full w-full max-w-xl overflow-y-auto bg-background shadow-xl"
        role="dialog"
        dir="rtl"
      >
        <div className="sticky top-0 flex items-center justify-between border-b bg-background p-5">
          <div>
            <h2 id="order-detail-title" className="text-lg font-semibold">
              تفاصيل الطلب
            </h2>
            <p className="mt-1 max-w-64 truncate text-xs text-muted-foreground">
              {orderId}
            </p>
          </div>
          <Button variant="outline" size="sm" onClick={onClose}>
            إغلاق
          </Button>
        </div>
        <div className="space-y-6 p-5">
          {orderQuery.isLoading && <LoadingSpinner />}
          {orderQuery.isError && (
            <ErrorMessage
              error={orderQuery.error}
              onRetry={() => void orderQuery.refetch()}
            />
          )}
          {orderQuery.data && (
            <>
              <div className="grid grid-cols-2 gap-3 rounded-lg border bg-card p-4 text-sm">
                <p className="text-muted-foreground">الحالة</p>
                <p className="text-left">{orderQuery.data.status}</p>
                <p className="text-muted-foreground">الإجمالي</p>
                <p className="text-left font-semibold">
                  {currency.format(orderQuery.data.total)}
                </p>
                <p className="text-muted-foreground">تاريخ الإنشاء</p>
                <p className="text-left">
                  {orderQuery.data.created_at
                    ? new Date(orderQuery.data.created_at).toLocaleString("ar-DZ")
                    : "—"}
                </p>
              </div>
              <section>
                <h3 className="mb-3 font-semibold">العناصر</h3>
                <div className="divide-y rounded-lg border bg-card">
                  {orderQuery.data.items.map((item) => {
                    const lineTotal =
                      item.line_total ?? item.unit_price * item.quantity;
                    return (
                      <div key={item.id} className="space-y-2 p-4">
                        <div className="flex justify-between gap-3">
                          <p className="font-medium">
                            {item.product_name ?? "منتج"}
                          </p>
                          <p className="font-semibold">
                            {currency.format(lineTotal)}
                          </p>
                        </div>
                        <p className="text-sm text-muted-foreground">
                          {item.variant_name ?? "بدون متغير"} · الكمية:{" "}
                          {item.quantity}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          سعر الوحدة: {currency.format(item.unit_price)}
                        </p>
                      </div>
                    );
                  })}
                </div>
              </section>
              {(orderQuery.data.wilaya ||
                orderQuery.data.shipping_address) && (
                <section>
                  <h3 className="mb-3 font-semibold">معلومات الشحن</h3>
                  <div className="space-y-2 rounded-lg border bg-card p-4 text-sm">
                    {orderQuery.data.wilaya && (
                      <p>الولاية: {orderQuery.data.wilaya}</p>
                    )}
                    {orderQuery.data.shipping_address && (
                      <p>{orderQuery.data.shipping_address}</p>
                    )}
                    <p>
                      تكلفة الشحن:{" "}
                      {currency.format(orderQuery.data.shipping_cost)}
                    </p>
                  </div>
                </section>
              )}
            </>
          )}
        </div>
      </aside>
    </div>
  );
}
