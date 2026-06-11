"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type {
  StepStatus,
  StepStatusValue,
  WebSocketEvent,
  PipelineStep,
} from "@/types/pipeline";
import { PIPELINE_STEPS } from "@/types/pipeline";
import { backendUrl, getApiOrigin } from "@/lib/api-client";
import { getBasePath } from "@/lib/base-path";
import {
  RUN_STATUS_POLL_MS,
  RUN_STATUS_REQUEST_TIMEOUT_MS,
} from "@/lib/runStatusPoll";

interface UseExtractionSocketReturn {
  steps: Map<string, StepStatus>;
  isConnected: boolean;
  error: string | null;
}

const BACKEND_TO_FRONTEND_STEP: Record<string, PipelineStep> = {
  prepare_arango: "prepare_arango",
  strategy_selector: "strategy_selector",
  extractor: "extraction_agent",
  consistency_checker: "consistency_checker",
  quality_judge: "quality_judge",
  er_agent: "entity_resolution_agent",
  filter: "pre_curation_filter",
  finalize_graph: "finalize_graph",
  belief_revision: "quality_judge",
};

function buildInitialSteps(): Map<string, StepStatus> {
  const map = new Map<string, StepStatus>();
  for (const step of PIPELINE_STEPS) {
    map.set(step, { status: "pending" });
  }
  return map;
}

function toFrontendStep(backendStep: string): PipelineStep | string {
  return BACKEND_TO_FRONTEND_STEP[backendStep] ?? backendStep;
}

function applyCurrentStepFallback(
  map: Map<string, StepStatus>,
  currentStep: string | null | undefined,
): void {
  if (!currentStep) return;
  const frontendStep = toFrontendStep(currentStep);
  const idx = PIPELINE_STEPS.indexOf(frontendStep as PipelineStep);
  if (idx < 0) return;
  for (let i = 0; i < PIPELINE_STEPS.length; i++) {
    const step = PIPELINE_STEPS[i];
    if (i < idx) {
      map.set(step, { status: "completed" });
    } else if (i === idx) {
      map.set(step, { ...(map.get(step) ?? { status: "pending" }), status: "running" });
    } else {
      map.set(step, { status: "pending" });
    }
  }
}

/**
 * Build the WebSocket URL for an extraction run.
 */
export function resolveWsUrl(runId: string): string {
  if (typeof window === "undefined") return "";
  const wsBase = getApiOrigin().replace(/^http/, "ws");
  const basePath = getBasePath();
  const token = localStorage.getItem("aoe_auth_token") ?? "";
  const sep = token ? "?" : "";
  return `${wsBase}${basePath}/ws/extraction/${runId}${sep}${token ? `token=${encodeURIComponent(token)}` : ""}`;
}

async function fetchStepsFromRest(
  runId: string,
): Promise<Map<string, StepStatus> | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RUN_STATUS_REQUEST_TIMEOUT_MS);
    const res = await fetch(backendUrl(`/api/v1/extraction/runs/${runId}/status`), {
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const run = await res.json();

    const runStatus: string = run?.status ?? "unknown";
    const isRunning =
      runStatus === "running" ||
      runStatus === "preparing" ||
      runStatus === "queued" ||
      runStatus === "paused";

    const stepLogs: {
      step: string;
      status: string;
      started_at?: number;
      completed_at?: number;
      error?: string | null;
      metadata?: Record<string, unknown>;
      tokens?: Record<string, unknown>;
    }[] = run?.stats?.step_logs ?? [];

    if (stepLogs.length === 0 && !isRunning) return null;

    const map = buildInitialSteps();
    const completedFrontendSteps = new Set<string>();

    for (const log of stepLogs) {
      const frontendStep = String(toFrontendStep(log.step));
      if (!map.has(frontendStep)) continue;

      let status: StepStatusValue = "pending";
      if (log.status === "completed") status = "completed";
      else if (log.status === "failed") status = "failed";
      else if (log.status === "running") status = "running";
      else if (log.status === "skipped") status = "completed";

      if (status === "completed" || status === "failed") {
        completedFrontendSteps.add(frontendStep);
      }

      map.set(frontendStep, {
        status,
        startedAt: log.started_at
          ? new Date(log.started_at * 1000).toISOString()
          : undefined,
        completedAt: log.completed_at
          ? new Date(log.completed_at * 1000).toISOString()
          : undefined,
        error: log.error ?? undefined,
        data: { ...log.metadata, ...log.tokens },
      });
    }

    if (isRunning) {
      const currentStep =
        run?.current_step ??
        run?.stats?.current_step ??
        (stepLogs.length > 0 ? stepLogs[stepLogs.length - 1]?.step : null);
      applyCurrentStepFallback(map, currentStep);
    } else if (
      runStatus === "completed" ||
      runStatus === "completed_with_errors" ||
      runStatus === "failed"
    ) {
      for (const step of PIPELINE_STEPS) {
        const current = map.get(step);
        if (current && current.status === "pending") {
          map.set(step, { ...current, status: "completed" });
        }
      }
    }

    return map;
  } catch {
    return null;
  }
}

