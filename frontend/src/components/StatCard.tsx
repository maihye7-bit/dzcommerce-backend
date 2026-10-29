import type { ComponentType, SVGProps } from "react";
import { Card, CardContent } from "@/components/ui/card";

interface StatCardProps {
  title: string;
  value: string;
  change?: string;
  changeType?: "increase" | "decrease";
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  trend?: React.ReactNode;
}

export function StatCard({ title, value, change, changeType, icon: Icon, trend }: StatCardProps) {
  return (
    <Card className="glass glass-dark">
      <CardContent className="flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <span className="rounded-xl bg-primary/10 p-2 text-primary">
            <Icon className="size-5" aria-hidden="true" />
          </span>
        </div>
        <div className="flex items-end justify-between gap-4">
          <div className="flex-1 min-w-0">
            <p className="text-3xl font-bold tracking-tight truncate">{value}</p>
            {change && (
              <div className="flex items-center gap-1 mt-1">
                {changeType === "increase" ? (
                  <span className="flex items-center gap-0.5 text-sm font-medium text-green-600 dark:text-green-400">
                    <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <path d="M18 15l-6-6-6 6" />
                    </svg>
                    {change}
                  </span>
                ) : changeType === "decrease" ? (
                  <span className="flex items-center gap-0.5 text-sm font-medium text-red-600 dark:text-red-400">
                    <svg className="size-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <path d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                    </svg>
                    {change}
                  </span>
                ) : null}
              </div>
            )}
          </div>
          {trend && <div className="flex-shrink-0">{trend}</div>}
        </div>
      </CardContent>
    </Card>
  );
}