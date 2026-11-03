import type { ComponentType, ReactNode, SVGProps } from "react";
import { Card, CardContent } from "@/components/ui/card";

interface StatCardProps {
  title: string;
  value: string;
  change?: string;
  changeType?: "increase" | "decrease";
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  trend?: ReactNode;
}

export function StatCard({
  title,
  value,
  change,
  changeType,
  icon: Icon,
  trend,
}: StatCardProps) {
  return (
    <Card className="group relative overflow-hidden">
      <span
        aria-hidden="true"
        className="absolute inset-y-0 right-0 w-0.5 bg-primary/70 opacity-0 transition-opacity group-hover:opacity-100"
      />
      <CardContent className="flex min-h-36 flex-col gap-5 p-5 sm:p-6">
        <div className="flex items-start justify-between gap-4">
          <p className="min-w-0 text-sm font-medium leading-6 text-muted-foreground">
            {title}
          </p>
          <span className="grid size-11 shrink-0 place-items-center rounded-xl border border-primary/15 bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
            <Icon className="size-5" aria-hidden="true" />
          </span>
        </div>
        <p className="min-w-0 break-words text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
          {value}
        </p>
        {(change || trend) && (
          <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
            {change ? (
              <span
                className={
                  changeType === "increase"
                    ? "font-medium text-success"
                    : changeType === "decrease"
                      ? "font-medium text-destructive"
                      : ""
                }
              >
                {change}
              </span>
            ) : (
              <span />
            )}
            {trend}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
