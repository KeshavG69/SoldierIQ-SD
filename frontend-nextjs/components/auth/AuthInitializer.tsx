"use client";

import { useEffect } from "react";
import { useAuthStore } from "@/lib/stores/authStore";

export default function AuthInitializer() {
  const initializeAuth = useAuthStore((state) => state.initializeAuth);

  useEffect(() => {
    initializeAuth();
  }, [initializeAuth]);

  return null;
}
