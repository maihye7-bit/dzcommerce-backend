import { useState, type FormEvent } from "react";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useInventory, useUpdateInventory } from "@/hooks/useInventory";
import type { InventoryVariant } from "@/types/api";

function InventoryRow({
  variant,
  storeId,
  canEdit,
}: {
  variant: InventoryVariant;
  storeId: string;
  canEdit: boolean;
}) {
  const [quantity, setQuantity] = useState(String(variant.quantity));
  const updateMutation = useUpdateInventory(storeId);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsedQuantity = Number(quantity);
    if (!Number.isInteger(parsedQuantity) || parsedQuantity < 0) return;
    updateMutation.mutate({
      variantId: variant.id,
      payload: { quantity: parsedQuantity },
    });
  }

  return (
    <div className="grid gap-3 px-4 py-4 sm:grid-cols-[1fr_auto_auto] sm:items-center">
      <div className="min-w-0">
        <p className="font-medium">{variant.name}</p>
        {variant.sku && (
          <p className="mt-1 text-xs text-muted-foreground">{variant.sku}</p>
        )}
      </div>
      <p className="text-sm text-muted-foreground">
        المخزون الحالي:{" "}
        <span className="font-semibold text-foreground">
          {variant.quantity.toLocaleString("ar-DZ")}
        </span>
      </p>
      {canEdit && (
        <form className="flex gap-2" onSubmit={handleSubmit}>
          <Input
            aria-label={`الكمية الجديدة لـ${variant.name}`}
            className="w-28"
            min="0"
            step="1"
            type="number"
            value={quantity}
            onChange={(event) => setQuantity(event.target.value)}
          />
          <Button
            type="submit"
            size="sm"
            disabled={
              updateMutation.isPending ||
              Number(quantity) === variant.quantity
            }
          >
            حفظ
          </Button>
        </form>
      )}
    </div>
  );
}

export function InventoryPage() {
  const { isOwner } = useCurrentUser();
  const inventoryQuery = useInventory();
  const storeId = inventoryQuery.storeId;

  return (
    <section className="space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">إدارة المتجر</p>
        <h1 className="mt-2 text-3xl font-bold">المخزون</h1>
        {!isOwner && (
          <p className="mt-2 text-sm text-muted-foreground">
            صلاحية القراءة فقط. تواصل مع مالك المتجر لتعديل الكميات.
          </p>
        )}
      </div>
      {inventoryQuery.isStoreLoading && <LoadingSpinner />}
      {inventoryQuery.storeError && (
        <ErrorMessage
          error={inventoryQuery.storeError}
          onRetry={() => void inventoryQuery.refetchStore()}
        />
      )}
      {inventoryQuery.isError && (
        <ErrorMessage
          error={inventoryQuery.error}
          onRetry={() => void inventoryQuery.refetch()}
        />
      )}
      {inventoryQuery.isLoading && !inventoryQuery.isStoreLoading && (
        <LoadingSpinner label="جارٍ تحميل المخزون..." />
      )}
      {inventoryQuery.data?.length === 0 && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            لا توجد منتجات أو متغيرات في المخزون بعد.
          </CardContent>
        </Card>
      )}
      {storeId &&
        inventoryQuery.data?.map((product) => (
          <Card key={product.id}>
            <CardHeader>
              <CardTitle>{product.name}</CardTitle>
              <p className="text-sm text-muted-foreground">
                السعر الأساسي:{" "}
                {new Intl.NumberFormat("ar-DZ", {
                  style: "currency",
                  currency: "DZD",
                  maximumFractionDigits: 0,
                }).format(product.base_price)}
              </p>
            </CardHeader>
            <CardContent>
              {product.variants.length ? (
                <div className="divide-y rounded-lg border">
                  {product.variants.map((variant) => (
                    <InventoryRow
                      key={variant.id}
                      variant={variant}
                      storeId={storeId}
                      canEdit={isOwner}
                    />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">
                  لا توجد متغيرات لهذا المنتج.
                </p>
              )}
            </CardContent>
          </Card>
        ))}
    </section>
  );
}
