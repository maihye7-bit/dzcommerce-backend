import { useState, type FormEvent } from "react";
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
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
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
  }

  return (
    <main
      className="grid min-h-screen place-items-center bg-gradient-to-br from-slate-100 via-background to-sky-100 p-4"
      dir="rtl"
    >
      <Card className="w-full max-w-md shadow-lg">
        <CardHeader className="space-y-2">
          <p className="text-sm font-semibold text-primary">DzCommerce</p>
          <CardTitle className="text-2xl">مرحبًا بعودتك</CardTitle>
          <CardDescription>سجّل الدخول إلى لوحة إدارة متجرك.</CardDescription>
        </CardHeader>
        <CardContent>
          <form className="space-y-5" onSubmit={handleSubmit}>
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
                className="rounded-lg border border-destructive/20 bg-destructive/5 p-3 text-sm text-destructive"
              >
                {error}
              </p>
            )}
            <Button className="w-full" type="submit" disabled={isSubmitting}>
              {isSubmitting ? "جارٍ تسجيل الدخول..." : "تسجيل الدخول"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
