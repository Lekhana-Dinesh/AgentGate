import { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-xl px-4 py-2 text-sm font-semibold transition",
        variant === "primary" && "bg-ink text-white hover:bg-slate-900",
        variant === "secondary" && "bg-signal/10 text-signal hover:bg-signal/20",
        variant === "ghost" && "bg-white/60 text-slate-700 hover:bg-white",
        variant === "danger" && "bg-red-50 text-red-700 hover:bg-red-100",
        "disabled:cursor-not-allowed disabled:opacity-60",
        className,
      )}
      {...props}
    />
  );
}

