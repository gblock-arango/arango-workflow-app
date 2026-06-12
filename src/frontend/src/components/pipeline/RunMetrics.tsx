"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";
import { formatStepLabel } from "@/lib/agentDiagnostics";
import { ACTIVE_RUN_STATUSES, RUN_STATUS_POLL_MS } from "@/lib/runStatusPoll";
import type { BeliefRevisionSummary, RunCostResponse, StepStatus } from "@/types/pipeline";

const IBR_REASON_LABELS: Record<string, string> = {
  feature_flag_off: "IBR disabled in this environment",
  no_extraction_results: "No extraction results to revise",
  no_ontology_id: "No target ontology resolved",
  no_document_id: "No document context available",
};

function ibrReasonLabel(reason: string | undefined): string {
  if (!reason) return "Skipped";
  return IBR_REASON_LABELS[reason] ?? `Skipped: ${reason}`;
}

function verdictsSublabel(counts: Record<string, number>): string {
  const entries = Object.entries(counts).filter(([, n]) => n > 0);
  if (entries.length === 0) return "—";
  entries.sort((a, b) => b[1] - a[1]);
  return entries
    .map(([verdict, n]) => `${verdict.replace(/^FLAG_FOR_/, "FLAG·")} ${n}`)
    .join(" · ");
}

interface RunMetricsProps {
  runId: string | null;
  runStatus?: string | null;
  agentSteps?: Map<string, StepStatus>;
  /** Smaller metric tiles (Pipeline page Metrics tab only). */
  compact?: boolean;
}

type MetricsSize = "default" | "compact";

function metricsSizeClasses(size: MetricsSize) {
  const compact = size === "compact";
  return {
    card: compact
      ? "bg-white rounded-lg border border-gray-200 p-2 shadow-sm"
      : "bg-white rounded-xl border border-gray-200 p-4 shadow-sm",
    headerRow: compact ? "flex items-center gap-1 mb-1" : "flex items-center gap-1.5 mb-2",
    label: compact
      ? "text-[10px] font-semibold text-gray-500 uppercase tracking-wide leading-tight"
      : "text-xs font-semibold text-gray-500 uppercase tracking-wide",
    liveBadge: compact
      ? "text-[8px] font-semibold uppercase tracking-wide text-emerald-600 bg-emerald-50 px-0.5 py-px rounded"
      : "text-[9px] font-semibold uppercase tracking-wide text-emerald-600 bg-emerald-50 px-1 py-0.5 rounded",
    value: compact
      ? "text-lg font-bold text-gray-900 leading-tight"
      : "text-2xl font-bold text-gray-900",
    sublabel: compact
      ? "text-[10px] text-gray-400 mt-0.5 leading-snug"
      : "text-xs text-gray-400 mt-1",
    skeletonCard: compact
      ? "bg-white rounded-lg border border-gray-200 p-2 shadow-sm animate-pulse"
      : "bg-white rounded-xl border border-gray-200 p-4 shadow-sm animate-pulse",
    skeletonLabel: compact ? "h-2 w-16 bg-gray-200 rounded mb-1.5" : "h-3 w-20 bg-gray-200 rounded mb-3",
    skeletonValue: compact ? "h-4 w-12 bg-gray-200 rounded" : "h-7 w-16 bg-gray-200 rounded",
    pad: compact ? "p-2" : "p-4",
    gridGap: compact ? "gap-1.5" : "gap-3",
    spaceY: compact ? "space-y-1.5" : "space-y-3",
    errorBanner: compact
      ? "text-[10px] text-amber-700 bg-amber-50 border border-amber-100 rounded px-1.5 py-0.5"
      : "text-xs text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1",
    agentPanel: compact
      ? "rounded-lg border border-emerald-100 bg-emerald-50/40 px-2 py-1"
      : "rounded-lg border border-emerald-100 bg-emerald-50/40 px-3 py-2",
    agentHeader: compact
      ? "text-[9px] font-semibold text-emerald-800 uppercase tracking-wide mb-1"
      : "text-[10px] font-semibold text-emerald-800 uppercase tracking-wide mb-1.5",
    agentRow: compact
      ? "text-[10px] font-mono text-gray-700 leading-snug"
      : "text-[11px] font-mono text-gray-700",
  };
}

function formatDuration(ms: number | undefined): string {
  if (ms == null || ms === 0) return "—";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSec = seconds % 60;
  return `${minutes}m ${remainingSec}s`;
}

function formatNumber(n: number | undefined): string {
  if (n == null) return "0";
  return n.toLocaleString();
}

function formatCost(cost: number | undefined): string {
  if (cost == null) return "$0.00";
  return `$${cost.toFixed(2)}`;
}

