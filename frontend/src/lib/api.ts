import axios from "axios";
import { showToast } from "@/lib/toast";

export const TOKEN_STORAGE_KEY = "access_token";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
});

api.interceptors.request.use((config) => {
  const token = window.localStorage.getItem(TOKEN_STORAGE_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => {
    if (
      axios.isAxiosError(error) &&
      error.response?.status === 401 &&
      typeof window !== "undefined"
    ) {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
      if (window.location.pathname !== "/login") {
        window.location.assign("/login");
      }
    }
    if (axios.isAxiosError(error) && error.response?.status === 403) {
      showToast("You do not have permission to perform this action", "error");
    } else if (
      axios.isAxiosError(error) &&
      error.response &&
      error.response.status >= 500
    ) {
      showToast("حدث خطأ في الخادم. يرجى المحاولة مرة أخرى.", "error");
    }
    return Promise.reject(error);
  },
);

export default api;
