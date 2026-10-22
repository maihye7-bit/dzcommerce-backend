import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type {
  Product,
  ProductCreatePayload,
  ProductUpdatePayload,
} from "@/types/api";
import { showMutationError, showToast } from "@/lib/toast";

export function useProducts() {
  const {
    currentStore,
    isLoading: isStoreLoading,
    error: storeError,
    refetch: refetchStore,
  } = useCurrentUser();
  const storeId = currentStore?.id;

  const query = useQuery({
    queryKey: ["products", storeId],
    queryFn: async () => {
      const response = await api.get<Product[]>(
        `/api/stores/${storeId}/products`,
      );
      return response.data;
    },
    enabled: Boolean(storeId),
    staleTime: 5 * 60 * 1000,
  });

  return { ...query, storeId, isStoreLoading, storeError, refetchStore };
}

export function useCreateProduct(storeId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ProductCreatePayload) => {
      if (!storeId) throw new Error("Store is not available");
      const response = await api.post<Product>(
        `/api/stores/${storeId}/products`,
        payload,
      );
      return response.data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["products", storeId] }),
        queryClient.invalidateQueries({ queryKey: ["inventory", storeId] }),
      ]);
      showToast("تم إنشاء المنتج بنجاح.", "success");
    },
    onError: (error) =>
      showMutationError(
        error,
        "تعذر حفظ المنتج. تحقق من البيانات وحاول مجددًا.",
      ),
  });
}

export function useUpdateProduct(storeId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      productId,
      payload,
    }: {
      productId: string;
      payload: ProductUpdatePayload;
    }) => {
      if (!storeId) throw new Error("Store is not available");
      const response = await api.patch<Product>(
        `/api/stores/${storeId}/products/${productId}`,
        payload,
      );
      return response.data;
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["products", storeId] });
      showToast("تم تحديث المنتج بنجاح.", "success");
    },
    onError: (error) =>
      showMutationError(
        error,
        "تعذر حفظ المنتج. تحقق من البيانات وحاول مجددًا.",
      ),
  });
}

export function useDeleteProduct(storeId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (productId: string) => {
      if (!storeId) throw new Error("Store is not available");
      await api.delete(`/api/stores/${storeId}/products/${productId}`);
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["products", storeId] }),
        queryClient.invalidateQueries({ queryKey: ["inventory", storeId] }),
      ]);
      showToast("تم حذف المنتج بنجاح.", "success");
    },
    onError: (error) =>
      showMutationError(error, "تعذر حذف المنتج. حاول مرة أخرى."),
  });
}
