import api from "@/lib/api";

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface RegistrationPayload {
  email: string;
  password: string;
  full_name: string;
  store_name: string;
}

export async function login(
  username: string,
  password: string,
): Promise<TokenResponse> {
  const form = new URLSearchParams({ username, password });
  const response = await api.post<TokenResponse>("/api/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return response.data;
}

export async function register(
  payload: RegistrationPayload,
): Promise<TokenResponse> {
  const response = await api.post<TokenResponse>("/api/auth/register", payload);
  return response.data;
}
