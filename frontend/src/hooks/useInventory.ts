import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type {
  InventoryProduct,
  InventoryUpdatePayload,
} from "@/types/api";
import { showMutationError, showToast } from "@/lib/toast";

export function useInventory() {
  const {
    currentStore,
    isLoading: isStoreLoading,
    error: storeError,
    refetch: refetchStore,
  } = useCurrentUser();
  const storeId = currentStore?.id;
  const query = useQuery({
    queryKey: ["inventory", storeId],
    queryFn: async () => {
      const response = await api.get<InventoryProduct[]>(
        `/api/stores/${storeId}/inventory/products`,
      );
      return response.data;
    },
    enabled: Boolean(storeId),
    staleTime: 5 * 60 * 1000,
  });
  return { ...query, storeId, isStoreLoading, storeError, refetchStore };
}

export function useUpdateInventory(storeId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      variantId,
      payload,
    }: {
      variantId: string;
      payload: InventoryUpdatePayload;
    }) => {
      if (!storeId) throw new Error("Store is not available");
      const response = await api.patch(
        `/api/stores/${storeId}/variants/${variantId}/inventory`,
        payload,
      );
      return response.data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["inventory", storeId] }),
        queryClient.invalidateQueries({
          queryKey: ["dashboard", "stats", storeId],
        }),
      ]);
      showToast("تم تحديث المخزون بنجاح.", "success");
    },
    onError: (error) =>
      showMutationError(error, "تعذر تحديث المخزون. تحقق من البيانات."),
  });
}
