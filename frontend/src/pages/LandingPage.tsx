import { useEffect, useRef, useState } from "react";
import {
  ArrowDownLeft,
  ArrowLeft,
  ArrowUpLeft,
  BarChart3,
  Boxes,
  Check,
  ChevronDown,
  CircleDollarSign,
  LayoutDashboard,
  Menu,
  MessageCircle,
  Package,
  ShoppingBag,
  Sparkles,
  X,
} from "lucide-react";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type LinkButtonProps = {
  to: string;
  children: React.ReactNode;
  variant?: "primary" | "outline";
  size?: "default" | "lg";
  className?: string;
  onClick?: () => void;
};

function LinkButton({
  to,
  children,
  variant = "primary",
  size = "default",
  className,
  onClick,
}: LinkButtonProps) {
  return (
    <Link
      to={to}
      onClick={onClick}
      className={cn(
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg font-medium outline-none transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        variant === "primary"
          ? "bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 active:bg-primary/80"
          : "border border-border bg-transparent text-foreground hover:border-primary/40 hover:bg-surface-elevated active:bg-muted",
        size === "lg" ? "h-11 px-5 text-sm" : "h-10 px-4 text-sm",
        className,
      )}
    >
      {children}
    </Link>
  );
}

const previewRows = [
  { label: "الطلبات", icon: ShoppingBag },
  { label: "المنتجات والمخزون", icon: Package },
  { label: "محادثات العملاء", icon: MessageCircle },
];

const navigation = [
  { label: "المزايا", href: "#features" },
  { label: "كيف يعمل", href: "#how-it-works" },
  { label: "التكاملات", href: "#integrations" },
];

const capabilities = [
  {
    icon: ShoppingBag,
    title: "إدارة الطلبات",
    description:
      "تابع طلبات متجرك وحالاتها وتفاصيل المنتجات من مساحة عمل واحدة.",
    tone: "orange",
  },
  {
    icon: Package,
    title: "كتالوج المنتجات",
    description:
      "أضف المنتجات وعدّل معلوماتها وأسعارها، مع صلاحيات تناسب فريقك.",
    tone: "coral",
  },
  {
    icon: Boxes,
    title: "متابعة المخزون",
    description:
      "أدر كميات المتغيرات وتعرّف على المنتجات التي تحتاج إلى إعادة التزويد.",
    tone: "teal",
  },
  {
    icon: MessageCircle,
    title: "محادثات العملاء",
    description:
      "راجع المحادثات وسجل الرسائل المرتبط بكل عميل في متجرك.",
    tone: "orange",
  },
  {
    icon: BarChart3,
    title: "تحليلات المتجر",
    description:
      "اطّلع على مؤشرات الطلبات والإيرادات والمنتجات الأكثر مبيعًا.",
    tone: "warm",
  },
  {
    icon: CircleDollarSign,
    title: "إعدادات المتجر",
    description:
      "حدّث ملف متجرك وأدر اتصال صفحات Facebook وInstagram من الإعدادات.",
    tone: "coral",
  },
];

const steps = [
  {
    number: "01",
    title: "أنشئ حسابك ومتجرك",
    description:
      "ابدأ بالتسجيل وأدخل بياناتك واسم المتجر للوصول إلى لوحة الإدارة.",
  },
  {
    number: "02",
    title: "أضف المنتجات والمخزون",
    description:
      "نظّم كتالوج منتجاتك وكمياتها قبل متابعة الطلبات اليومية.",
  },
  {
    number: "03",
    title: "تابع عملياتك من مكان واحد",
    description:
      "راجع الطلبات والمحادثات ومؤشرات المتجر من مساحة العمل نفسها.",
  },
];

