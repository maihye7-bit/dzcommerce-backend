import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth } from "@/context/useAuth";

export function ProtectedRoute() {
  const { isAuthenticated, isLoading, token, logout } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">
        جارٍ التحقق من الجلسة...
      </div>
    );
  }

  if (!isAuthenticated) {
    // If there's a token but user is not authenticated, redirect to login
    if (token) {
      logout();
    }
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return <Outlet />;
}
