import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/context/useAuth";
import { useStoreId } from "@/hooks/useStoreId";
import type { Order, PaginatedResponse } from "@/types/api";

interface Pagination {
  limit: number;
  offset: number;
}

export function useOrders({ limit, offset }: Pagination) {
  const { token } = useAuth();
  const storeQuery = useStoreId();
  const storeId = storeQuery.data?.id;

  return useQuery({
    queryKey: ["dashboard", "orders", storeId, limit, offset],
    queryFn: async () => {
      const response = await api.get<PaginatedResponse<Order>>(
        "/api/dashboard/orders",
        { params: { store_id: storeId, limit, offset } },
      );
      return response.data;
    },
    enabled: Boolean(token && storeId),
    staleTime: 5 * 60 * 1000,
  });
}

export function useOrder(orderId: string | null) {
  const { token } = useAuth();

  return useQuery({
    queryKey: ["dashboard", "order", orderId],
    queryFn: async () => {
      const response = await api.get<Order>(
        `/api/dashboard/orders/${orderId}`,
      );
      return response.data;
    },
    enabled: Boolean(token && orderId),
    staleTime: 5 * 60 * 1000,
  });
}
