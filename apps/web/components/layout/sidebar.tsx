"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

const navItems = [
  { href: "/", label: "Overview" },
  { href: "/agents", label: "Agents" },
  { href: "/tool-calls", label: "Tool Calls" },
  { href: "/approvals", label: "Approvals" },
  { href: "/jobs", label: "Jobs" },
  { href: "/audit-exports", label: "Audit Exports" },
  { href: "/retention", label: "Retention" },
  { href: "/policies", label: "Policies" },
  { href: "/traces", label: "Traces" },
  { href: "/audit", label: "Audit" },
  { href: "/demo", label: "Demo" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="glass-panel sticky top-6 hidden h-[calc(100vh-3rem)] w-72 rounded-[2rem] p-6 shadow-panel lg:block">
      <div className="rounded-3xl bg-slate-950 px-5 py-5 text-white">
        <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Agent Runtime</p>
        <h1 className="mt-3 text-2xl font-semibold">AgentGate</h1>
        <p className="mt-2 text-sm text-slate-300">
          Runtime security and governance for enterprise AI agents.
        </p>
      </div>

      <nav className="mt-8 flex flex-col gap-2">
        {navItems.map((item) => {
          const active =
            item.href === "/"
              ? pathname === "/"
              : pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "rounded-2xl px-4 py-3 text-sm font-medium transition",
                active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-white/80",
              )}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
