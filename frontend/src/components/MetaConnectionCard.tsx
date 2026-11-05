import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStoreMetaConnection } from "@/hooks/useStoreMetaConnection";

export function MetaConnectionCard({ storeId }: { storeId: string | null }) {
  const [pageName, setPageName] = useState("");
  const [pageId, setPageId] = useState("");
  const [pageAccessToken, setPageAccessToken] = useState("");
  const {
    data: connection,
    isLoading,
    isError,
    connect,
    disconnect,
    isConnecting,
    isDisconnecting
  } = useStoreMetaConnection(storeId);

  useEffect(() => {
    setPageName(connection?.pageName ?? "");
    setPageId(connection?.pageId ?? "");
  }, [connection?.pageId, connection?.pageName]);

  async function submitConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!storeId) return;
    try {
      await connect(storeId, { pageName, pageId, pageAccessToken });
      setPageAccessToken("");
    } catch {
      // The mutation reports a sanitized error to the user.
    }
  }

  return (
    <Card className="space-y-4">
      <CardHeader>
        <CardTitle>ربط صفحة Facebook</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <p>جارٍ التحقق من الحالة...</p>}
        {isError && (
          <p className="text-destructive">خطأ في تحميل حالة الاتصال. يرجى المحاولة مرة أخرى.</p>
        )}
        {!isLoading && !isError && connection && (
          <>
            <p className="mb-3 text-sm text-muted-foreground">
              إذا كان لديك حساب Facebook شخصي فقط، أنشئ صفحة تجارية أولاً ثم اربطها هنا.
            </p>
            <p className="mb-3 text-sm" role="status" aria-live="polite">
              {isConnecting
                ? "جارٍ التحقق من الصفحة والصلاحيات..."
                : connection.connected && connection.verified
                  ? `تم التحقق من الصفحة، وهي متصلة: ${connection.pageName}`
                  : "غير مكتمل: أدخل بيانات صفحة Facebook للتحقق والربط."}
            </p>
            <form className="space-y-3" onSubmit={submitConnection}>
              <label className="block space-y-1">
                <span>اسم صفحة Facebook</span>
                <input
                  className="w-full rounded border px-3 py-2"
                  value={pageName}
                  onChange={(event) => setPageName(event.target.value)}
                  maxLength={255}
                  required
                  autoComplete="organization"
                />
              </label>
              <label className="block space-y-1">
                <span>Facebook Page ID</span>
                <input
                  className="w-full rounded border px-3 py-2"
                  value={pageId}
                  onChange={(event) => setPageId(event.target.value)}
                  maxLength={255}
                  required
                  dir="ltr"
                  autoComplete="off"
                />
              </label>
              <label className="block space-y-1">
                <span>Page Access Token</span>
                <input
                  className="w-full rounded border px-3 py-2"
                  type="password"
                  value={pageAccessToken}
                  onChange={(event) => setPageAccessToken(event.target.value)}
                  minLength={20}
                  maxLength={4096}
                  required
                  dir="ltr"
                  autoComplete="new-password"
                  placeholder="لن يتم عرض الرمز بعد حفظه"
                />
              </label>
              <div className="flex flex-wrap gap-2">
                <Button type="submit" disabled={isConnecting || !storeId}>
                  {isConnecting
                    ? "جارٍ التحقق والربط..."
                    : "التحقق من الصفحة وربطها"}
                </Button>
                {connection.connected && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => disconnect(storeId!)}
                    disabled={isDisconnecting}
                  >
                    {isDisconnecting ? "جارٍ القطع..." : "قطع الاتصال"}
                  </Button>
                )}
              </div>
            </form>
          </>
        )}
      </CardContent>
    </Card>
  );
}