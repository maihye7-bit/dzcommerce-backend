import type { StoreSummary } from "@/types/api";

export function selectCurrentStore(
  stores: StoreSummary[] | undefined,
): StoreSummary | null {
  if (!stores?.length) return null;
  return stores.find((store) => store.role === "owner") ?? stores[0];
}
