import axios from "axios";

export type ToastKind = "success" | "error";

export interface ToastPayload {
  message: string;
  kind: ToastKind;
}

const TOAST_EVENT = "dzcommerce:toast";

export function showToast(message: string, kind: ToastKind = "success") {
  window.dispatchEvent(
    new CustomEvent<ToastPayload>(TOAST_EVENT, {
      detail: { message, kind },
    }),
  );
}

export function showMutationError(error: unknown, fallback: string) {
  if (!axios.isAxiosError(error)) {
    showToast(fallback, "error");
    return;
  }

  const status = error.response?.status;
  if (status === 403 || (status !== undefined && status >= 500)) return;

  const responseBody: unknown = error.response?.data;
  const detail =
    typeof responseBody === "object" &&
    responseBody !== null &&
    "detail" in responseBody &&
    typeof responseBody.detail === "string"
      ? responseBody.detail
      : fallback;
  showToast(detail, "error");
}

export function subscribeToToasts(
  listener: (toast: ToastPayload) => void,
): () => void {
  const handler = (event: Event) => {
    listener((event as CustomEvent<ToastPayload>).detail);
  };
  window.addEventListener(TOAST_EVENT, handler);
  return () => window.removeEventListener(TOAST_EVENT, handler);
}
