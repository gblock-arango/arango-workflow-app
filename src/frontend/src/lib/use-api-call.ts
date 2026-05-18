"use client";

import { useState, useCallback } from "react";
import { ApiError } from "@/lib/api-client";

interface UseApiCallReturn<T> {
  execute: (...args: unknown[]) => Promise<T | undefined>;
  data: T | undefined;
  loading: boolean;
  error: string | null;
  reset: () => void;
}

/**
 * Generic hook for API calls with loading/error state management.
 *
 * Eliminates repeated try/catch/setLoading/setError boilerplate.
 *
 * @example
 * const { execute, data, loading, error } = useApiCall(
 *   () => api.get<MyData>("/api/v1/resource"),
 * );
 * // Call execute() in useEffect or onClick handlers
 */
export function useApiCall<T>(
  fn: (...args: unknown[]) => Promise<T>,
  opts?: { errorMessage?: string },
): UseApiCallReturn<T> {
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const execute = useCallback(
    async (...args: unknown[]): Promise<T | undefined> => {
      setLoading(true);
      setError(null);
      try {
        const result = await fn(...args);
        setData(result);
        return result;
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : (opts?.errorMessage ?? "Request failed");
        setError(message);
        return undefined;
      } finally {
        setLoading(false);
      }
    },
    [fn, opts?.errorMessage],
  );

  const reset = useCallback(() => {
    setData(undefined);
    setLoading(false);
    setError(null);
  }, []);

  return { execute, data, loading, error, reset };
}
