"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import {
  ACTIVE_RUN_STATUSES,
  isRunStatusPollTimeout,
  mergeRunProgressSnapshots,
  pickProgress,
  PREPARATION_STATUS_POLL_MS,
  RUN_STATUS_POLL_MS,
  RUN_STATUS_REQUEST_TIMEOUT_MS,
  type RunProgressSnapshot,
} from "@/lib/runStatusPoll";

export {
  ACTIVE_RUN_STATUSES,
  RUN_STATUS_POLL_MS,
  PREPARATION_STATUS_POLL_MS,
  RUN_STATUS_REQUEST_TIMEOUT_MS,
} from "@/lib/runStatusPoll";
export type { RunProgressSnapshot, PreparationProgressDetail } from "@/lib/runStatusPoll";

/**
 * Poll ``GET /extraction/runs/{id}/status`` every 1s while preparing, 2s while running.
 * Keeps the last good snapshot when a poll fails; never clears progress on timeout.
 */
export function useRunPreparationPoll(runId: string | null): {
  progress: RunProgressSnapshot | null;
  pollError: string | null;
  pollBusy: boolean;
  lastPolledAt: number | null;
  pollAttempt: number;
} {
  const [progress, setProgress] = useState<RunProgressSnapshot | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [pollBusy, setPollBusy] = useState(false);
  const [lastPolledAt, setLastPolledAt] = useState<number | null>(null);
  const [pollAttempt, setPollAttempt] = useState(0);
  const statusRef = useRef<string | null>(null);
  const consecutiveErrorsRef = useRef(0);

  const fetchOnce = useCallback(async () => {
    if (!runId) return;
    setPollAttempt((n) => n + 1);
    try {
      const raw = await api.get<Record<string, unknown>>(
        `/api/v1/extraction/runs/${runId}/status`,
        { timeoutMs: RUN_STATUS_REQUEST_TIMEOUT_MS },
      );
      const snap = pickProgress(raw);
      setProgress((prev) => {
        const merged = mergeRunProgressSnapshots(prev, snap);
        statusRef.current = merged.status;
        return merged;
      });
      setPollError(null);
      setPollBusy(false);
      consecutiveErrorsRef.current = 0;
      setLastPolledAt(Date.now());
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      consecutiveErrorsRef.current += 1;
      const timedOut = isRunStatusPollTimeout(msg);
      setPollBusy(timedOut);
      setPollError(
        timedOut
          ? "Status poll timed out — extraction may still be running on the server (API busy)."
          : msg,
      );
      setLastPolledAt(Date.now());
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setProgress(null);
      setPollError(null);
      setPollBusy(false);
      setLastPolledAt(null);
      setPollAttempt(0);
      statusRef.current = null;
      consecutiveErrorsRef.current = 0;
      return;
    }

    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout> | null = null;

    const pollDelayMs = () => {
      const status = statusRef.current;
      return status === "preparing" || status === "queued"
        ? PREPARATION_STATUS_POLL_MS
        : RUN_STATUS_POLL_MS;
    };

    const scheduleNext = () => {
      if (cancelled) return;
      timeoutId = setTimeout(() => {
        void (async () => {
          if (cancelled) return;
          await fetchOnce();
          const status = statusRef.current;
          if (status && !ACTIVE_RUN_STATUSES.has(status)) return;
          scheduleNext();
        })();
      }, pollDelayMs());
    };

    void fetchOnce().then(() => {
      if (!cancelled) scheduleNext();
    });

    return () => {
      cancelled = true;
      if (timeoutId) clearTimeout(timeoutId);
    };
  }, [runId, fetchOnce]);

  return { progress, pollError, pollBusy, lastPolledAt, pollAttempt };
}
