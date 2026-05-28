"use client";

import { useCallback, useEffect, useSyncExternalStore } from "react";
import { api } from "@/lib/api-client";
import { scheduleAfterInitialPaint } from "@/lib/scheduleAfterInitialPaint";

export interface LlmStatusPayload {
  ok: boolean;
  provider: string;
  embedding_model: string;
  extraction_model: string;
  openai_base_url?: string | null;
  openai_api_key_configured?: boolean;
  anthropic_api_key_configured?: boolean;
  summary?: string;
  hints?: string[];
  curl_examples?: string[];
  embedding: { ok: boolean; message: string; latency_ms?: number };
  extraction: { ok: boolean; message: string; latency_ms?: number };
}

export const LLM_STATUS_POLL_OK_MS = 10_000;
export const LLM_STATUS_POLL_FAIL_MS = 1_000;

type Snapshot = {
  status: LlmStatusPayload | null;
  /** True only when there is no cached status yet and a probe is in flight. */
  loading: boolean;
};

let cachedStatus: LlmStatusPayload | null = null;
let lastFetchedAt = 0;
let loading = false;
let inFlight = false;
let pollTimer: ReturnType<typeof setTimeout> | null = null;
let subscriberCount = 0;
let cancelDeferred: (() => void) | null = null;

const listeners = new Set<() => void>();

function emit() {
  listeners.forEach((l) => l());
}

function getSnapshot(): Snapshot {
  return {
    status: cachedStatus,
    loading: loading && cachedStatus === null,
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function clearPollTimer() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

function schedulePoll() {
  clearPollTimer();
  if (subscriberCount === 0) return;
  const delay =
    cachedStatus?.ok === true ? LLM_STATUS_POLL_OK_MS : LLM_STATUS_POLL_FAIL_MS;
  pollTimer = setTimeout(() => {
    void runProbe({ force: false });
  }, delay);
}

function errorPayload(message: string): LlmStatusPayload {
  return {
    ok: false,
    provider: "error",
    embedding_model: "",
    extraction_model: "",
    summary: `Probe request failed: ${message}`,
    hints: ["Check that the workflow-app API is reachable from the browser."],
    embedding: { ok: false, message },
    extraction: { ok: false, message: "Probe request failed" },
  };
}

async function runProbe(opts: { force: boolean }) {
  if (inFlight) return;
  inFlight = true;
  if (!cachedStatus) {
    loading = true;
    emit();
  }

  try {
    const qs = opts.force ? "?force=true" : "";
    cachedStatus = await api.get<LlmStatusPayload>(`/api/v1/system/llm-status${qs}`);
    lastFetchedAt = Date.now();
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    cachedStatus = errorPayload(msg);
    lastFetchedAt = Date.now();
  } finally {
    loading = false;
    inFlight = false;
    emit();
    schedulePoll();
  }
}

function cacheAgeMs(): number {
  return lastFetchedAt ? Date.now() - lastFetchedAt : Number.POSITIVE_INFINITY;
}

function shouldProbeNow(force: boolean): boolean {
  if (force) return true;
  if (!cachedStatus) return true;
  const maxAge = cachedStatus.ok ? LLM_STATUS_POLL_OK_MS : LLM_STATUS_POLL_FAIL_MS;
  return cacheAgeMs() >= maxAge;
}

function startPollingLoop() {
  cancelDeferred?.();
  cancelDeferred = scheduleAfterInitialPaint(() => {
    if (shouldProbeNow(false)) {
      void runProbe({ force: false });
    } else {
      const maxAge = cachedStatus?.ok ? LLM_STATUS_POLL_OK_MS : LLM_STATUS_POLL_FAIL_MS;
      const remaining = Math.max(0, maxAge - cacheAgeMs());
      clearPollTimer();
      pollTimer = setTimeout(() => void runProbe({ force: false }), remaining);
    }
  }, 0);
}

function stopPollingLoop() {
  cancelDeferred?.();
  cancelDeferred = null;
  clearPollTimer();
}

function ensureStoreActive() {
  subscriberCount += 1;
  if (subscriberCount === 1) {
    startPollingLoop();
  }
}

function releaseStore() {
  subscriberCount = Math.max(0, subscriberCount - 1);
  if (subscriberCount === 0) {
    stopPollingLoop();
  }
}

/**
 * Shared LLM connectivity probe — one in-flight request and one poll timer app-wide.
 * Cached status is shown immediately on navigation; re-probes every 10s when OK, 1s when not.
 */
export function useLlmConnectivityStatus(): {
  status: LlmStatusPayload | null;
  loading: boolean;
  refresh: (opts?: { force?: boolean }) => void;
} {
  const snapshot = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);

  useEffect(() => {
    ensureStoreActive();
    return releaseStore;
  }, []);

  const refresh = useCallback((opts?: { force?: boolean }) => {
    void runProbe({ force: opts?.force ?? true });
  }, []);

  return {
    status: snapshot.status,
    loading: snapshot.loading,
    refresh,
  };
}
