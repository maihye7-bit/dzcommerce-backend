import {
  type PropsWithChildren,
  useEffect,
  useState,
} from "react";
import { subscribeToToasts, type ToastPayload } from "@/lib/toast";

interface ActiveToast extends ToastPayload {
  id: number;
}

export function ToastProvider({ children }: PropsWithChildren) {
  const [toasts, setToasts] = useState<ActiveToast[]>([]);

  useEffect(
    () =>
      subscribeToToasts((toast) => {
        const id = Date.now() + Math.random();
        setToasts((current) => [...current, { ...toast, id }]);
        window.setTimeout(
          () => setToasts((current) => current.filter((item) => item.id !== id)),
          4500,
        );
      }),
    [],
  );

  return (
    <>
      {children}
      <div
        aria-live="polite"
        className="fixed left-4 top-4 z-[100] flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`rounded-lg border px-4 py-3 text-sm shadow-lg ${
              toast.kind === "error"
                ? "border-destructive/30 bg-destructive text-white"
                : "border-emerald-700 bg-emerald-700 text-white"
            }`}
            role={toast.kind === "error" ? "alert" : "status"}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </>
  );
}