function formatPercent(rate: number | undefined): string {
  if (rate == null || rate === 0) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

function countRunningFromSteps(steps?: Map<string, StepStatus>): number {
  if (!steps || steps.size === 0) return 0;
  let n = 0;
  for (const step of steps.values()) {
    if (step.status === "running") n += 1;
  }
  return n;
}

interface MetricCardProps {
  label: string;
  value: string;
  sublabel?: string;
  live?: boolean;
  size?: MetricsSize;
}

function MetricCard({ label, value, sublabel, live, size = "default" }: MetricCardProps) {
  const c = metricsSizeClasses(size);
  return (
    <div className={c.card}>
      <div className={c.headerRow}>
        <div className={c.label}>{label}</div>
        {live && <span className={c.liveBadge}>live</span>}
      </div>
      <div className={c.value}>{value}</div>
      {sublabel && <div className={c.sublabel}>{sublabel}</div>}
    </div>
  );
}

function SkeletonCard({ size = "default" }: { size?: MetricsSize }) {
  const c = metricsSizeClasses(size);
  return (
    <div className={c.skeletonCard}>
      <div className={c.skeletonLabel} />
      <div className={c.skeletonValue} />
    </div>
  );
}

export default function RunMetrics({
  runId,
  runStatus,
  agentSteps,
  compact = false,
}: RunMetricsProps) {
  const size: MetricsSize = compact ? "compact" : "default";
  const layout = metricsSizeClasses(size);
  const [metrics, setMetrics] = useState<RunCostResponse | null>(null);
  const [initialLoading, setInitialLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const hasLoaded = useRef(false);

  const pollActive =
    runStatus != null && ACTIVE_RUN_STATUSES.has(runStatus);

  const fetchMetrics = useCallback(async () => {
    if (!runId) return;
    if (!hasLoaded.current) setInitialLoading(true);
    setError(null);
    try {
      const data = await api.get<RunCostResponse>(
        `/api/v1/extraction/runs/${runId}/cost`,
      );
      setMetrics(data);
      hasLoaded.current = true;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load metrics");
    } finally {
      setInitialLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    hasLoaded.current = false;
    setMetrics(null);
    if (!runId) return;

    void fetchMetrics();
    if (!pollActive) return;

    const id = window.setInterval(() => {
      void fetchMetrics();
    }, RUN_STATUS_POLL_MS);
    return () => window.clearInterval(id);
  }, [runId, pollActive, fetchMetrics]);

  if (!runId) {
    return (
      <div className={`text-sm text-gray-400 ${layout.pad}`} data-testid="metrics-empty">
        Select a run to view metrics.
      </div>
    );
  }

  if (error && !metrics) {
    return (
      <div className={`text-sm text-red-500 ${layout.pad}`} data-testid="metrics-error">
        {error}
      </div>
    );
  }

  if (initialLoading || !metrics) {
    return (
      <div
        className={`grid grid-cols-2 lg:grid-cols-5 ${layout.gridGap} ${layout.pad}`}
        data-testid="metrics-loading"
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <SkeletonCard key={i} size={size} />
        ))}
      </div>
    );
  }

  const isLive = metrics.live === true || pollActive;
  const agentsRunning = Math.max(
    metrics.agents_running ?? 0,
    countRunningFromSteps(agentSteps),
  );
  const llmCalls = metrics.llm_calls ?? 0;
  const callsPerMin = metrics.llm_calls_per_min;

  const confidenceLabel =
    metrics.avg_confidence != null
      ? `${(metrics.avg_confidence * 100).toFixed(1)}%`
      : "—";

  const confidenceSublabel =
    metrics.avg_confidence != null
      ? metrics.avg_confidence > 0.7
        ? "High confidence"
        : metrics.avg_confidence >= 0.5
          ? "Moderate confidence"
          : "Low confidence"
      : undefined;

  const stepLogs = Array.isArray(metrics.step_logs) ? metrics.step_logs : [];
  const recentSteps = [...stepLogs].reverse().slice(0, 6);

  return (
    <div className={`${layout.spaceY} ${layout.pad}`} data-testid="run-metrics">
      {error && <p className={layout.errorBanner}>Metrics poll failed — showing last values. {error}</p>}

      <div className={`grid grid-cols-2 lg:grid-cols-5 ${layout.gridGap}`}>
        <MetricCard
          size={size}
          label="Total Duration"
          value={formatDuration(metrics.total_duration_ms)}
          sublabel={isLive ? "Elapsed (updates while running)" : undefined}
          live={isLive}
        />
        <MetricCard
          size={size}
          label="LLM Calls"
          value={formatNumber(llmCalls)}
          sublabel={
            callsPerMin != null
              ? `${callsPerMin.toFixed(1)} calls / min`
              : isLive
                ? "Updates as agents invoke the model"
                : undefined
          }
          live={isLive}
        />
        <MetricCard
          size={size}
          label="Token Usage"
          value={formatNumber(metrics.total_tokens)}
          sublabel={`${formatNumber(metrics.prompt_tokens)} prompt + ${formatNumber(metrics.completion_tokens)} completion`}
          live={isLive}
        />
        <MetricCard
          size={size}
          label="Estimated Cost"
          value={formatCost(metrics.estimated_cost)}
          live={isLive}
        />
        <MetricCard
          size={size}
          label="Entity Counts"
          value={String(
            (metrics.classes_extracted ?? 0) + (metrics.properties_extracted ?? 0),
          )}
          sublabel={`${metrics.classes_extracted ?? 0} classes + ${metrics.properties_extracted ?? 0} properties`}
          live={isLive}
        />
        <MetricCard
          size={size}
          label="Agreement Rate"
          value={formatPercent(metrics.pass_agreement_rate)}
          sublabel="Cross-pass consistency"
          live={isLive && (metrics.pass_agreement_rate ?? 0) > 0}
        />
        <MetricCard
          size={size}
          label="Agents Running"
          value={String(agentsRunning)}
          sublabel={
            metrics.current_step
              ? `Current: ${formatStepLabel(metrics.current_step)}`
              : isLive
                ? "LangGraph pipeline"
                : undefined
          }
          live={isLive}
        />
        {(metrics.merge_candidates_found ?? 0) > 0 && (
          <MetricCard
            size={size}
            label="ER Merge Candidates"
            value={formatNumber(metrics.merge_candidates_found)}
            sublabel="Entity resolution matches"
            live={isLive}
          />
        )}
        <MetricCard
          size={size}
          label="Avg Confidence"
          value={confidenceLabel}
          sublabel={confidenceSublabel}
        />
        <MetricCard
          size={size}
          label="Completeness"
          value={
            metrics.completeness_pct != null
              ? `${metrics.completeness_pct.toFixed(1)}%`
              : "—"
          }
          sublabel="Classes with properties"
        />
        <BeliefRevisionTiles ibr={metrics.belief_revision ?? null} size={size} />
      </div>

      {isLive && recentSteps.length > 0 && (
        <div className={layout.agentPanel}>
          <p className={layout.agentHeader}>Agent state changes</p>
          <ul className="space-y-0.5">
            {recentSteps.map((entry, i) => {
              if (!entry || typeof entry !== "object") return null;
              const row = entry as Record<string, unknown>;
              const step = typeof row.step === "string" ? row.step : "step";
              const status = typeof row.status === "string" ? row.status : "unknown";
              return (
                <li
                  key={`${step}-${String(row.started_at)}-${i}`}
                  className={layout.agentRow}
                >
                  <span className="font-semibold">{formatStepLabel(step)}</span>
                  {": "}
                  <span
                    className={
                      status === "failed"
                        ? "text-red-700"
                        : status === "running"
                          ? "text-emerald-700"
                          : "text-gray-600"
                    }
                  >
                    {status}
                  </span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

function BeliefRevisionTiles({
  ibr,
  size = "default",
}: {
  ibr: BeliefRevisionSummary | null;
  size?: MetricsSize;
}) {
  if (ibr == null) {
    return (
      <MetricCard
        size={size}
        label="Belief Revision"
        value="—"
        sublabel="No IBR data on this run"
      />
    );
  }

  if (ibr.status === "skipped") {
    return (
      <MetricCard
        size={size}
        label="Belief Revision"
        value="Skipped"
        sublabel={ibrReasonLabel(ibr.reason)}
      />
    );
  }

  const statusSuffix = ibr.status === "failed" ? " (failed)" : "";
  return (
    <>
      <MetricCard
        size={size}
        label={`IBR Touchpoints${statusSuffix}`}
        value={formatNumber(ibr.touchpoints_discovered)}
        sublabel={`${ibr.llm_invocations} LLM call${ibr.llm_invocations === 1 ? "" : "s"}`}
      />
      <MetricCard
        size={size}
        label="IBR Verdicts"
        value={formatNumber(
          Object.values(ibr.verdict_counts).reduce((a, b) => a + b, 0),
        )}
        sublabel={verdictsSublabel(ibr.verdict_counts)}
      />
      <MetricCard
        size={size}
        label="IBR Auto-applied"
        value={formatNumber(ibr.auto_applied)}
        sublabel={
          ibr.skipped_idempotency > 0
            ? `${ibr.skipped_idempotency} skipped (idempotent)`
            : undefined
        }
      />
      <MetricCard
        size={size}
        label="IBR Flagged for Curation"
        value={formatNumber(ibr.flagged_for_curation)}
        sublabel={
          ibr.flagged_for_curation > 0
            ? "Awaiting human review"
            : "Nothing pending"
        }
      />
    </>
  );
}
