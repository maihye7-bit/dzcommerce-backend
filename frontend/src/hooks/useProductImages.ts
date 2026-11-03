import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import type { ProductImage } from "@/types/api";
import { showMutationError, showToast } from "@/lib/toast";

interface ProductImageUpload {
  file: File;
  isPrimary: boolean;
  displayOrder: number;
  onProgress?: (progress: number) => void;
}

interface ProductImageReplacement {
  imageId: string;
  file: File;
  onProgress?: (progress: number) => void;
}

export function resolveProductImageUrl(imageUrl: string) {
  const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || window.location.origin;
  return new URL(imageUrl, apiBaseUrl).toString();
}

export function useProductImages(
  storeId: string | undefined,
  productId: string | undefined,
) {
  const queryClient = useQueryClient();
  const queryKey = ["product-images", storeId, productId];
  const invalidateImages = () =>
    queryClient.invalidateQueries({ queryKey });

  const query = useQuery({
    queryKey,
    queryFn: async () => {
      if (!storeId || !productId) throw new Error("Product is not available");
      const response = await api.get<ProductImage[]>(
        `/api/stores/${storeId}/products/${productId}/images`,
      );
      return response.data;
    },
    enabled: Boolean(storeId && productId),
  });

  const uploadMutation = useMutation({
    mutationFn: async ({
      file,
      isPrimary,
      displayOrder,
      onProgress,
    }: ProductImageUpload) => {
      if (!storeId || !productId) throw new Error("Product is not available");
      const formData = new FormData();
      formData.append("file", file);
      formData.append("is_primary", String(isPrimary));
      formData.append("display_order", String(displayOrder));
      const response = await api.post<ProductImage>(
        `/api/stores/${storeId}/products/${productId}/images`,
        formData,
        {
          onUploadProgress: (event) => {
            if (event.total) onProgress?.(Math.round((event.loaded / event.total) * 100));
          },
        },
      );
      return response.data;
    },
    onSuccess: invalidateImages,
    onError: (error) =>
      showMutationError(error, "تعذر رفع الصورة. تحقق من الملف وحاول مجددًا."),
  });

  const replaceMutation = useMutation({
    mutationFn: async ({ imageId, file, onProgress }: ProductImageReplacement) => {
      if (!storeId || !productId) throw new Error("Product is not available");
      const formData = new FormData();
      formData.append("file", file);
      const response = await api.put<ProductImage>(
        `/api/stores/${storeId}/products/${productId}/images/${imageId}/content`,
        formData,
        {
          onUploadProgress: (event) => {
            if (event.total) onProgress?.(Math.round((event.loaded / event.total) * 100));
          },
        },
      );
      return response.data;
    },
    onSuccess: invalidateImages,
    onError: (error) =>
      showMutationError(error, "تعذر استبدال الصورة. تحقق من الملف وحاول مجددًا."),
  });

  const updateMutation = useMutation({
    mutationFn: async ({
      imageId,
      isPrimary,
    }: {
      imageId: string;
      isPrimary: boolean;
    }) => {
      if (!storeId || !productId) throw new Error("Product is not available");
      const response = await api.patch<ProductImage>(
        `/api/stores/${storeId}/products/${productId}/images/${imageId}`,
        { is_primary: isPrimary },
      );
      return response.data;
    },
    onSuccess: invalidateImages,
    onError: (error) =>
      showMutationError(error, "تعذر تحديث الصورة. حاول مرة أخرى."),
  });

  const deleteMutation = useMutation({
    mutationFn: async (imageId: string) => {
      if (!storeId || !productId) throw new Error("Product is not available");
      await api.delete(
        `/api/stores/${storeId}/products/${productId}/images/${imageId}`,
      );
    },
    onSuccess: async () => {
      await invalidateImages();
      showToast("تم حذف الصورة.", "success");
    },
    onError: (error) =>
      showMutationError(error, "تعذر حذف الصورة. حاول مرة أخرى."),
  });

  const reorderMutation = useMutation({
    mutationFn: async (imageIds: string[]) => {
      if (!storeId || !productId) throw new Error("Product is not available");
      const response = await api.post<ProductImage[]>(
        `/api/stores/${storeId}/products/${productId}/images/reorder`,
        { image_ids: imageIds },
      );
      return response.data;
    },
    onSuccess: invalidateImages,
    onError: (error) =>
      showMutationError(error, "تعذر ترتيب الصور. حاول مرة أخرى."),
  });

  return {
    query,
    uploadImage: uploadMutation.mutateAsync,
    replaceImage: replaceMutation.mutateAsync,
    updateImage: updateMutation.mutateAsync,
    deleteImage: deleteMutation.mutateAsync,
    reorderImages: reorderMutation.mutateAsync,
    isUploading: uploadMutation.isPending,
    isReplacing: replaceMutation.isPending,
    isUpdating: updateMutation.isPending,
    isDeleting: deleteMutation.isPending,
    isReordering: reorderMutation.isPending,
  };
}
