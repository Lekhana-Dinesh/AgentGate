import { CurrentUser } from "@/types/api";

const TOKEN_KEY = "agentgate_access_token";
const USER_KEY = "agentgate_current_user";
const SESSION_MODE_KEY = "agentgate_session_mode";
const CSRF_TOKEN_KEY = "agentgate_csrf_token";

export const COOKIE_SESSION_TOKEN = "__agentgate_cookie_session__";

function hasWindow(): boolean {
  return typeof window !== "undefined";
}

export function isCookieSessionToken(token: string | null | undefined): boolean {
  return token === COOKIE_SESSION_TOKEN;
}

export function getStoredToken(): string | null {
  if (!hasWindow()) {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (hasWindow()) {
    window.localStorage.setItem(TOKEN_KEY, token);
    window.localStorage.setItem(SESSION_MODE_KEY, "token");
  }
}

export function clearStoredToken(): void {
  if (hasWindow()) {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

export function getStoredUser(): CurrentUser | null {
  if (!hasWindow()) {
    return null;
  }
  const raw = window.localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as CurrentUser) : null;
}

export function setStoredUser(user: CurrentUser): void {
  if (hasWindow()) {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function clearStoredUser(): void {
  if (hasWindow()) {
    window.localStorage.removeItem(USER_KEY);
  }
}

export function getStoredSessionMode(): "token" | "cookie" | null {
  if (!hasWindow()) {
    return null;
  }
  const value = window.localStorage.getItem(SESSION_MODE_KEY);
  return value === "token" || value === "cookie" ? value : null;
}

export function setStoredSessionMode(mode: "token" | "cookie"): void {
  if (hasWindow()) {
    window.localStorage.setItem(SESSION_MODE_KEY, mode);
  }
}

export function clearStoredSessionMode(): void {
  if (hasWindow()) {
    window.localStorage.removeItem(SESSION_MODE_KEY);
  }
}

export function getStoredCsrfToken(): string | null {
  if (!hasWindow()) {
    return null;
  }
  return window.sessionStorage.getItem(CSRF_TOKEN_KEY);
}

export function setStoredCsrfToken(token: string): void {
  if (hasWindow()) {
    window.sessionStorage.setItem(CSRF_TOKEN_KEY, token);
  }
}

export function clearStoredCsrfToken(): void {
  if (hasWindow()) {
    window.sessionStorage.removeItem(CSRF_TOKEN_KEY);
  }
}

export function activateCookieSession(csrfToken?: string | null): void {
  clearStoredToken();
  setStoredSessionMode("cookie");
  if (csrfToken) {
    setStoredCsrfToken(csrfToken);
  } else {
    clearStoredCsrfToken();
  }
}

export function clearSession(): void {
  clearStoredToken();
  clearStoredUser();
  clearStoredSessionMode();
  clearStoredCsrfToken();
}
