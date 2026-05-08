"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiClient } from "@/lib/api";
import {
  activateCookieSession,
  clearSession,
  COOKIE_SESSION_TOKEN,
  getStoredSessionMode,
  getStoredToken,
  getStoredUser,
  setStoredCsrfToken,
  setStoredToken,
  setStoredUser,
} from "@/lib/session";
import type { CurrentUser, LoginPayload, TokenResponse } from "@/types/api";

async function resolveCookieSession(): Promise<CurrentUser | null> {
  try {
    const currentUser = await apiClient.getCurrentUser(COOKIE_SESSION_TOKEN);
    const csrfResponse = await apiClient.getCsrfToken();
    activateCookieSession(csrfResponse.csrf_token);
    return currentUser;
  } catch {
    return null;
  }
}

export function useSession() {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;

    async function hydrateSession() {
      const storedToken = getStoredToken();
      const storedUser = getStoredUser();
      if (storedToken) {
        if (storedUser) {
          if (!cancelled) {
            setTokenState(storedToken);
            setUserState(storedUser);
            setLoading(false);
          }
          return;
        }
        try {
          const currentUser = await apiClient.getCurrentUser(storedToken);
          if (!cancelled) {
            setStoredUser(currentUser);
            setTokenState(storedToken);
            setUserState(currentUser);
            setLoading(false);
          }
        } catch {
          if (!cancelled) {
            clearSession();
            setTokenState(null);
            setUserState(null);
            setLoading(false);
          }
        }
        return;
      }

      const cookieUser = await resolveCookieSession();
      if (cancelled) {
        return;
      }
      if (cookieUser) {
        setStoredUser(cookieUser);
        setTokenState(COOKIE_SESSION_TOKEN);
        setUserState(cookieUser);
      } else {
        if (getStoredSessionMode() === "cookie" || storedUser) {
          clearSession();
        }
        setTokenState(null);
        setUserState(null);
      }
      setLoading(false);
    }

    void hydrateSession();
    return () => {
      cancelled = true;
    };
  }, []);

  async function completeLogin(tokenResponse: TokenResponse) {
    if (tokenResponse.session_mode === "cookie") {
      activateCookieSession(tokenResponse.csrf_token);
      const currentUser = await apiClient.getCurrentUser(COOKIE_SESSION_TOKEN);
      if (tokenResponse.csrf_token) {
        setStoredCsrfToken(tokenResponse.csrf_token);
      }
      setStoredUser(currentUser);
      setTokenState(COOKIE_SESSION_TOKEN);
      setUserState(currentUser);
      router.push("/");
      return;
    }

    if (!tokenResponse.access_token) {
      throw new Error("Access token missing from login response.");
    }
    setStoredToken(tokenResponse.access_token);
    try {
      const currentUser = await apiClient.getCurrentUser(tokenResponse.access_token);
      setStoredUser(currentUser);
      setTokenState(tokenResponse.access_token);
      setUserState(currentUser);
      router.push("/");
    } catch (error) {
      clearSession();
      throw error;
    }
  }

  async function login(payload: LoginPayload) {
    const tokenResponse = await apiClient.login(payload);
    await completeLogin(tokenResponse);
  }

  async function logout() {
    const currentToken = token;
    try {
      if (currentToken) {
        await apiClient.logout(currentToken);
      } else {
        await apiClient.logout();
      }
    } catch {
      // Best-effort logout keeps local state safe even if the cookie has already expired.
    } finally {
      clearSession();
      setTokenState(null);
      setUserState(null);
      router.push("/login");
    }
  }

  return {
    token,
    user,
    loading,
    login,
    completeLogin,
    logout,
    setToken: setStoredToken,
    setUser: setStoredUser,
  };
}
