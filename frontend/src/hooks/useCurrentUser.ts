import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/context/useAuth";
import { selectCurrentStore } from "@/lib/stores";
import type { StoreSummary } from "@/types/api";

export function useCurrentUser() {
  const { token } = useAuth();
  const storesQuery = useQuery({
    queryKey: ["stores"],
    queryFn: async () => {
      const response = await api.get<StoreSummary[]>("/api/stores");
      return response.data;
    },
    enabled: Boolean(token),
    staleTime: 5 * 60 * 1000,
  });

  const currentStore = selectCurrentStore(storesQuery.data);
  return {
    ...storesQuery,
    currentStore,
    isOwner: currentStore?.role === "owner",
  };
}
