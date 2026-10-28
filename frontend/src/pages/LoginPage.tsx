import { useState, useCallback, type FormEvent } from "react";
import axios from "axios";
import { useLocation, useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/context/useAuth";

interface LoginLocationState {
  from?: {
    pathname?: string;
  };
}

export function LoginPage() {
  // All state variables declared upfront
  const [isLoggingIn, setIsLoggingIn] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [registerEmail, setRegisterEmail] = useState("");
  const [registerPassword, setRegisterPassword] = useState("");
  const [registerConfirmPassword, setRegisterConfirmPassword] = useState("");
  const [registerFullName, setRegisterFullName] = useState("");
  const [registerStoreName, setRegisterStoreName] = useState("");

  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Handle login submission
  const handleLoginSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);

      try {
        await login(email, password);
        const state = location.state as LoginLocationState | null;
        navigate(state?.from?.pathname ?? "/", { replace: true });
      } catch (loginError: unknown) {
        if (
          axios.isAxiosError(loginError) &&
          loginError.response?.status === 429
        ) {
          setError("محاولات كثيرة. يرجى الانتظار دقيقة ثم المحاولة مجددًا.");
        } else if (
          axios.isAxiosError(loginError) &&
          loginError.response?.status === 401
        ) {
          setError("البريد الإلكتروني أو كلمة المرور غير صحيحة.");
        } else {
          setError("تعذر تسجيل الدخول. تحقق من اتصالك وحاول مرة أخرى.");
        }
      } finally {
        setIsSubmitting(false);
      }
    },
    [email, password, location, navigate],
  );

  // Handle registration submission via direct API call
  const handleRegisterSubmit = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      setError(null);
      setIsSubmitting(true);

      if (registerPassword !== registerConfirmPassword) {
        setError("كلمة المرور والتأكيد غير المتطابقتين.");
        setIsSubmitting(false);
        return;
      }

      try {
        await axios.post("/api/auth/register", {
          email: registerEmail,
          password: registerPassword,
          full_name: registerFullName,
          store_name: registerStoreName,
        });
        // Auto-login after successful registration
        await login(registerEmail, registerPassword);
        navigate("/dashboard", { replace: true });
      } catch (registerError: unknown) {
        if (
          axios.isAxiosError(registerError) &&
          registerError.response?.status === 400
        ) {
          setError("البريد الإلكتروني مستخدم مسبقاً. يرجى استخدام عنوان بريد مختلف.");
        } else if (
          axios.isAxiosError(registerError) &&
          registerError.response?.status === 500
        ) {
          setError("حدث خطأ في الخادم. يرجى المحاولة مرة أخرى.");
        } else {
          setError("تعذر إنشاء الحساب. يرجى المحاولة مرة أخرى.");
        }
      } finally {
        setIsSubmitting(false);
      }
    },
    [
      registerEmail,
      registerPassword,
      registerFullName,
      registerStoreName,
      registerConfirmPassword,
      login,
      navigate,
    ],
  );

  return (
    <main
      className="grid min-h-screen place-items-center bg-gradient-to-br from-slate-100 via-background to-sky-100 p-4"
      dir="rtl"
    >
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-2">
          <p className="text-sm font-semibold text-primary">DzCommerce</p>

          {isLoggingIn ? (
            <>
              <CardTitle className="text-2xl">مرحبًا بعودتك</CardTitle>
              <CardDescription>سجّل الدخول إلى لوحة إدارة متجرك.</CardDescription>
            </>
          ) : (
            <>
              <CardTitle className="text-2xl">انشاء حساب جديد</CardTitle>
              <CardDescription>سجّل دخولك إلى لوحة الإدارة.</CardDescription>
            </>
          )}
        </CardHeader>

        <CardContent>
          {isLoggingIn ? (
            <form className="space-y-5" onSubmit={handleLoginSubmit}>
              <div className="space-y-2">
                <Label htmlFor="email">البريد الإلكتروني</Label>
                <Input
                  autoComplete="username"
                  id="email"
                  type="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">كلمة المرور</Label>
                <Input
                  autoComplete="current-password"
                  id="password"
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  required
                />
              </div>
              {error && (
                <p
                  role="alert"
                  className="rounded-lg border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive"
                >
                  {error}
                </p>
              )}
              <Button className="w-full" type="submit" disabled={isSubmitting}>
                {isSubmitting ? "جارٍ تسجيل الدخول..." : "تسجيل الدخول"}
              </Button>
              <p className="text-sm text-muted-foreground mt-2">
                لا تملك Account؟ {" "}
                <Button
                  onClick={() => setIsLoggingIn(!isLoggingIn)}
                  className="underline text-primary"
                >
                  أنشئ Account جديد
                </Button>
              </p>
            </form>
          ) : (
            <form className="space-y-5" onSubmit={handleRegisterSubmit}>
              <div className="space-y-2">
                <Label htmlFor="reg-email">البريد الإلكتروني</Label>
                <Input
                  autoComplete="email"
                  id="reg-email"
                  type="email"
                  value={registerEmail}
                  onChange={(event) => setRegisterEmail(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-full-name">الاسم الكامل</Label>
                <Input
                  id="reg-full-name"
                  type="text"
                  value={registerFullName}
                  onChange={(event) => setRegisterFullName(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-store-name">اسم المتجر</Label>
                <Input
                  id="reg-store-name"
                  type="text"
                  value={registerStoreName}
                  onChange={(event) => setRegisterStoreName(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-password">كلمة المرور</Label>
                <Input
                  autoComplete="current-password"
                  id="reg-password"
                  type="password"
                  value={registerPassword}
                  onChange={(event) => setRegisterPassword(event.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="reg-confirm-password">確認 كلمة المرور</Label>
                <Input
                  autoComplete="current-password"
                  id="reg-confirm-password"
                  type="password"
                  value={registerConfirmPassword}
                  onChange={(event) => setRegisterConfirmPassword(event.target.value)}
                  required
                />
              </div>
              <Button className="w-full" type="submit" disabled={isSubmitting}>
                {isSubmitting ? "جارٍ إنشاء الحساب..." : "إنشاء الحساب"}
              </Button>
              <p className="text-sm text-muted-foreground mt-2">
                Already have an account? {" "}
                <Button
                  onClick={() => setIsLoggingIn(!isLoggingIn)}
                  className="underline text-primary"
                >
                  سجل دخول
                </Button>
              </p>
            </form>
          )}
        </CardContent>
      </Card>
    </main>
  );
}