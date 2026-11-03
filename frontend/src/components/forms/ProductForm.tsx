import {
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type FormEvent,
} from "react";
import type { Product } from "@/types/api";
import {
  useCreateProduct,
  useUpdateProduct,
} from "@/hooks/useProducts";
import {
  resolveProductImageUrl,
  useProductImages,
} from "@/hooks/useProductImages";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const MAX_IMAGE_FILE_SIZE = 10 * 1024 * 1024;
const MAX_PRODUCT_IMAGES = 10;
const ACCEPTED_IMAGE_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

interface ProductFormProps {
  storeId: string;
  product?: Product;
  onClose: () => void;
}

export function ProductForm({ storeId, product, onClose }: ProductFormProps) {
  const createMutation = useCreateProduct(storeId);
  const updateMutation = useUpdateProduct(storeId);
  const [savedProduct, setSavedProduct] = useState<Product | null>(null);
  const [name, setName] = useState(product?.name ?? "");
  const [description, setDescription] = useState(product?.description ?? "");
  const [sku, setSku] = useState(product?.sku ?? "");
  const [price, setPrice] = useState(String(product?.price ?? ""));
  const [initialQuantity, setInitialQuantity] = useState("0");
  const [selectedImages, setSelectedImages] = useState<File[]>([]);
  const [primaryImageIndex, setPrimaryImageIndex] = useState(0);
  const [uploadedFiles, setUploadedFiles] = useState<Set<File>>(() => new Set());
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});
  const [imageError, setImageError] = useState<string | null>(null);
  const [hasInvalidImageSelection, setHasInvalidImageSelection] = useState(false);
  const activeProduct = product ?? savedProduct;
  const images = useProductImages(storeId, activeProduct?.id);
  const isPending = createMutation.isPending || updateMutation.isPending;
  const isImagePending =
    images.isUploading ||
    images.isReplacing ||
    images.isUpdating ||
    images.isDeleting ||
    images.isReordering;
  const pendingSelectedCount = selectedImages.filter(
    (file) => !uploadedFiles.has(file),
  ).length;
  const previews = useMemo(
    () =>
      selectedImages.flatMap((file, index) =>
        uploadedFiles.has(file)
          ? []
          : [{ file, index, url: URL.createObjectURL(file) }],
      ),
    [selectedImages, uploadedFiles],
  );

  useEffect(
    () => () => previews.forEach(({ url }) => URL.revokeObjectURL(url)),
    [previews],
  );

  function fileKey(file: File) {
    return `${file.name}-${file.size}-${file.lastModified}`;
  }

  function handleImageSelection(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    setImageError(null);
    setHasInvalidImageSelection(false);
    if (files.some((file) => !ACCEPTED_IMAGE_TYPES.has(file.type))) {
      setImageError("اختر صور JPEG أو PNG أو WebP فقط.");
      setHasInvalidImageSelection(true);
      return;
    }
    if (files.some((file) => file.size > MAX_IMAGE_FILE_SIZE)) {
      setImageError("الحد الأقصى لحجم الصورة هو 10 ميغابايت.");
      setHasInvalidImageSelection(true);
      return;
    }
    const currentCount = images.query.data?.length ?? 0;
    if (currentCount + pendingSelectedCount + files.length > MAX_PRODUCT_IMAGES) {
      setImageError(`يمكن إضافة ${MAX_PRODUCT_IMAGES} صور كحد أقصى لكل منتج.`);
      setHasInvalidImageSelection(true);
      return;
    }
    setSelectedImages((current) => [...current, ...files]);
  }

  function moveSelectedImage(index: number, offset: number) {
    const destination = index + offset;
    if (destination < 0 || destination >= selectedImages.length) return;
    setSelectedImages((current) => {
      const reordered = [...current];
      [reordered[index], reordered[destination]] = [
        reordered[destination],
        reordered[index],
      ];
      return reordered;
    });
    setPrimaryImageIndex((current) => {
      if (current === index) return destination;
      if (current === destination) return index;
      return current;
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (hasInvalidImageSelection) return;
    setImageError(null);
    const sharedPayload = {
      name: name.trim(),
      description: description.trim() || null,
      sku: sku.trim() || null,
      price: Number(price),
    };

    let productWasSaved = Boolean(activeProduct);
    try {
      let productToUpdate = activeProduct;
      if (productToUpdate) {
        await updateMutation.mutateAsync({
          productId: productToUpdate.id,
          payload: sharedPayload,
        });
      } else {
        productToUpdate = await createMutation.mutateAsync({
          ...sharedPayload,
          initial_quantity: Number(initialQuantity),
        });
        productWasSaved = true;
        setSavedProduct(productToUpdate);
      }

      const savedFiles = new Set(uploadedFiles);
      let displayOrder = images.query.data?.length ?? 0;
      for (let index = 0; index < selectedImages.length; index += 1) {
        const file = selectedImages[index];
        if (savedFiles.has(file)) continue;
        await images.uploadImage({
          file,
          isPrimary:
            index === primaryImageIndex ||
            (displayOrder === 0 && index === 0),
          displayOrder,
          onProgress: (progress) =>
            setUploadProgress((current) => ({
              ...current,
              [fileKey(file)]: progress,
            })),
        });
        savedFiles.add(file);
        displayOrder += 1;
        setUploadedFiles(new Set(savedFiles));
      }
      onClose();
    } catch {
      setImageError(
        productWasSaved
          ? "تم حفظ بيانات المنتج، لكن تعذّر إكمال رفع الصور. أعد المحاولة لإكمال العملية."
          : "تعذّر حفظ المنتج. تحقق من البيانات وحاول مجددًا.",
      );
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
            {activeProduct ? "تعديل المنتج" : "إضافة منتج"}
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
          {!activeProduct && (
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
          <section aria-labelledby="product-images-heading" className="space-y-3">
            <div className="space-y-1">
              <h3 id="product-images-heading" className="text-sm font-semibold">
                صور المنتج
              </h3>
              <p className="text-xs text-muted-foreground">
                JPEG أو PNG أو WebP، بحد أقصى 10 ميغابايت للصورة و10 صور للمنتج.
              </p>
            </div>
            {activeProduct && (
              <div className="space-y-3">
                {images.query.isLoading && (
                  <p className="text-sm text-muted-foreground">جارٍ تحميل الصور...</p>
                )}
                {images.query.isError && (
                  <div className="flex items-center justify-between gap-3 text-sm text-destructive">
                    <span>تعذر تحميل صور المنتج.</span>
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => void images.query.refetch()}
                    >
                      إعادة المحاولة
                    </Button>
                  </div>
                )}
                {images.query.data?.map((image, index) => (
                  <div
                    key={image.id}
                    className="flex flex-wrap items-center gap-3 rounded-lg border border-border p-3"
                  >
                    <img
                      alt={activeProduct.name}
                      className="size-16 shrink-0 rounded-md border border-border object-cover"
                      src={resolveProductImageUrl(
                        image.thumbnail_url ?? image.image_url,
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">
                        {image.is_primary ? "الصورة الرئيسية" : `الصورة ${index + 1}`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {Math.round(image.file_size / 1024)} كيلوبايت
                      </p>
                    </div>
                    <div className="flex w-full flex-wrap justify-end gap-1 sm:w-auto">
                      <Button
                        type="button"
                        size="sm"
                        variant={image.is_primary ? "secondary" : "outline"}
                        disabled={isImagePending || image.is_primary}
                        onClick={() =>
                          void images.updateImage({
                            imageId: image.id,
                            isPrimary: true,
                          })
                        }
                      >
                        رئيسية
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={isImagePending || index === 0}
                        aria-label="تحريك الصورة للأمام"
                        onClick={() => {
                          const ordered = [...(images.query.data ?? [])];
                          [ordered[index - 1], ordered[index]] = [
                            ordered[index],
                            ordered[index - 1],
                          ];
                          void images.reorderImages(ordered.map((entry) => entry.id));
                        }}
                      >
                        ↑
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={
                          isImagePending ||
                          index === (images.query.data?.length ?? 0) - 1
                        }
                        aria-label="تحريك الصورة للخلف"
                        onClick={() => {
                          const ordered = [...(images.query.data ?? [])];
                          [ordered[index], ordered[index + 1]] = [
                            ordered[index + 1],
                            ordered[index],
                          ];
                          void images.reorderImages(ordered.map((entry) => entry.id));
                        }}
                      >
                        ↓
                      </Button>
                      <label className="inline-flex cursor-pointer items-center rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-surface-elevated">
                        استبدال
                        <input
                          accept="image/jpeg,image/png,image/webp"
                          className="sr-only"
                          type="file"
                          onChange={(event) => {
                            const file = event.target.files?.[0];
                            event.target.value = "";
                            if (!file) return;
                            if (!ACCEPTED_IMAGE_TYPES.has(file.type)) {
                              setImageError("اختر صورة JPEG أو PNG أو WebP.");
                              setHasInvalidImageSelection(true);
                              return;
                            }
                            if (file.size > MAX_IMAGE_FILE_SIZE) {
                              setImageError("الحد الأقصى لحجم الصورة هو 10 ميغابايت.");
                              setHasInvalidImageSelection(true);
                              return;
                            }
                            setImageError(null);
                            setHasInvalidImageSelection(false);
                            void images.replaceImage({
                              imageId: image.id,
                              file,
                              onProgress: (progress) =>
                                setUploadProgress((current) => ({
                                  ...current,
                                  [image.id]: progress,
                                })),
                            });
                          }}
                        />
                      </label>
                      <Button
                        type="button"
                        size="sm"
                        variant="destructive"
                        disabled={isImagePending}
                        onClick={() => {
                          if (window.confirm("هل تريد حذف هذه الصورة؟")) {
                            void images.deleteImage(image.id);
                          }
                        }}
                      >
                        حذف
                      </Button>
                    </div>
                    {uploadProgress[image.id] !== undefined && (
                      <progress
                        aria-label="تقدم استبدال الصورة"
                        className="w-full"
                        max={100}
                        value={uploadProgress[image.id]}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
            {previews.map(({ file, index, url }) => (
              <div
                key={`${file.name}-${file.lastModified}-${index}`}
                className="flex items-center gap-3 rounded-lg border border-border p-3"
              >
                <img
                  alt={file.name}
                  className="size-16 shrink-0 rounded-md border border-border object-cover"
                  src={url}
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{file.name}</p>
                  {uploadedFiles.has(file) ? (
                    <p className="text-xs text-emerald-500">تم الرفع</p>
                  ) : uploadProgress[fileKey(file)] !== undefined ? (
                    <progress
                      aria-label={`تقدم رفع ${file.name}`}
                      className="w-full"
                      max={100}
                      value={uploadProgress[fileKey(file)]}
                    />
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      {Math.round(file.size / 1024)} كيلوبايت
                    </p>
                  )}
                  <label className="mt-1 flex items-center gap-2 text-xs">
                    <input
                      checked={primaryImageIndex === index}
                      name="new-primary-image"
                      type="radio"
                      onChange={() => setPrimaryImageIndex(index)}
                    />
                    الصورة الرئيسية
                  </label>
                </div>
                <div className="flex gap-1">
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={index === 0 || isPending || isImagePending}
                    aria-label="تقديم الصورة الجديدة"
                    onClick={() => moveSelectedImage(index, -1)}
                  >
                    ↑
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={
                      index === selectedImages.length - 1 ||
                      isPending ||
                      isImagePending
                    }
                    aria-label="تأخير الصورة الجديدة"
                    onClick={() => moveSelectedImage(index, 1)}
                  >
                    ↓
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={isPending || isImagePending}
                    onClick={() => {
                      const removedFile = selectedImages[index];
                      setSelectedImages((current) =>
                        current.filter((_, fileIndex) => fileIndex !== index),
                      );
                      setUploadedFiles((current) => {
                        const next = new Set(current);
                        next.delete(removedFile);
                        return next;
                      });
                      setPrimaryImageIndex((current) =>
                        current >= selectedImages.length - 1
                          ? Math.max(0, current - 1)
                          : current > index
                            ? current - 1
                            : current,
                      );
                    }}
                  >
                    إزالة
                  </Button>
                </div>
              </div>
            ))}
            <label className="inline-flex cursor-pointer items-center rounded-lg border border-border px-4 py-2 text-sm font-medium hover:bg-surface-elevated">
              إضافة صور
              <input
                accept="image/jpeg,image/png,image/webp"
                className="sr-only"
                disabled={
                  Boolean(activeProduct && images.query.isLoading) ||
                  (images.query.data?.length ?? 0) + pendingSelectedCount >=
                    MAX_PRODUCT_IMAGES
                }
                multiple
                type="file"
                onChange={handleImageSelection}
              />
            </label>
            {imageError && (
              <p className="text-sm text-destructive" role="alert">
                {imageError}
              </p>
            )}
            {activeProduct && images.query.data?.length === 0 && selectedImages.length === 0 && (
              <p className="text-sm text-muted-foreground">
                لم تُضف صورًا لهذا المنتج بعد.
              </p>
            )}
          </section>
          <div className="flex justify-end gap-2 border-t pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isPending || isImagePending}
            >
              إلغاء
            </Button>
            <Button type="submit" disabled={isPending || isImagePending}>
              {isPending || isImagePending ? "جارٍ الحفظ..." : "حفظ"}
            </Button>
          </div>
        </form>
      </section>
    </div>
  );
}
