import { CurrentUser } from "@/types/api";

const TOKEN_KEY = "agentgate_access_token";
const USER_KEY = "agentgate_current_user";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") {
    return null;
  }
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(TOKEN_KEY, token);
  }
}

export function clearStoredToken(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(TOKEN_KEY);
  }
}

export function getStoredUser(): CurrentUser | null {
  if (typeof window === "undefined") {
    return null;
  }
  const raw = window.localStorage.getItem(USER_KEY);
  return raw ? (JSON.parse(raw) as CurrentUser) : null;
}

export function setStoredUser(user: CurrentUser): void {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  }
}

export function clearStoredUser(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(USER_KEY);
  }
}

export function clearSession(): void {
  clearStoredToken();
  clearStoredUser();
}

