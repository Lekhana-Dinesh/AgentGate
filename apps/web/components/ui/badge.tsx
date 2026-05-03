import { ReactNode } from "react";

import { cn } from "@/lib/utils";

const toneMap: Record<string, string> = {
  active: "bg-emerald-50 text-emerald-700",
  suspended: "bg-amber-50 text-amber-700",
  revoked: "bg-rose-50 text-rose-700",
  low: "bg-slate-100 text-slate-700",
  medium: "bg-sky-100 text-sky-700",
  high: "bg-amber-100 text-amber-800",
  critical: "bg-rose-100 text-rose-800",
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-800",
  blocked: "bg-rose-100 text-rose-800",
  executed: "bg-emerald-100 text-emerald-800",
  queued: "bg-sky-100 text-sky-800",
  running: "bg-cyan-100 text-cyan-800",
  succeeded: "bg-emerald-100 text-emerald-800",
  retry_exhausted: "bg-rose-100 text-rose-800",
  cancelled: "bg-slate-200 text-slate-700",
  sent: "bg-emerald-100 text-emerald-800",
  failed: "bg-rose-100 text-rose-800",
  enabled: "bg-emerald-100 text-emerald-800",
  disabled: "bg-slate-200 text-slate-700",
  dry_run_succeeded: "bg-cyan-100 text-cyan-800",
  allow: "bg-emerald-100 text-emerald-800",
  block: "bg-rose-100 text-rose-800",
  require_approval: "bg-amber-100 text-amber-800",
  redact: "bg-cyan-100 text-cyan-800",
};

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return (
    <span
      className={cn(
        "inline-flex rounded-full px-3 py-1 text-xs font-semibold capitalize",
        toneMap[tone] || "bg-slate-100 text-slate-700",
      )}
    >
      {children}
    </span>
  );
}
