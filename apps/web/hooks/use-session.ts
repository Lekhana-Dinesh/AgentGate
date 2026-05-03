"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { apiClient } from "@/lib/api";
import {
  clearSession,
  getStoredToken,
  getStoredUser,
  setStoredToken,
  setStoredUser,
} from "@/lib/session";
import type { CurrentUser, LoginPayload } from "@/types/api";

export function useSession() {
  const [token, setTokenState] = useState<string | null>(null);
  const [user, setUserState] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    setTokenState(getStoredToken());
    setUserState(getStoredUser());
    setLoading(false);
  }, []);

  async function completeLoginWithAccessToken(accessToken: string) {
    setStoredToken(accessToken);
    try {
      const currentUser = await apiClient.getCurrentUser(accessToken);
      setStoredUser(currentUser);
      setTokenState(accessToken);
      setUserState(currentUser);
      router.push("/");
    } catch (error) {
      clearSession();
      throw error;
    }
  }

  async function login(payload: LoginPayload) {
    const tokenResponse = await apiClient.login(payload);
    await completeLoginWithAccessToken(tokenResponse.access_token);
  }

  function logout() {
    clearSession();
    setTokenState(null);
    setUserState(null);
    router.push("/login");
  }

  return {
    token,
    user,
    loading,
    login,
    completeLoginWithAccessToken,
    logout,
    setToken: setStoredToken,
    setUser: setStoredUser,
  };
}
