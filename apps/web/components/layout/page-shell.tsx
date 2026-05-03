"use client";

import { ReactNode, useEffect } from "react";
import { useRouter } from "next/navigation";

import { Sidebar } from "@/components/layout/sidebar";
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
      <div className="page-shell app-grid flex items-center justify-center text-slate-500">
        Loading workspace...
      </div>
    );
  }

  if (!token || !user) {
    return null;
  }

  return (
    <div className="page-shell app-grid px-4 py-6 lg:px-6">
      <div className="mx-auto flex w-full max-w-[1600px] gap-6">
        <Sidebar />
        <main className="min-w-0 flex-1">
          <div className="glass-panel mb-6 rounded-[2rem] px-6 py-5 shadow-panel">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
                  {user.role.replace("_", " ")} / {user.email}
                </p>
                <h2 className="mt-2 text-3xl font-semibold tracking-tight text-slate-950">
                  {title}
                </h2>
                <p className="mt-2 max-w-3xl text-sm text-slate-500">{description}</p>
              </div>
              <div className="flex items-center gap-3">
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
