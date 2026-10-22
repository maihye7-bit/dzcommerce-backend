import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import type { StoreProfile, StoreUpdatePayload } from "@/types/api";
import { showMutationError, showToast } from "@/lib/toast";

export function useStoreProfile() {
  const { currentStore, isLoading: isStoreLoading } = useCurrentUser();
  const storeId = currentStore?.id;
  const query = useQuery({
    queryKey: ["store-profile", storeId],
    queryFn: async () => {
      const response = await api.get<StoreProfile>(`/api/stores/${storeId}`);
      return response.data;
    },
    enabled: Boolean(storeId),
    staleTime: 5 * 60 * 1000,
  });
  return { ...query, storeId, isStoreLoading };
}

export function useUpdateStoreProfile(storeId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: StoreUpdatePayload) => {
      if (!storeId) throw new Error("Store is not available");
      const response = await api.patch<StoreProfile>(
        `/api/stores/${storeId}`,
        payload,
      );
      return response.data;
    },
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["store-profile", storeId] }),
        queryClient.invalidateQueries({ queryKey: ["stores"] }),
      ]);
      showToast("تم تحديث اسم المتجر بنجاح.", "success");
    },
    onError: (error) =>
      showMutationError(error, "تعذر تحديث بيانات المتجر."),
  });
}
