import {
  type PropsWithChildren,
  useCallback,
  useEffect,
  useMemo,
  useState,
} from "react";
import { login as requestLogin } from "@/lib/auth-api";
import { TOKEN_STORAGE_KEY } from "@/lib/api";
import { AuthContext } from "@/context/auth-context";

export function AuthProvider({ children }: PropsWithChildren) {
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [rememberMe, setRememberMe] = useState(false);

  useEffect(() => {
    // Try localStorage (primary), cookie is handled by Axios interceptor
    const storedToken = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    setToken(storedToken);
    setIsLoading(false);
  }, []);

  const login = useCallback(
    async (username: string, password: string, options: { rememberMe?: boolean } = {}) => {
      const result = await requestLogin(username, password);
      setToken(result.access_token);
      setRememberMe(!!options.rememberMe);

      // Store token in localStorage (both rememberMe options use localStorage;
      // true HttpOnly cookie support would require backend Set-Cookie header)
      window.localStorage.setItem(TOKEN_STORAGE_KEY, result.access_token);
    },
    [],
  );

  const logout = useCallback(() => {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setRememberMe(false);
  }, []);

  const value = useMemo(
    () => ({
      token,
      isAuthenticated: token !== null,
      isLoading,
      login,
      logout,
      rememberMe,
    }),
    [token, isLoading, login, logout, rememberMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
