import { ReactNode } from "react";

import { cn } from "@/lib/utils";

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cn("glass-panel rounded-3xl p-6 shadow-panel", className)}>{children}</div>;
}

