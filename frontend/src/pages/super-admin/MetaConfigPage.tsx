import { useEffect, useState, type FormEvent } from "react";
import { ErrorMessage } from "@/components/ErrorMessage";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { fetchMetaAppConfig, updateMetaAppConfig } from "@/lib/meta-api";

export interface MetaAppConfig {
  appId: string;
  verificationToken: string;
}

export function MetaConfigPage() {
  const [config, setConfig] = useState<MetaAppConfig>({ appId: "", verificationToken: "" });
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    setIsLoading(true);
    try {
      const fetchedConfig = await fetchMetaAppConfig();
      setConfig(fetchedConfig);
    } catch (err) {
      setError("Failed to load Meta configuration");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    updateConfig();
  }

  const updateConfig = async () => {
    setIsLoading(true);
    setError(null);
    try {
      await updateMetaAppConfig(config);
      setError(null);
      // Optionally show a success toast
    } catch (err) {
      setError("Failed to update Meta configuration");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="max-w-4xl space-y-6" dir="rtl">
      <div>
        <p className="text-sm font-medium text-primary">إعدادات الفائق administrator</p>
        <h1 className="mt-2 text-3xl font-bold">تكوين تطبيق Meta (Facebook)</h1>
      </div>
      {error && (
        <ErrorMessage error={error} onRetry={loadConfig} />
      )}
      {isLoading && <LoadingSpinner label="جارٍ تحميل الإعدادات..." />}
      {!isLoading && !error && (
        <Card>
          <CardHeader>
            <CardTitle>إعدادات تطبيق Meta</CardTitle>
          </Header>
          <CardContent className="space-y-6">
            <form className="space-y-4 border-t pt-5" onSubmit={handleSubmit}>
              <div className="space-y-2">
                <Label htmlFor="meta-app-id">معرف تطبيق Meta (App ID)</Label>
                <Input
                  id="meta-app-id"
                  maxLength={255}
                  minLength={1}
                  value={config.appId}
                  onChange={(event) => setConfig({ ...config, appId: event.target.value })}
                  required
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="meta-verification-token">رمز التحقق من Meta (Verification Token)</Label>
                <Input
                  id="meta-verification-token"
                  maxLength={255}
                  minLength={1}
                  value={config.verificationToken}
                  onChange={(event) => setConfig({ ...config, verificationToken: event.target.value })}
                  required
                />
              </div>
              <Button
                type="submit"
                disabled={isLoading}
              >
                {isLoading ? "جارٍ الحفظ..." : "حفظ التغييرات"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}
    </section>
  );
}