import { useState, type FormEvent } from "react";
import type { Product } from "@/types/api";
import {
  useCreateProduct,
  useUpdateProduct,
} from "@/hooks/useProducts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface ProductFormProps {
  storeId: string;
  product?: Product;
  onClose: () => void;
}

export function ProductForm({ storeId, product, onClose }: ProductFormProps) {
  const createMutation = useCreateProduct(storeId);
  const updateMutation = useUpdateProduct(storeId);
  const [name, setName] = useState(product?.name ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [sku, setSku] = useState(product?.sku ?? "");
  const [price, setPrice] = useState(String(product?.price ?? ""));
  const [initialQuantity, setInitialQuantity] = useState("0");
  const isPending = createMutation.isPending || updateMutation.isPending;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const sharedPayload = {
      name: name.trim(),
      description: description.trim() || null,
      sku: sku.trim() || null,
      price: Number(price),
    };

    try {
      if (product) {
        await updateMutation.mutateAsync({
          productId: product.id,
          payload: sharedPayload,
        });
      } else {
        await createMutation.mutateAsync({
          ...sharedPayload,
          initial_quantity: Number(initialQuantity),
        });
      }
      onClose();
    } catch {
      // Mutation hooks publish typed, user-facing errors through the toast system.
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/40 p-4"
      role="presentation"
    >
      <section
        aria-labelledby="product-form-title"
        aria-modal="true"
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-xl bg-background shadow-xl"
        role="dialog"
        dir="rtl"
      >
        <header className="border-b p-5">
          <h2 id="product-form-title" className="text-lg font-semibold">
            {product ? "تعديل المنتج" : "إضافة منتج"}
          </h2>
        </header>
        <form className="space-y-4 p-5" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <Label htmlFor="product-name">اسم المنتج</Label>
            <Input
              id="product-name"
              maxLength={255}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-description">الوصف</Label>
            <textarea
              id="product-description"
              className="min-h-24 w-full rounded-lg border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-price">السعر الأساسي (DZD)</Label>
            <Input
              id="product-price"
              min="0"
              step="0.01"
              type="number"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-sku">رمز المنتج (اختياري)</Label>
            <Input
              id="product-sku"
              maxLength={64}
              value={sku}
              onChange={(event) => setSku(event.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="product-category">التصنيف</Label>
            <Input
              id="product-category"
              value="غير مدعوم حاليًا"
              disabled
              aria-describedby="category-note"
            />
            <p id="category-note" className="text-xs text-muted-foreground">
              API المنتج الحالي لا يوفّر حقلًا للتصنيف.
            </p>
          </div>
          {!product && (
            <div className="space-y-2">
              <Label htmlFor="product-initial-quantity">الكمية الابتدائية</Label>
              <Input
                id="product-initial-quantity"
                min="0"
                step="1"
                type="number"
                value={initialQuantity}
                onChange={(event) => setInitialQuantity(event.target.value)}
                required
              />
            </div>
          )}
          <div className="flex justify-end gap-2 border-t pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isPending}
            >
              إلغاء
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? "جارٍ الحفظ..." : "حفظ"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
