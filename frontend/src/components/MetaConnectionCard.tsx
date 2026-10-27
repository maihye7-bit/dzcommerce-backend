import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useStoreMetaConnection } from "@/hooks/useStoreMetaConnection";

export function MetaConnectionCard({ storeId }: { storeId: string | null }) {
  const {
    data: connection,
    isLoading,
    isError,
    connect,
    disconnect,
    isConnecting,
    isDisconnecting
  } = useStoreMetaConnection(storeId);

  return (
    <Card className="space-y-4">
      <CardHeader>
        <CardTitle>الاتصال بفيسبوك وإنستغرام</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <p>جارٍ التحقق من الحالة...</p>}
        {isError && (
          <p className="text-destructive">خطأ في تحميل حالة الاتصال. يرجى المحاولة مرة أخرى.</p>
        )}
        {!isLoading && !isError && connection && (
          <>
            {connection.connected ? (
              <>
                <p className="mb-2">
                  أنت متصل بصفحة: <strong className="font-medium">{connection.pageName}</strong>
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => disconnect(storeId!)}
                  disabled={isDisconnecting}
                >
                  {isDisconnecting ? "جارٍ القطع..." : "قطع الاتصال"}
                </Button>
              </>
            ) : (
              <>
                <p className="mb-2">
                  لم تقم بربط أي صفحة بعد. يمكنك ربط صفحة فيسبوك أو إنستغرام الخاصة بمتجرك لتلقي الرسائل والرد عليها عبر الشات.
                </p>
                <Button
                  variant="default"
                  size="sm"
                  onClick={() => connect(storeId!)}
                  disabled={isConnecting}
                >
                  {isConnecting ? "جارٍ الربط..." : "ربط صفحة الفيسبوك وإنستغرام"}
                </Button>
              </>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}