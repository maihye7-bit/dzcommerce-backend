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

export function DashboardLayout() {
  const { logout } = useAuth();
  const { currentStore } = useCurrentUser();
  const storeName = currentStore?.name ?? "DzCommerce";

  return (
    <div className="min-h-screen bg-background md:flex" dir="rtl">
      <aside
        className="flex w-full flex-col border-b bg-card/80 md:min-h-screen md:w-64 md:border-b-0 md:border-l backdrop-blur-md"
        style={{
          backdropFilter: 'blur(20px)',
          WebkitBackdropFilter: 'blur(20px)'
        }}
      >
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
          {[
            { label: "الرئيسية", to: "/", icon: LayoutDashboard },
            { label: "الطلبات", to: "/orders", icon: ShoppingBag },
            { label: "المحادثات", to: "/conversations", icon: MessageCircle },
            { label: "المنتجات", to: "/products", icon: Package },
            { label: "المخزون", to: "/inventory", icon: ClipboardList },
            { label: "التحليلات", to: "/analytics", icon: BarChart3 },
            { label: "الإعدادات", to: "/settings", icon: Settings },
          ].map(({ label, to, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                `flex shrink-0 items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  isActive
                    ? `bg-primary/20 text-primary`
                    : `text-muted-foreground hover:text-primary hover:bg-muted/30 transition-all`
                }`
              }
            >
              <Icon aria-hidden="true" size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3 md:block">
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
        <header
          className="flex h-16 items-center justify-between border-b bg-card/80 px-5 md:px-8 backdrop-blur-md"
          style={{
            backdropFilter: 'blur(20px)',
            WebkitBackdropFilter: 'blur(20px)'
          }}
        >
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
            onClick={() => window.dispatchEvent(new Event("theme-toggle"))}
          >
            <LogOut aria-hidden="true" size={16} />
            {true ? "light" : "dark"}
          </Button>
        </header>
        <main className="mx-auto w-full max-w-7xl p-5 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}