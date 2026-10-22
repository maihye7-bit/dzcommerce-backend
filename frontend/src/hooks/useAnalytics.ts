import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/context/useAuth";
import { useStoreId } from "@/hooks/useStoreId";
import type { DashboardStats, TopProduct } from "@/types/api";

export function useDashboardStats() {
  const { token } = useAuth();
  const storeQuery = useStoreId();
  const storeId = storeQuery.data?.id;

  return useQuery({
    queryKey: ["dashboard", "stats", storeId],
    queryFn: async () => {
      const response = await api.get<DashboardStats>(
        "/api/dashboard/stats",
        { params: { store_id: storeId } },
      );
      return response.data;
    },
    enabled: Boolean(token && storeId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useTopProducts() {
  const { token } = useAuth();
  const storeQuery = useStoreId();
  const storeId = storeQuery.data?.id;

  return useQuery({
    queryKey: ["dashboard", "top-products", storeId],
    queryFn: async () => {
      const response = await api.get<TopProduct[]>(
        "/api/dashboard/analytics/top-products",
        { params: { store_id: storeId } },
      );
      return response.data;
    },
    enabled: Boolean(token && storeId),
    staleTime: 5 * 60 * 1000,
  });
}
