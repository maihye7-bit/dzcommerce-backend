import api from "@/lib/api";

export interface MetaAppConfig {
  appId: string;
  verificationToken: string;
}

export interface StoreMetaConnection {
  connected: boolean;
  pageId: string | null;
  pageName: string | null;
}

/**
 * Fetch the global Meta App configuration (super admin only)
 */
export async function fetchMetaAppConfig(): Promise<MetaAppConfig> {
  const response = await api.get<MetaAppConfig>("/api/super-admin/meta-config");
  return response.data;
}

/**
 * Update the global Meta App configuration (super admin only)
 */
export async function updateMetaAppConfig(config: MetaAppConfig): Promise<void> {
  await api.put("/api/super-admin/meta-config", config);
}

/**
 * Fetch the Meta connection status for a store
 */
export async function fetchStoreMetaConnection(storeId: string): Promise<StoreMetaConnection> {
  const response = await api.get<StoreMetaConnection>(`/api/stores/${storeId}/meta-connection`);
  return response.data;
}

/**
 * Initiate the Meta connection flow for a store.
 * In a real implementation, this would return a URL to redirect the user to for OAuth.
 * For simplicity, we assume the backend handles the OAuth flow and just toggles the connection status.
 */
export async function connectStoreMeta(storeId: string): Promise<StoreMetaConnection> {
  const response = await api.post<StoreMetaConnection>(`/api/stores/${storeId}/meta-connection`, {});
  return response.data;
}

/**
 * Disconnect the Meta connection for a store.
 */
export async function disconnectStoreMeta(storeId: string): Promise<StoreMetaConnection> {
  const response = await api.delete<StoreMetaConnection>(`/api/stores/${storeId}/meta-connection`);
  return response.data;
}