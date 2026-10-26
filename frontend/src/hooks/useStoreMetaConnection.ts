import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchStoreMetaConnection, connectStoreMeta, disconnectStoreMeta } from "@/lib/meta-api";
import { showToast } from "@/lib/toast";
import type { StoreMetaConnection } from "@/types/api";

export function useStoreMetaConnection(storeId: string | null) {
  const queryClient = useQueryClient();

  const connectionQuery = useQuery({
    queryKey: ["store", "meta-connection", storeId],
    queryFn: () => storeId ? fetchStoreMetaConnection(storeId) : Promise.resolve({ connected: false, pageId: null, pageName: null }),
    enabled: Boolean(storeId),
  });

  const connectMutation = useMutation({
    mutationFn: connectStoreMeta,
    onSuccess: (data, variables, context) => {
      showToast("تم ربط الصفحة بنجاح", "success");
      queryClient.invalidateQueries({ queryKey: ["store", "meta-connection", variables] });
    },
    onError: (error) => {
      showToast("فشل ربط الصفحة: " + (error as Error).message, "error");
    },
  });

  const disconnectMutation = useMutation({
    mutationFn: disconnectStoreMeta,
    onSuccess: (data, variables, context) => {
      showToast("تم قطع الاتصال بالصفحة", "success");
      queryClient.invalidateQueries({ queryKey: ["store", "meta-connection", variables] });
    },
    onError: (error) => {
      showToast("فشل قطع الاتصال: " + (error as Error).message, "error");
    },
  });

  const connect = (storeId: string) => {
    connectMutation.mutate(storeId);
  };

  const disconnect = (storeId: string) => {
    disconnectMutation.mutate(storeId);
  };

  return {
    ...connectionQuery,
    connect,
    disconnect,
    isConnecting: connectMutation.isPending,
    isDisconnecting: disconnectMutation.isPending,
  };
}