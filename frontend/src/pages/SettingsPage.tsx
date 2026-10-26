import { useEffect, useState, type FormEvent } from "react";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MetaConnectionCard } from "@/components/MetaConnectionCard";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import {
  useStoreProfile,
  useUpdateStoreProfile,
} from "@/hooks/useStoreProfile";

export function SettingsPage() {
  const {
    isOwner,
    error: storeError,
    refetch: refetchStore,
  } = useCurrentUser();
  const profileQuery = useStoreProfile();
  const updateMutation = useUpdateStoreProfile(profileQuery.storeId);
  const [name, setName] = useState("");

  useEffect(() => {
    if (profileQuery.data) setName(profileQuery.data.name);
  }, [profileQuery.data]);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateMutation.mutate({ name: name.trim() });
  }

  return (
    <section className="max-w-3xl space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">إدارة الحساب</p>
        <h1 className="mt-2 text-3xl font-bold">إعدادات المتجر</h1>
      </div>
      {storeError && (
        <ErrorMessage error={storeError} onRetry={() => void refetchStore()} />
      )}
      {profileQuery.isLoading && <LoadingSpinner />}
      {profileQuery.isError && (
        <ErrorMessage
          error={profileQuery.error}
          onRetry={() => void profileQuery.refetch()}
        />
      )}
      {profileQuery.data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>ملف المتجر</CardTitle>
            </CardHeader>
            <CardContent className="space-y-6">
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="store-id">معرّف المتجر</Label>
                  <Input id="store-id" value={profileQuery.data.id} readOnly />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="store-created-at">تاريخ الإنشاء</Label>
                  <Input
                    id="store-created-at"
                    value="غير متاح من API ملف المتجر"
                    readOnly
                  />
                </div>
              </div>
              <form className="space-y-4 border-t pt-5" onSubmit={handleSubmit}>
                <div className="space-y-2">
                  <Label htmlFor="store-name">اسم المتجر</Label>
                  <Input
                    id="store-name"
                    maxLength={255}
                    minLength={1}
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    readOnly={!isOwner}
                    required
                  />
                </div>
                {!isOwner && (
                  <p className="text-sm text-muted-foreground">
                    صلاحية القراءة فقط. يقتصر تعديل الملف على مالك المتجر.
                  </p>
                )}
                {isOwner && (
                  <Button
                    type="submit"
                    disabled={
                      updateMutation.isPending ||
                      !name.trim() ||
                      name.trim() === profileQuery.data.name
                    }
                  >
                    {updateMutation.isPending ? "جارٍ الحفظ..." : "حفظ التغييرات"}
                  </Button>
                )}
              </form>
            </CardContent>
          </Card>
          <MetaConnectionCard storeId={profileQuery.data.id} />
        </>
      )}
    </section>
  );
}
