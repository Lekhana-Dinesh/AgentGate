import { ReactNode } from "react";

import { Card } from "@/components/ui/card";

export function StatCard({
  label,
  value,
  detail,
  accent,
}: {
  label: string;
  value: string | number;
  detail: string;
  accent: ReactNode;
}) {
  return (
    <Card className="relative overflow-hidden">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-signal via-slate-900 to-amber-600" />
      <div className="flex items-start justify-between gap-6">
        <div>
          <p className="text-sm text-slate-500">{label}</p>
          <p className="mt-3 text-4xl font-semibold tracking-tight text-slate-950">{value}</p>
          <p className="mt-2 text-sm text-slate-500">{detail}</p>
        </div>
        <div className="rounded-2xl bg-slate-900 px-3 py-2 text-xs font-semibold text-white">
          {accent}
        </div>
      </div>
    </Card>
  );
}

