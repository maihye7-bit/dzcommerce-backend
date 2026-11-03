import { useEffect, useRef, useState } from "react";
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageCircle,
  Moon,
  Package,
  Settings,
  ShoppingBag,
  Sun,
  X,
} from "lucide-react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuth } from "@/context/useAuth";
import { Button } from "@/components/ui/button";

const navigation = [
  { label: "الرئيسية", to: "/", icon: LayoutDashboard },
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
  const location = useLocation();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (window.localStorage.getItem("dz-theme") === "light" ? "light" : "dark"),
  );
  const menuButtonRef = useRef<HTMLButtonElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const sidebarRef = useRef<HTMLElement>(null);

  const currentPage =
    navigation.find(({ to }) =>
      to === "/" ? location.pathname === "/" : location.pathname.startsWith(to),
    )?.label ?? "لوحة التحكم";
  const isDashboard = location.pathname === "/";

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.classList.toggle("light", theme === "light");
    window.localStorage.setItem("dz-theme", theme);
  }, [theme]);

  useEffect(() => {
    setIsMobileOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isMobileOpen) return;

    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsMobileOpen(false);
        return;
      }
      if (event.key !== "Tab" || !sidebarRef.current) return;

      const focusable = sidebarRef.current.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled])',
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [isMobileOpen]);

  function toggleTheme() {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }

  const SidebarContent = (
    <>
      <div
        className={`flex h-[4.5rem] items-center border-b border-border px-4 ${
          isCollapsed ? "justify-center" : "justify-between"
        }`}
      >
        <Link
          to="/"
          className="flex min-w-0 items-center gap-3 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label="DzCommerce — الرئيسية"
          onClick={() => setIsMobileOpen(false)}
        >
          <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary text-sm font-black tracking-tight text-primary-foreground shadow-sm">
            DZ
          </span>
          {!isCollapsed && (
            <span className="min-w-0 text-right">
              <span className="block truncate text-sm font-semibold text-foreground">
                DzCommerce
              </span>
              <span className="mt-0.5 block max-w-40 truncate text-xs text-muted-foreground">
                {storeName}
              </span>
            </span>
          )}
        </Link>
        <Button
          ref={closeButtonRef}
          variant="ghost"
          size="icon"
          className="md:hidden"
          aria-label="إغلاق قائمة التنقل"
          onClick={() => setIsMobileOpen(false)}
        >
          <X size={19} aria-hidden="true" />
        </Button>
      </div>

      <nav
        aria-label="التنقل الرئيسي"
        className="flex-1 space-y-1 overflow-y-auto p-3"
      >
        <p
          className={`mb-3 px-3 pt-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground ${
            isCollapsed ? "sr-only" : ""
          }`}
        >
          القائمة الرئيسية
        </p>
        {navigation.map(({ label, to, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            title={isCollapsed ? label : undefined}
            aria-label={isCollapsed ? label : undefined}
            onClick={() => setIsMobileOpen(false)}
            className={({ isActive }) =>
              `group flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring ${
                isCollapsed ? "justify-center px-0" : ""
              } ${
                isActive
                  ? "bg-primary/12 text-primary"
                  : "text-muted-foreground hover:bg-surface-elevated hover:text-foreground"
              }`
            }
          >
            <Icon
              aria-hidden="true"
              size={18}
              className="shrink-0 transition-transform duration-150 group-hover:scale-105"
            />
            {!isCollapsed && <span>{label}</span>}
            {!isCollapsed && location.pathname === to && (
              <span className="ms-auto size-1.5 rounded-full bg-primary" />
            )}
          </NavLink>
        ))}
      </nav>

      <div className="space-y-2 border-t border-border p-3">
        <Button
          variant="ghost"
          className={`w-full text-muted-foreground hover:text-foreground ${
            isCollapsed ? "justify-center px-0" : "justify-start"
          }`}
          title={isCollapsed ? "تسجيل الخروج" : undefined}
          aria-label={isCollapsed ? "تسجيل الخروج" : undefined}
          onClick={logout}
        >
          <LogOut aria-hidden="true" size={18} />
          {!isCollapsed && <span>تسجيل الخروج</span>}
        </Button>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-background" dir="ltr">
      {isMobileOpen && (
        <button
          type="button"
          className="fixed inset-0 z-40 bg-slate-950/65 backdrop-blur-[2px] md:hidden"
          aria-label="إغلاق قائمة التنقل"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      <aside
        id="dashboard-sidebar"
        ref={sidebarRef}
        role={isMobileOpen ? "dialog" : "complementary"}
        aria-label="قائمة لوحة التحكم"
        aria-modal={isMobileOpen ? true : undefined}
        className={`fixed inset-y-0 left-0 z-50 flex w-72 flex-col border-r border-border bg-sidebar text-right shadow-2xl shadow-black/20 transition-[width,transform] duration-200 ease-out md:z-30 md:translate-x-0 md:shadow-none ${
          isCollapsed ? "md:w-[5.25rem]" : "md:w-72"
        } ${
          isMobileOpen
            ? "visible translate-x-0"
            : "invisible -translate-x-full md:visible"
        }`}
        dir="rtl"
      >
        {SidebarContent}
      </aside>

      <div
        dir="rtl"
        className={`min-h-screen transition-[margin] duration-200 ease-out ${
          isCollapsed ? "md:ml-[5.25rem]" : "md:ml-72"
        }`}
      >
        <header className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur-sm">
          <div className="flex min-h-[4.5rem] items-center gap-3 px-4 sm:px-6 lg:px-8">
            <Button
              ref={menuButtonRef}
              variant="outline"
              size="icon"
              className="md:hidden"
              aria-label="فتح قائمة التنقل"
              aria-expanded={isMobileOpen}
              aria-controls="dashboard-sidebar"
              onClick={() => setIsMobileOpen(true)}
            >
              <Menu size={19} aria-hidden="true" />
            </Button>

            <div className="min-w-0 flex-1">
              <nav
                aria-label="مسار التنقل"
                className="mb-1 flex items-center gap-1 text-xs text-muted-foreground"
              >
                <Link
                  to="/"
                  className="rounded-sm outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring"
                >
                  لوحة التحكم
                </Link>
                {!isDashboard && (
                  <>
                    <ChevronLeft size={13} aria-hidden="true" />
                    <span className="text-foreground" aria-current="page">
                      {currentPage}
                    </span>
                  </>
                )}
              </nav>
              <h1 className="truncate text-base font-semibold leading-5 text-foreground sm:text-lg">
                {currentPage}
              </h1>
            </div>

            <div className="hidden max-w-48 truncate text-left text-xs text-muted-foreground sm:block">
              {storeName}
            </div>
            <Button
              variant="outline"
              size="icon"
              aria-label={
                theme === "dark" ? "التبديل إلى الوضع الفاتح" : "التبديل إلى الوضع الداكن"
              }
              title={theme === "dark" ? "الوضع الفاتح" : "الوضع الداكن"}
              onClick={toggleTheme}
            >
              {theme === "dark" ? (
                <Sun size={17} aria-hidden="true" />
              ) : (
                <Moon size={17} aria-hidden="true" />
              )}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="hidden md:inline-flex"
              aria-label={isCollapsed ? "توسيع القائمة الجانبية" : "طي القائمة الجانبية"}
              title={isCollapsed ? "توسيع القائمة" : "طي القائمة"}
              onClick={() => setIsCollapsed((current) => !current)}
            >
              {isCollapsed ? (
                <ChevronRight size={17} aria-hidden="true" />
              ) : (
                <ChevronsLeft size={17} aria-hidden="true" />
              )}
            </Button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1440px] px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