function DashboardPreview() {
  return (
    <div
      className="relative mx-auto w-full max-w-[620px]"
      aria-label="معاينة توضيحية للوحة DzCommerce بلا بيانات متجر فعلية"
      dir="ltr"
    >
      <div
        aria-hidden="true"
        className="absolute -inset-8 rounded-[2.5rem] bg-primary/10 blur-3xl"
      />
      <div className="relative overflow-hidden rounded-2xl border border-white/10 bg-[#0d1522]/95 shadow-2xl shadow-black/40 ring-1 ring-white/5">
        <div className="flex h-12 items-center justify-between border-b border-white/[0.08] px-4">
          <div className="flex items-center gap-1.5" aria-hidden="true">
            <span className="size-2.5 rounded-full bg-[#ff6b6b]/80" />
            <span className="size-2.5 rounded-full bg-[#e8b44e]/80" />
            <span className="size-2.5 rounded-full bg-[#56c98a]/80" />
          </div>
          <span className="rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-[10px] text-slate-400">
            معاينة توضيحية · لا تعرض بيانات فعلية
          </span>
          <span className="grid size-7 place-items-center rounded-lg bg-primary text-[9px] font-black text-white">
            DZ
          </span>
        </div>

        <div className="flex min-h-[330px]">
          <aside className="hidden w-14 shrink-0 flex-col items-center gap-5 border-r border-white/[0.07] bg-white/[0.015] py-5 sm:flex">
            {[LayoutDashboard, ShoppingBag, MessageCircle, Package, BarChart3].map(
              (Icon, index) => (
                <span
                  key={index}
                  className={`grid size-7 place-items-center rounded-lg ${
                    index === 0
                      ? "bg-primary/15 text-primary"
                      : "text-slate-500"
                  }`}
                >
                  <Icon size={14} aria-hidden="true" />
                </span>
              ),
            )}
          </aside>

          <div className="min-w-0 flex-1 p-4 sm:p-5" dir="rtl">
            <div className="mb-5 flex items-center justify-between gap-3">
              <div>
                <p className="text-[10px] text-slate-500">مساحة العمل</p>
                <p className="mt-1 text-sm font-semibold text-slate-100">
                  نظرة عامة على المتجر
                </p>
              </div>
              <span className="rounded-lg border border-white/10 px-2.5 py-1.5 text-[10px] text-slate-400">
                متجر تجريبي
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              {[
                { label: "إجمالي الطلبات", icon: ShoppingBag, color: "text-primary" },
                { label: "الإيرادات", icon: CircleDollarSign, color: "text-[#d8b77a]" },
                { label: "طلبات اليوم", icon: Boxes, color: "text-[#65c9b7]" },
                { label: "مخزون منخفض", icon: Package, color: "text-[#ff8a65]" },
              ].map(({ label, icon: Icon, color }) => (
                <div
                  key={label}
                  className="rounded-xl border border-white/[0.08] bg-white/[0.035] p-3"
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="truncate text-[9px] text-slate-400">
                      {label}
                    </span>
                    <Icon className={`size-3.5 shrink-0 ${color}`} aria-hidden="true" />
                  </div>
                  <div className="mt-4 h-5 text-lg font-semibold text-slate-200">
                    —
                  </div>
                  <div className="mt-2 h-1 w-2/3 rounded-full bg-white/[0.07]" />
                </div>
              ))}
            </div>

            <div className="mt-3 grid gap-2.5 sm:grid-cols-[1.4fr_1fr]">
              <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-medium text-slate-300">
                    ملخص النشاط
                  </span>
                  <span className="text-[9px] text-slate-500">بيانات متجرك</span>
                </div>
                <div className="mt-4 flex h-16 items-end gap-1.5" aria-hidden="true">
                  {[34, 52, 40, 67, 48, 76, 57, 86, 62, 72, 46, 65].map(
                    (height, index) => (
                      <span
                        key={index}
                        className={`flex-1 rounded-t-sm ${
                          index === 7
                            ? "bg-primary/80"
                            : "bg-slate-500/25"
                        }`}
                        style={{ height: `${height}%` }}
                      />
                    ),
                  )}
                </div>
              </div>
              <div className="rounded-xl border border-white/[0.08] bg-white/[0.025] p-3.5">
                <span className="text-[10px] font-medium text-slate-300">
                  إدارة من مكان واحد
                </span>
                <div className="mt-3 space-y-2.5">
                  {previewRows.map(({ label, icon: Icon }) => (
                    <div
                      key={label}
                      className="flex items-center gap-2 text-[9px] text-slate-400"
                    >
                      <Icon
                        size={12}
                        className="text-primary"
                        aria-hidden="true"
                      />
                      <span>{label}</span>
                      <Check
                        size={11}
                        className="ms-auto text-[#65c9b7]"
                        aria-hidden="true"
                      />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="absolute -bottom-5 -left-3 hidden items-center gap-2 rounded-xl border border-white/10 bg-[#172338]/95 px-3 py-2.5 shadow-xl shadow-black/20 sm:flex">
        <span className="grid size-8 place-items-center rounded-lg bg-[#65c9b7]/10 text-[#65c9b7]">
          <Sparkles size={15} aria-hidden="true" />
        </span>
        <span className="text-right" dir="rtl">
          <span className="block text-[10px] font-medium text-slate-200">
            مساحة واحدة لمتجرك
          </span>
          <span className="mt-0.5 block text-[9px] text-slate-500">
            واجهة توضيحية
          </span>
        </span>
      </div>
    </div>
  );
}

export function LandingPage() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!isMenuOpen) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsMenuOpen(false);
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = document.querySelectorAll<HTMLElement>(
        "#public-navigation-dialog a[href], #public-navigation-dialog button:not([disabled])",
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
  }, [isMenuOpen]);

  function closeMenu() {
    setIsMenuOpen(false);
  }

  return (
    <div className="min-h-screen overflow-hidden bg-background text-foreground" dir="rtl">
      <header className="sticky top-0 z-30 border-b border-border/70 bg-background/85 backdrop-blur-xl">
        <div className="mx-auto flex h-[4.5rem] max-w-7xl items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
          <Link
            to="/"
            className="flex shrink-0 items-center gap-2.5 rounded-lg outline-none focus-visible:ring-2 focus-visible:ring-ring"
            aria-label="DzCommerce — الصفحة الرئيسية"
          >
            <span className="grid size-9 place-items-center rounded-xl bg-primary text-xs font-black text-primary-foreground shadow-lg shadow-primary/20">
              DZ
            </span>
            <span className="text-base font-bold tracking-tight">
              Dz<span className="text-primary">Commerce</span>
            </span>
          </Link>

          <nav
            aria-label="التنقل الرئيسي"
            className="hidden items-center gap-7 md:flex"
          >
            {navigation.map(({ label, href }) => (
              <a
                key={href}
                href={href}
                className="text-sm text-muted-foreground transition-colors hover:text-foreground"
              >
                {label}
              </a>
            ))}
          </nav>

          <div className="hidden items-center gap-2 sm:flex">
            <Link
              to="/login"
              className="rounded-lg px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              تسجيل الدخول
            </Link>
            <LinkButton to="/login?mode=register">
              ابدأ الآن
              <ArrowLeft size={16} aria-hidden="true" />
            </LinkButton>
          </div>

          <Button
            variant="outline"
            size="icon"
            className="sm:hidden"
            ref={menuButtonRef}
            aria-label="فتح قائمة الموقع"
            aria-expanded={isMenuOpen}
            aria-controls="public-navigation-dialog"
            onClick={() => setIsMenuOpen(true)}
          >
            <Menu size={19} aria-hidden="true" />
          </Button>
        </div>
      </header>

      {isMenuOpen && (
        <div className="fixed inset-0 z-50 sm:hidden">
          <button
            type="button"
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            aria-label="إغلاق قائمة الموقع"
            onClick={closeMenu}
          />
          <nav
            aria-label="قائمة الموقع"
            aria-modal="true"
            role="dialog"
            id="public-navigation-dialog"
            className="absolute inset-x-3 top-3 rounded-2xl border border-border bg-surface p-4 shadow-2xl"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="text-sm font-semibold">تصفّح DzCommerce</span>
              <Button
                ref={closeButtonRef}
                variant="ghost"
                size="icon"
                aria-label="إغلاق قائمة الموقع"
                onClick={closeMenu}
              >
                <X size={18} aria-hidden="true" />
              </Button>
            </div>
            <div className="space-y-1">
              {navigation.map(({ label, href }) => (
                <a
                  key={href}
                  href={href}
                  onClick={closeMenu}
                  className="block rounded-lg px-3 py-3 text-sm text-muted-foreground hover:bg-surface-elevated hover:text-foreground"
                >
                  {label}
                </a>
              ))}
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 border-t border-border pt-3">
              <LinkButton
                to="/login"
                variant="outline"
                onClick={closeMenu}
              >
                تسجيل الدخول
              </LinkButton>
              <LinkButton
                to="/login?mode=register"
                onClick={closeMenu}
              >
                إنشاء حساب
              </LinkButton>
            </div>
          </nav>
        </div>
      )}

      <main>
        <section className="relative isolate">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -right-36 -top-20 -z-10 size-[30rem] rounded-full bg-primary/10 blur-[130px]"
          />
          <div
            aria-hidden="true"
            className="pointer-events-none absolute -bottom-28 left-0 -z-10 size-[26rem] rounded-full bg-[#65c9b7]/[0.07] blur-[120px]"
          />
          <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 pb-20 pt-14 sm:px-6 sm:pb-28 sm:pt-20 lg:grid-cols-[0.88fr_1.12fr] lg:gap-16 lg:px-8 lg:py-28">
            <div className="max-w-xl">
              <div className="inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/[0.08] px-3 py-1.5 text-xs font-medium text-primary">
                <span className="size-1.5 rounded-full bg-primary shadow-[0_0_12px_var(--dz-orange)]" />
                إدارة متجرك الإلكتروني بوضوح
              </div>
              <h1 className="mt-6 text-4xl font-bold leading-[1.28] tracking-tight sm:text-5xl lg:text-[3.55rem]">
                كل تفاصيل متجرك.
                <span className="mt-1 block bg-gradient-to-l from-primary via-[#ff9a61] to-[#65c9b7] bg-clip-text text-transparent">
                  في مساحة واحدة.
                </span>
              </h1>
              <p className="mt-6 max-w-lg text-base leading-8 text-muted-foreground sm:text-lg">
                نظّم المنتجات والمخزون، تابع الطلبات، وراجع محادثات العملاء
                ومؤشرات متجرك من لوحة إدارة واحدة.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <LinkButton to="/login?mode=register" size="lg">
                  أنشئ حساب متجرك
                  <ArrowLeft size={17} aria-hidden="true" />
                </LinkButton>
                <a
                  href="#features"
                  className={cn(
                    "inline-flex h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-lg border border-border bg-transparent px-5 text-sm font-medium text-foreground outline-none transition-colors duration-150 hover:border-primary/40 hover:bg-surface-elevated focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                  )}
                >
                  اكتشف المزايا
                  <ArrowDownLeft size={17} aria-hidden="true" />
                </a>
              </div>
              <div className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
                <span className="inline-flex items-center gap-1.5">
                  <Check size={14} className="text-[#65c9b7]" aria-hidden="true" />
                  إدارة المنتجات والمخزون
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <Check size={14} className="text-[#65c9b7]" aria-hidden="true" />
                  متابعة الطلبات والمحادثات
                </span>
              </div>
            </div>

            <div className="relative px-1 pb-5 sm:px-3">
              <DashboardPreview />
            </div>
          </div>
        </section>

        <section
          id="features"
          className="scroll-mt-24 border-y border-border/70 bg-surface/[0.38] py-20 sm:py-24"
        >
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="mx-auto max-w-2xl text-center">
              <p className="text-sm font-semibold text-primary">منصة واحدة</p>
              <h2 className="mt-3 text-3xl font-bold tracking-tight sm:text-4xl">
                أدوات متجرك، مرتبة حول عملك
              </h2>
              <p className="mt-4 text-sm leading-7 text-muted-foreground sm:text-base">
                واجهات عملية تساعدك على متابعة أساسيات التجارة اليومية دون
                تشتيت بين صفحات وأدوات متعددة.
              </p>
            </div>

            <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {capabilities.map(({ icon: Icon, title, description, tone }, index) => (
                <article
                  key={title}
                  className={`group relative overflow-hidden rounded-2xl border border-border/80 bg-card/80 p-6 transition-all duration-200 hover:-translate-y-1 hover:border-primary/25 hover:shadow-xl hover:shadow-black/10 ${
                    index === 0 ? "lg:col-span-2" : ""
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`grid size-11 place-items-center rounded-xl border ${
                      tone === "orange"
                        ? "border-primary/20 bg-primary/10 text-primary"
                        : tone === "coral"
                          ? "border-[#ff8a65]/20 bg-[#ff8a65]/10 text-[#ff8a65]"
                          : tone === "teal"
                            ? "border-[#65c9b7]/20 bg-[#65c9b7]/10 text-[#65c9b7]"
                            : "border-[#d8b77a]/20 bg-[#d8b77a]/10 text-[#d8b77a]"
                    }`}
                  >
                    <Icon size={20} />
                  </span>
                  <h3 className="mt-5 text-lg font-semibold">{title}</h3>
                  <p className="mt-2 max-w-lg text-sm leading-7 text-muted-foreground">
                    {description}
                  </p>
                  {index === 0 && (
                    <span className="absolute -left-2 -top-8 hidden size-36 rounded-full border border-primary/10 lg:block" />
                  )}
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="how-it-works" className="scroll-mt-24 py-20 sm:py-24">
          <div className="mx-auto grid max-w-7xl gap-12 px-4 sm:px-6 lg:grid-cols-[0.8fr_1.2fr] lg:items-start lg:px-8">
            <div className="max-w-lg">
              <p className="text-sm font-semibold text-primary">بداية واضحة</p>
              <h2 className="mt-3 text-3xl font-bold leading-tight tracking-tight sm:text-4xl">
                من إعداد المتجر إلى متابعة يومك
              </h2>
              <p className="mt-4 text-sm leading-7 text-muted-foreground sm:text-base">
                ابدأ بالأساسيات، ثم استخدم صفحات الإدارة لمتابعة ما يحدث في
                متجرك.
              </p>
              <LinkButton to="/login?mode=register" className="mt-7">
                ابدأ بإنشاء حساب
                <ArrowLeft size={16} aria-hidden="true" />
              </LinkButton>
            </div>

            <ol className="space-y-3">
              {steps.map(({ number, title, description }) => (
                <li
                  key={number}
                  className="flex gap-4 rounded-2xl border border-border/80 bg-card/70 p-5 sm:gap-5 sm:p-6"
                >
                  <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary/10 font-mono text-sm font-semibold text-primary">
                    {number}
                  </span>
                  <div>
                    <h3 className="font-semibold">{title}</h3>
                    <p className="mt-1.5 text-sm leading-6 text-muted-foreground">
                      {description}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section
          id="integrations"
          className="scroll-mt-24 border-y border-border/70 bg-surface/[0.38] py-16 sm:py-20"
        >
          <div className="mx-auto grid max-w-7xl gap-8 px-4 sm:px-6 md:grid-cols-[1fr_auto] md:items-center lg:px-8">
            <div>
              <p className="text-sm font-semibold text-primary">تكامل متاح</p>
              <h2 className="mt-3 text-2xl font-bold tracking-tight sm:text-3xl">
                محادثات صفحات Meta ضمن مساحة متجرك
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-7 text-muted-foreground">
                اربط صفحة Facebook أو Instagram من إعدادات المتجر لمتابعة
                الرسائل عبر واجهة المحادثات. يعتمد توفر الربط على إعداد Meta
                وصلاحيات الصفحة.
              </p>
            </div>
            <div className="flex items-center gap-3 rounded-2xl border border-border bg-card/80 p-4 sm:min-w-64">
              <span className="grid size-12 place-items-center rounded-xl bg-gradient-to-br from-[#4c68d7]/20 via-[#a044a8]/20 to-[#e36b48]/20 text-[#c678c8]">
                <MessageCircle size={22} aria-hidden="true" />
              </span>
              <div>
                <p className="font-semibold">Facebook وInstagram</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  ربط صفحات المتجر
                </p>
              </div>
              <ChevronDown
                className="ms-auto -rotate-90 text-muted-foreground"
                size={16}
                aria-hidden="true"
              />
            </div>
          </div>
        </section>

        <section className="relative isolate overflow-hidden py-20 sm:py-24">
          <div
            aria-hidden="true"
            className="absolute inset-x-0 bottom-0 -z-10 mx-auto h-64 max-w-4xl rounded-full bg-primary/[0.08] blur-[100px]"
          />
          <div className="mx-auto max-w-4xl px-4 text-center sm:px-6">
            <span className="mx-auto grid size-12 place-items-center rounded-2xl border border-primary/20 bg-primary/10 text-primary">
              <ArrowUpLeft size={21} aria-hidden="true" />
            </span>
            <h2 className="mt-5 text-3xl font-bold tracking-tight sm:text-4xl">
              ابدأ بإدارة متجرك من مساحة واحدة
            </h2>
            <p className="mx-auto mt-4 max-w-2xl text-sm leading-7 text-muted-foreground sm:text-base">
              أنشئ حسابك للوصول إلى أدوات المنتجات والمخزون والطلبات ومحادثات
              العملاء.
            </p>
            <LinkButton to="/login?mode=register" size="lg" className="mt-7">
              إنشاء حساب جديد
              <ArrowLeft size={17} aria-hidden="true" />
            </LinkButton>
          </div>
        </section>
      </main>

      <footer className="border-t border-border/70 bg-surface/[0.38]">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-7 sm:flex-row sm:items-center sm:justify-between sm:px-6 lg:px-8">
          <Link to="/" className="flex items-center gap-2 text-sm font-semibold">
            <span className="grid size-7 place-items-center rounded-lg bg-primary text-[9px] font-black text-primary-foreground">
              DZ
            </span>
            DzCommerce
          </Link>
          <p className="text-xs text-muted-foreground">
            مساحة عملية لإدارة متجرك الإلكتروني.
          </p>
          <div className="flex items-center gap-4 text-sm">
            <a
              href="#features"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              المزايا
            </a>
            <Link
              to="/login"
              className="text-muted-foreground transition-colors hover:text-foreground"
            >
              تسجيل الدخول
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
