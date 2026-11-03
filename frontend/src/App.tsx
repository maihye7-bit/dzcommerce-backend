import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  BrowserRouter,
  Navigate,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { AuthProvider } from "@/context/AuthContext";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { DashboardLayout } from "@/layouts/DashboardLayout";
import { DashboardPage } from "@/pages/DashboardPage";
import { LandingPage } from "@/pages/LandingPage";
import { LoginPage } from "@/pages/LoginPage";
import { OrdersPage } from "@/pages/OrdersPage";
import { ConversationsPage } from "@/pages/ConversationsPage";
import { AnalyticsPage } from "@/pages/AnalyticsPage";
import { ProductsPage } from "@/pages/ProductsPage";
import { InventoryPage } from "@/pages/InventoryPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { MetaConfigPage } from "@/pages/super-admin/MetaConfigPage";
import { ToastProvider } from "@/context/ToastProvider";
import { useAuth } from "@/context/useAuth";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

function PublicHomeRoute() {
  const { isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center text-sm text-muted-foreground">
        جارٍ التحقق من الجلسة...
      </div>
    );
  }

  if (!isAuthenticated && location.pathname === "/") {
    return <LandingPage />;
  }

  return <Outlet />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/" element={<PublicHomeRoute />}>
                <Route path="dashboard" element={<Navigate to="/" replace />} />
                <Route element={<ProtectedRoute />}>
                  <Route element={<DashboardLayout />}>
                    <Route index element={<DashboardPage />} />
                    <Route path="orders" element={<OrdersPage />} />
                    <Route path="conversations" element={<ConversationsPage />} />
                    <Route path="products" element={<ProductsPage />} />
                    <Route path="inventory" element={<InventoryPage />} />
                    <Route path="settings" element={<SettingsPage />} />
                    <Route path="analytics" element={<AnalyticsPage />} />
                  </Route>
                </Route>
              </Route>
              <Route element={<ProtectedRoute />}>
                <Route path="/super-admin" element={<MetaConfigPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
