"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { api, ApiError } from "./api";

/** One click: a private, throwaway demo account (a copy of the showcase profile), then the dashboard. */
export function useStartDemo() {
  const router = useRouter();
  const qc = useQueryClient();
  const [loading, setLoading] = useState(false);
  const start = async () => {
    setLoading(true);
    try {
      await api.post("/auth/demo");
      qc.clear();
      router.replace("/dashboard");
      router.refresh();
    } catch (err) {
      toast.error("Couldn’t start the demo", { description: err instanceof ApiError ? err.message : "Please try again" });
      setLoading(false);
    }
  };
  return { start, loading };
}
