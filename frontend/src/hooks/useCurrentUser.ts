import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { useAuth } from "@/context/useAuth";
import { selectCurrentStore } from "@/lib/stores";
import type { StoreSummary, UserOut } from "@/types/api";

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

  const userQuery = useQuery({
    queryKey: ["user"],
    queryFn: async () => {
      const response = await api.get<UserOut>("/api/auth/me");
      return response.data;
    },
    enabled: Boolean(token),
  });

  const currentStore = selectCurrentStore(storesQuery.data);
  const isSuperAdmin = userQuery.data?.is_super_admin ?? false;

  return {
    ...storesQuery,
    ...userQuery,
    currentStore,
    isOwner: currentStore?.role === "owner",
    isSuperAdmin,
  };
}