"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type PaginatedResponse } from "@/lib/api-client";
import type { ExtractionRun } from "@/types/pipeline";

const REFRESH_MS = 10_000;

/** Count extraction runs that are queued or running (active pipeline agents). */
export function useActivePipelineAgents(): {
  count: number | null;
  loading: boolean;
  error: boolean;
} {
  const [count, setCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [running, queued] = await Promise.all([
        api.get<PaginatedResponse<ExtractionRun>>(
          "/api/v1/extraction/runs?status=running&limit=1",
        ),
        api.get<PaginatedResponse<ExtractionRun>>(
          "/api/v1/extraction/runs?status=queued&limit=1",
        ),
      ]);
      setCount((running.total_count ?? 0) + (queued.total_count ?? 0));
      setError(false);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const start = window.setTimeout(() => void refresh(), 600);
    const id = window.setInterval(() => void refresh(), REFRESH_MS);
    return () => {
      window.clearTimeout(start);
      clearInterval(id);
    };
  }, [refresh]);

  return { count, loading, error };
}
