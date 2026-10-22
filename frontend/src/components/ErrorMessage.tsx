import axios from "axios";
import { Button } from "@/components/ui/button";

interface ErrorMessageProps {
  error: unknown;
  onRetry: () => void;
}

function errorDescription(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const status = error.response?.status;
    if (status === 403 || status === 404) {
      return "لا تملك صلاحية عرض هذه البيانات أو أنها لم تعد متاحة.";
    }
    if (status && status >= 500) {
      return "حدث خطأ في الخادم. يرجى المحاولة مرة أخرى.";
    }
  }
  return "تعذر تحميل البيانات. تحقق من اتصالك وحاول مرة أخرى.";
}

export function ErrorMessage({ error, onRetry }: ErrorMessageProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/5 p-4"
    >
      <p className="text-sm text-destructive">{errorDescription(error)}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        إعادة المحاولة
      </Button>
    </div>
  );
}