const MAX_WS_RETRIES = 5;

export const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "completed_with_errors",
  "failed",
  "skipped",
  "cancelled",
]);

export async function probeRunStatus(runId: string): Promise<string | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), RUN_STATUS_REQUEST_TIMEOUT_MS);
    const res = await fetch(backendUrl(`/api/v1/extraction/runs/${runId}/status`), {
      signal: controller.signal,
    });
    clearTimeout(timer);
    if (!res.ok) return null;
    const run = await res.json();
    const status = run?.status;
    return typeof status === "string" ? status : null;
  } catch {
    return null;
  }
}

export function useExtractionSocket(
  runId: string | null,
): UseExtractionSocketReturn {
  const [steps, setSteps] = useState<Map<string, StepStatus>>(buildInitialSteps);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const wsHasDeliveredRef = useRef(false);
  const wsLastEventAtRef = useRef(0);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const applyEvent = useCallback((evt: WebSocketEvent) => {
    if (
      evt.type === "step_started" ||
      evt.type === "step_completed" ||
      evt.type === "step_failed"
    ) {
      wsHasDeliveredRef.current = true;
      wsLastEventAtRef.current = Date.now();
    }
    setSteps((prev) => {
      const next = new Map(prev);
      const rawStep = evt.step;
      if (!rawStep) return next;
      const stepName = toFrontendStep(rawStep) as PipelineStep;
      if (!next.has(stepName)) return next;

      const current = next.get(stepName) ?? { status: "pending" as StepStatusValue };

      switch (evt.type) {
        case "step_started":
          next.set(stepName, {
            ...current,
            status: "running",
            startedAt: evt.timestamp,
            data: evt.data,
          });
          break;
        case "step_completed":
          next.set(stepName, {
            ...current,
            status: "completed",
            completedAt: evt.timestamp,
            data: evt.data,
          });
          break;
        case "step_failed":
          next.set(stepName, {
            ...current,
            status: "failed",
            completedAt: evt.timestamp,
            error: evt.error,
            data: evt.data,
          });
          break;
        case "pipeline_paused":
          next.set(stepName, {
            ...current,
            status: "paused",
            data: evt.data,
          });
          break;
        case "completed":
          break;
      }

      return next;
    });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // REST fallback when WS is down or connected on a worker that never receives events.
  useEffect(() => {
    if (!runId) return;
    let intervalId: ReturnType<typeof setInterval> | null = null;

    async function poll() {
      if (!mountedRef.current) return;

      const wsOpen = wsRef.current?.readyState === WebSocket.OPEN;
      const wsSilent =
        wsOpen &&
        (!wsHasDeliveredRef.current ||
          Date.now() - wsLastEventAtRef.current > 15_000);

      if (wsOpen && wsHasDeliveredRef.current && !wsSilent) return;

      const restSteps = await fetchStepsFromRest(runId!);
      if (!restSteps || !mountedRef.current) return;

      setSteps(restSteps);

      const allDone = [...restSteps.values()].every(
        (s) => s.status === "completed" || s.status === "failed",
      );
      if (allDone && intervalId) {
        clearInterval(intervalId);
        intervalId = null;
      }
    }

    const initialTimer = setTimeout(() => {
      void poll();
      intervalId = setInterval(() => void poll(), RUN_STATUS_POLL_MS);
    }, 500);

    return () => {
      clearTimeout(initialTimer);
      if (intervalId) clearInterval(intervalId);
    };
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setSteps(buildInitialSteps());
      setIsConnected(false);
      setError(null);
      return;
    }

    let cancelled = false;

    function connect() {
      if (!mountedRef.current || cancelled || !runId) return;

      if (retriesRef.current >= MAX_WS_RETRIES) {
        setError(null);
        return;
      }

      const url = resolveWsUrl(runId);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        setError(null);
        retriesRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const parsed = JSON.parse(event.data) as WebSocketEvent;
          applyEvent(parsed);
        } catch {
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        // silently handled by onclose
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        wsRef.current = null;

        retriesRef.current += 1;
        if (retriesRef.current < MAX_WS_RETRIES) {
          timerRef.current = setTimeout(connect, 2000);
        }
      };
    }

    setSteps(buildInitialSteps());
    retriesRef.current = 0;
    wsHasDeliveredRef.current = false;
    wsLastEventAtRef.current = 0;

    (async () => {
      const status = await probeRunStatus(runId);
      if (cancelled || !mountedRef.current) return;
      if (status !== null && TERMINAL_RUN_STATUSES.has(status)) {
        return;
      }
      connect();
    })();

    return () => {
      cancelled = true;
      clearTimer();
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [runId, applyEvent, clearTimer]);

  return { steps, isConnected, error };
}
