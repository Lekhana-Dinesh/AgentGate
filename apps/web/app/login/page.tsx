"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { useSession } from "@/hooks/use-session";
import { apiClient } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { OIDCConfigStatus } from "@/types/api";

function formatSSOError(code: string | null): string | null {
  switch (code) {
    case "oidc_invalid_state":
      return "The SSO session could not be validated. Start the sign-in flow again.";
    case "oidc_email_domain_forbidden":
      return "Your email domain is not allowed for this tenant's SSO configuration.";
    case "oidc_provider_disabled":
    case "oidc_tenant_not_found":
      return "SSO is not enabled for this tenant.";
    case "oidc_code_exchange_failed":
    case "oidc_token_invalid":
    case "oidc_invalid_nonce":
      return "The identity provider response could not be validated.";
    case "inactive_user":
      return "Your account is inactive in AgentGate.";
    default:
      return code ? "SSO sign-in could not be completed." : null;
  }
}

export default function LoginPage() {
  const { token, login, completeLoginWithAccessToken } = useSession();
  const [email, setEmail] = useState("admin@demo.agentgate.local");
  const [password, setPassword] = useState("AgentGate123!");
  const [tenantSlug, setTenantSlug] = useState("demo-agentgate");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [sessionExpired, setSessionExpired] = useState(false);
  const [ssoStatus, setSSOStatus] = useState<OIDCConfigStatus | null>(null);
  const [ssoLoading, setSSOLoading] = useState(false);
  const [ssoProcessing, setSSOProcessing] = useState(false);
  const router = useRouter();

  useEffect(() => {
    if (token) {
      router.push("/");
    }
  }, [token, router]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);
    setSessionExpired(params.get("reason") === "session-expired");
    const redirectedTenantSlug = params.get("tenant_slug");
    if (redirectedTenantSlug) {
      setTenantSlug(redirectedTenantSlug);
    }
    const ssoError = formatSSOError(params.get("sso_error"));
    if (ssoError) {
      setError(ssoError);
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined" || token) {
      return;
    }
    const hashParams = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const ticket = hashParams.get("oidc_ticket");
    if (!ticket) {
      return;
    }
    const oidcTicket = ticket;

    let cancelled = false;

    async function exchangeTicket() {
      setSSOProcessing(true);
      setError(null);
      try {
        const tokenResponse = await apiClient.exchangeOIDCTicket(oidcTicket);
        if (!cancelled) {
          const params = new URLSearchParams(window.location.search);
          const redirectedTenantSlug = params.get("tenant_slug") || tenantSlug;
          window.history.replaceState(
            {},
            document.title,
            `/login?tenant_slug=${encodeURIComponent(redirectedTenantSlug)}`,
          );
          await completeLoginWithAccessToken(tokenResponse.access_token);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "SSO sign-in failed.");
        }
      } finally {
        if (!cancelled) {
          setSSOProcessing(false);
        }
      }
    }

    void exchangeTicket();
    return () => {
      cancelled = true;
    };
  }, [completeLoginWithAccessToken, tenantSlug, token]);

  useEffect(() => {
    if (!tenantSlug.trim()) {
      setSSOStatus(null);
      setSSOLoading(false);
      return;
    }

    let cancelled = false;

    async function loadStatus() {
      setSSOLoading(true);
      try {
        const status = await apiClient.getOIDCConfigStatus(tenantSlug.trim());
        if (!cancelled) {
          setSSOStatus(status);
        }
      } catch {
        if (!cancelled) {
          setSSOStatus(null);
        }
      } finally {
        if (!cancelled) {
          setSSOLoading(false);
        }
      }
    }

    void loadStatus();
    return () => {
      cancelled = true;
    };
  }, [tenantSlug]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login({ email, password, tenant_slug: tenantSlug || undefined });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  }

  function handleSSOLogin() {
    if (!ssoStatus?.configured || !ssoStatus.login_url) {
      return;
    }
    window.location.assign(ssoStatus.login_url);
  }

  const ssoButtonLabel = useMemo(() => {
    if (ssoProcessing) {
      return "Completing SSO...";
    }
    if (ssoStatus?.provider_name) {
      return `Continue with ${ssoStatus.provider_name}`;
    }
    return "Continue with SSO";
  }, [ssoProcessing, ssoStatus?.provider_name]);

  return (
    <div className="page-shell app-grid flex min-h-screen items-center justify-center px-4 py-8">
      <div className="grid w-full max-w-6xl gap-6 lg:grid-cols-[1.2fr_0.8fr]">
        <Card className="relative overflow-hidden bg-slate-950 text-white">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(15,118,110,0.35),transparent_30%),radial-gradient(circle_at_bottom_right,rgba(180,83,9,0.28),transparent_25%)]" />
          <div className="relative">
            <p className="text-xs uppercase tracking-[0.28em] text-slate-400">Enterprise Runtime Control Plane</p>
            <h1 className="mt-5 max-w-2xl text-5xl font-semibold tracking-tight">
              Govern agent tool execution with identity, intent, policy, risk, approval, and audit in one place.
            </h1>
            <p className="mt-5 max-w-2xl text-base text-slate-300">
              AgentGate sits between enterprise AI agents and enterprise tools, intercepting each action at runtime before it is allowed, blocked, redacted, or routed to a human reviewer.
            </p>
            <div className="mt-8 grid gap-4 md:grid-cols-3">
              {[
                "Tenant-aware agent registry",
                "Deterministic policy and risk scoring",
                "Replayable traces and audit logs",
              ].map((item) => (
                <div key={item} className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-200">
                  {item}
                </div>
              ))}
            </div>
          </div>
        </Card>

        <Card>
          <p className="text-xs uppercase tracking-[0.24em] text-slate-500">Operator Login</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">Access AgentGate</h2>
          <p className="mt-2 text-sm text-slate-500">
            Use the seeded demo tenant or your local bootstrap account.
          </p>
          {sessionExpired ? (
            <p className="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Your session expired or was invalidated. Sign in again to continue.
            </p>
          ) : null}

          <form className="mt-8 space-y-4" onSubmit={handleSubmit}>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Tenant slug</label>
              <Input value={tenantSlug} onChange={(event) => setTenantSlug(event.target.value)} />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Email</label>
              <Input value={email} onChange={(event) => setEmail(event.target.value)} type="email" />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-slate-700">Password</label>
              <Input
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                type="password"
              />
            </div>
            {error ? <p className="text-sm text-rose-700">{error}</p> : null}
            <Button className="w-full" disabled={loading || ssoProcessing} type="submit">
              {loading ? "Signing in..." : "Sign in"}
            </Button>
          </form>

          <div className="mt-5 rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <p className="text-xs uppercase tracking-[0.18em] text-slate-500">Enterprise SSO</p>
            <p className="mt-2 text-sm text-slate-600">
              {ssoLoading
                ? "Checking tenant SSO configuration..."
                : ssoStatus?.configured
                  ? "This tenant has an enabled OIDC provider."
                  : "SSO is optional and only appears when the tenant has an enabled OIDC provider."}
            </p>
            <Button
              className="mt-4 w-full"
              variant="secondary"
              disabled={!ssoStatus?.configured || ssoProcessing}
              type="button"
              onClick={handleSSOLogin}
            >
              {ssoButtonLabel}
            </Button>
            {ssoStatus?.reason === "misconfigured" ? (
              <p className="mt-3 text-xs text-amber-700">
                This tenant&apos;s SSO configuration is present but not ready for login.
              </p>
            ) : null}
          </div>

          <div className="mt-8 rounded-2xl bg-slate-50 p-4 text-sm text-slate-600">
            <p className="font-semibold text-slate-800">Seeded demo access</p>
            <p className="mt-2">
              Admin: <code>admin@demo.agentgate.local</code> / <code>AgentGate123!</code>
            </p>
            <p className="mt-1">
              Reviewer: <code>reviewer@demo.agentgate.local</code> / <code>AgentGate123!</code>
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
