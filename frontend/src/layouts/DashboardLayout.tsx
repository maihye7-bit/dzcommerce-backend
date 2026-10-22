import {
  BarChart3,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  MessageCircle,
  Package,
  Settings,
  ShoppingBag,
} from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuth } from "@/context/useAuth";
import { Button } from "@/components/ui/button";

const navigation = [
  { label: "الرئيسية", to: "/", icon: LayoutDashboard, end: true },
  { label: "الطلبات", to: "/orders", icon: ShoppingBag },
  { label: "المحادثات", to: "/conversations", icon: MessageCircle },
  { label: "المنتجات", to: "/products", icon: Package },
  { label: "المخزون", to: "/inventory", icon: ClipboardList },
  { label: "التحليلات", to: "/analytics", icon: BarChart3 },
  { label: "الإعدادات", to: "/settings", icon: Settings },
];

export function DashboardLayout() {
  const { logout } = useAuth();
  const { currentStore } = useCurrentUser();
  const storeName = currentStore?.name ?? "DzCommerce";

  return (
    <div className="min-h-screen bg-background md:flex" dir="rtl">
      <aside className="flex w-full flex-col border-b bg-card md:min-h-screen md:w-64 md:border-b-0 md:border-l">
        <div className="border-b px-6 py-5">
          <p className="text-lg font-bold text-primary">DzCommerce</p>
          <p className="mt-1 truncate text-sm text-muted-foreground">
            {storeName}
          </p>
        </div>
        <nav
          aria-label="التنقل الرئيسي"
          className="flex gap-1 overflow-x-auto p-3 md:flex-1 md:flex-col"
        >
          {navigation.map(({ label, to, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`
              }
            >
              <Icon aria-hidden="true" size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="hidden border-t p-3 md:block">
          <Button
            variant="ghost"
            className="w-full justify-start gap-3"
            onClick={logout}
          >
            <LogOut aria-hidden="true" size={18} />
            تسجيل الخروج
          </Button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="flex h-16 items-center justify-between border-b bg-card px-5 md:px-8">
          <p className="truncate font-medium">{storeName}</p>
          <Button
            variant="outline"
            size="sm"
            className="gap-2 md:hidden"
            onClick={logout}
          >
            <LogOut aria-hidden="true" size={16} />
            خروج
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="hidden gap-2 md:inline-flex"
            onClick={logout}
          >
            <LogOut aria-hidden="true" size={16} />
            تسجيل الخروج
          </Button>
        </header>
        <main className="mx-auto w-full max-w-7xl p-5 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
