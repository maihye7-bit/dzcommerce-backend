import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { ProductForm } from "@/components/forms/ProductForm";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import {
  useDeleteProduct,
  useProducts,
} from "@/hooks/useProducts";
import type { Product } from "@/types/api";

const currency = new Intl.NumberFormat("ar-DZ", {
  style: "currency",
  currency: "DZD",
  maximumFractionDigits: 0,
});

export function ProductsPage() {
  const { isOwner, isLoading: roleLoading } = useCurrentUser();
  const productsQuery = useProducts();
  const deleteMutation = useDeleteProduct(productsQuery.storeId);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  const columns: DataTableColumn<Product>[] = [
    { key: "name", header: "المنتج", render: (product) => product.name },
    { key: "sku", header: "SKU", render: (product) => product.sku ?? "—" },
    {
      key: "price",
      header: "السعر",
      render: (product) => currency.format(product.price),
    },
    {
      key: "description",
      header: "الوصف",
      render: (product) => product.description || "—",
      className: "max-w-64 truncate",
    },
    ...(isOwner
      ? [
          {
            key: "actions",
            header: "الإجراءات",
            render: (product: Product) => (
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`تعديل ${product.name}`}
                  onClick={(event) => {
                    event.stopPropagation();
                    setEditingProduct(product);
                  }}
                >
                  <Pencil size={15} aria-hidden="true" />
                  تعديل
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`حذف ${product.name}`}
                  disabled={deleteMutation.isPending}
                  onClick={(event) => {
                    event.stopPropagation();
                    if (window.confirm(`هل تريد حذف ${product.name}؟`)) {
                      deleteMutation.mutate(product.id);
                    }
                  }}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  حذف
                </Button>
              </div>
            ),
          } satisfies DataTableColumn<Product>,
        ]
      : []),
  ];

  return (
    <section className="space-y-6" dir="rtl">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-primary">إدارة المتجر</p>
          <h1 className="mt-2 text-3xl font-bold">المنتجات</h1>
        </div>
        {isOwner && (
          <Button
            className="gap-2"
            onClick={() => setIsCreating(true)}
            disabled={roleLoading || !productsQuery.storeId}
          >
            <Plus size={17} aria-hidden="true" />
            إضافة منتج
          </Button>
        )}
      </div>
      <Card>
        <CardHeader>
          <CardTitle>قائمة المنتجات</CardTitle>
        </CardHeader>
        <CardContent>
          {(productsQuery.isLoading || productsQuery.isStoreLoading) && (
            <LoadingSpinner />
          )}
          {productsQuery.storeError && (
            <ErrorMessage
              error={productsQuery.storeError}
              onRetry={() => void productsQuery.refetchStore()}
            />
          )}
          {productsQuery.isError && (
            <ErrorMessage
              error={productsQuery.error}
              onRetry={() => void productsQuery.refetch()}
            />
          )}
          {productsQuery.data?.length === 0 && (
            <p className="py-10 text-center text-sm text-muted-foreground">
              لا توجد منتجات بعد.
            </p>
          )}
          {productsQuery.data && productsQuery.data.length > 0 && (
            <DataTable
              ariaLabel="قائمة المنتجات"
              columns={columns}
              rows={productsQuery.data}
              getRowKey={(product) => product.id}
            />
          )}
        </CardContent>
      </Card>
      {isOwner && productsQuery.storeId && (isCreating || editingProduct) && (
        <ProductForm
          storeId={productsQuery.storeId}
          product={editingProduct ?? undefined}
          onClose={() => {
            setIsCreating(false);
            setEditingProduct(null);
          }}
        />
      )}
    </section>
  );
}
