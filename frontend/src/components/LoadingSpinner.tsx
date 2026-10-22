interface LoadingSpinnerProps {
  label?: string;
}

export function LoadingSpinner({
  label = "جارٍ التحميل...",
}: LoadingSpinnerProps) {
  return (
    <div
      role="status"
      className="flex items-center justify-center gap-3 py-10 text-sm text-muted-foreground"
    >
      <span className="size-5 animate-spin rounded-full border-2 border-primary/25 border-t-primary" />
      {label}
    </div>
  );
}
