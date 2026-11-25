"use client";

import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";

import { MobileNavigation, Sidebar } from "@/components/layout/sidebar";
import { Button } from "@/components/ui/button";
import { useSession } from "@/hooks/use-session";

export function PageShell({
  title,
  description,
  children,
  actions,
}: {
  title: string;
  description: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  const { loading, token, user, logout } = useSession();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !token) {
      router.push("/login");
    }
  }, [loading, token, router]);

  if (loading) {
    return (
      <div role="status" className="page-shell app-grid flex items-center justify-center text-slate-500">
        Loading workspace...
      </div>
    );
  }

  if (!token || !user) {
    return null;
  }

  return (
    <div className="page-shell app-grid px-3 py-4 sm:px-4 lg:px-6 lg:py-6">
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-4 lg:flex-row lg:gap-6">
        <MobileNavigation />
        <Sidebar />
        <main className="min-w-0 flex-1">
          <div className="glass-panel mb-5 rounded-3xl px-4 py-4 shadow-panel sm:px-6 sm:py-5">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="break-words text-xs font-medium text-slate-600">
                  <span className="capitalize">{user.role.replaceAll("_", " ")}</span> · {user.email}
                </p>
                <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950 sm:text-3xl">
                  {title}
                </h1>
                <p className="mt-2 max-w-3xl text-sm text-slate-500">{description}</p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {actions}
                <Button variant="ghost" onClick={logout}>
                  Sign out
                </Button>
              </div>
            </div>
          </div>
          {children}
        </main>
      </div>
    </div>
  );
}
