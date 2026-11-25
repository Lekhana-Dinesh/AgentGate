"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useRef } from "react";

import { cn } from "@/lib/utils";

const groups = [
  { label: "Workspace", items: [
    { href: "/", label: "Overview" },
    { href: "/demo", label: "Demo" },
    { href: "/onboarding", label: "Onboarding" },
  ] },
  { label: "Governance", items: [
    { href: "/approvals", label: "Approvals" },
    { href: "/agents", label: "Agents" },
    { href: "/tools", label: "Tools" },
    { href: "/policies", label: "Policies" },
    { href: "/tool-calls", label: "Tool Calls" },
    { href: "/traces", label: "Traces" },
    { href: "/audit", label: "Audit" },
  ] },
  { label: "Operations", items: [
    { href: "/jobs", label: "Jobs" },
    { href: "/scheduled-tasks", label: "Scheduled Tasks" },
    { href: "/audit-integrity", label: "Audit Integrity" },
    { href: "/audit-exports", label: "Audit Exports" },
    { href: "/retention", label: "Retention" },
    { href: "/users", label: "Users & Identity" },
    { href: "/settings", label: "Settings" },
  ] },
];

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Primary" className="grid gap-4">
      {groups.map(({ label, items }) => (
        <div key={label}>
          <p className="px-3 pb-1 text-xs font-semibold uppercase tracking-wider text-slate-500">{label}</p>
          <ul className="grid gap-1">
            {items.map(({ href, label: itemLabel }) => {
              const active = pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
              return (
                <li key={href}>
                  <Link href={href} onClick={onNavigate} aria-current={active ? "page" : undefined}
                    className={cn(
                      "block rounded-xl px-3 py-2 text-sm font-medium transition",
                      active ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-white/80",
                    )}>
                    {itemLabel}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

export function Sidebar() {
  return (
    <aside className="glass-panel sticky top-6 hidden max-h-[calc(100dvh-3rem)] w-60 shrink-0 overflow-y-auto overscroll-contain rounded-3xl p-4 shadow-panel lg:block">
      <p className="mb-5 rounded-2xl bg-slate-950 px-4 py-4 text-xl font-semibold text-white">AgentGate</p>
      <Navigation />
    </aside>
  );
}

export function MobileNavigation() {
  const disclosure = useRef<HTMLDetailsElement>(null);
  const summary = useRef<HTMLElement>(null);

  function close() {
    if (disclosure.current?.open) {
      disclosure.current.open = false;
      summary.current?.focus();
    }
  }

  return (
    <details ref={disclosure} className="glass-panel rounded-2xl px-4 lg:hidden"
      onKeyDown={(event) => {
        if (event.key === "Escape") close();
      }}>
      <summary ref={summary} className="cursor-pointer py-3 text-sm font-semibold text-slate-950">
        AgentGate menu
      </summary>
      <div className="max-h-[55dvh] overflow-y-auto overscroll-contain pb-4">
        <Navigation onNavigate={close} />
      </div>
    </details>
  );
}
