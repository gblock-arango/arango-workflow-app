"use client";

import { useEffect, useState } from "react";
import { AGENT_DAG_HEIGHT_PX } from "@/components/pipeline/AgentDAG";
import {
  computeLlmCallsPerMinute,
  countRunningAgents,
  effectiveAgentStartedAt,
  formatCompactNumber,
  formatEpochTime,
  formatStepLabel,
  isAgentPhase,
  pickAgentDiagnostics,
  pickTokenUsage,
  recentAgentStepLogs,
} from "@/lib/agentDiagnostics";
import type { RunProgressSnapshot } from "@/lib/runStatusPoll";
import {
  effectivePreparationStage,
  isPreparationBlocked,
  isRunStatusPollTimeout,
  isSchemaBootstrapComplete,
  preparationSilenceMs,
  preparationStallThresholdMs,
  PREPARATION_UI_MAX_SILENCE_MS,
} from "@/lib/runStatusPoll";
import type { StepStatus } from "@/types/pipeline";

const PREPARATION_STEPS: {
  key: string;
  label: string;
  detail: string;
}[] = [
  {
    key: "queued",
    label: "Run accepted",
    detail: "Run ID returned; background worker starting gateway checks",
  },
  {
    key: "gateway_health",
    label: "Gateway /health",
    detail: "HTTP probe to arango-gateway-app before any Arango REST",
  },
  {
    key: "gateway_arango",
    label: "Arango session",
    detail: "Open database connection through gateway proxy",
  },
  {
    key: "run_persisted",
    label: "Run in Arango",
    detail: "Insert extraction_runs doc and read back to confirm write",
  },
  {
    key: "materializing_arango",
    label: "Materialize to Arango",
    detail: "UC volume chunks + embeddings → documents/chunks via gateway",
  },
  {
    key: "schema_migrations",
    label: "Schema migrations",
    detail: "Ontology collections and indexes through gateway (slow on first run)",
  },
  {
    key: "launching_pipeline",
    label: "Launch agents",
    detail: "LangGraph extraction pipeline starting",
  },
];

function stepState(
  stepKey: string,
  progress: RunProgressSnapshot | null,
): "done" | "active" | "pending" | "failed" {
  if (!progress) return "pending";
  if (progress.status === "failed") {
    const stage = progress.preparation_stage ?? "queued";
    const order = PREPARATION_STEPS.map((s) => s.key);
    const failIdx = order.indexOf(stage);
    const stepIdx = order.indexOf(stepKey);
    if (failIdx < 0) {
      return stepIdx === 0 ? "failed" : "pending";
    }
    if (stepIdx < failIdx) return "done";
    if (stepIdx === failIdx) return "failed";
    return "pending";
  }
  if (progress.status === "running" || progress.status === "completed") {
    return "done";
  }
  const stage = effectivePreparationStage(progress);
  const order = PREPARATION_STEPS.map((s) => s.key);
  const activeIdx = order.indexOf(stage);
  const stepIdx = order.indexOf(stepKey);
  if (activeIdx < 0) return stepIdx === 0 ? "active" : "pending";
  if (stepIdx < activeIdx) return "done";
  if (stepIdx === activeIdx) return "active";
  return "pending";
}

function formatPolledAt(ms: number | null): string {
  if (ms == null) return "";
  const sec = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (sec < 5) return "just now";
  return `${sec}s ago`;
}

function progressDetailLine(progress: RunProgressSnapshot | null): string | null {
  if (!progress?.preparation_progress) return null;
  const p = progress.preparation_progress;
  if (p.phase === "gateway_health" || p.phase === "gateway_arango" || p.phase === "run_persisted") {
    const parts: string[] = [];
    if (p.gateway_ok === true) parts.push("gateway OK");
    if (p.gateway_ok === false) parts.push("gateway failed");
    if (p.arango_verified) parts.push("run doc verified in Arango");
    if (parts.length > 0) return parts.join(" · ");
  }
  if (p.bootstrap_phase === "persist") {
    return "Schema bootstrap complete — saving migration state to Arango…";
  }
  if (p.bootstrap_phase === "complete") {
    return "Schema bootstrap complete — finalizing before agents start…";
  }
  if (p.index_done != null && p.index_total != null && p.index_step === "mdi") {
    return `Schema indexes: MDI temporal ${p.index_done}/${p.index_total}`;
  }
  if (p.confirm_run_status) {
    return "Confirming run status in Arango before agents start…";
  }
  if (
    (p.phase === "schema_migration" || p.phase === "schema_migrations") &&
    p.migration
  ) {
    const total = p.migration_total ?? p.migration_pending;
    const idx =
      p.migration_index != null && total != null
        ? ` (${p.migration_index}/${total})`
        : "";
    const elapsed =
      p.migration_elapsed_s != null ? ` · ${p.migration_elapsed_s}s` : "";
    return `Schema migration${idx}: ${p.migration}${elapsed}`;
  }
  if (p.phase === "staging_schema") {
    const created = p.collections_created as string[] | undefined;
    if (created?.length) return `Staging: created ${created.join(", ")}`;
    return "Staging: documents/chunks collections";
  }
  if (p.phase === "read_uc") {
    if (p.chunk_count != null) return `UC: ${p.chunk_count} chunks loaded`;
    if (p.status === "embeddings") return "UC: loading embeddings…";
    return "UC: reading chunks…";
  }
  if (p.phase === "document_upsert" && p.chunk_count != null) {
    const emb = p.embedding_count != null ? ` · ${p.embedding_count} embeddings` : "";
    return `Document upsert · ${p.chunk_count} chunks${emb}`;
  }
  if (p.phase === "arango_insert" && p.total != null && p.inserted != null) {
    const batch =
      p.batch_size != null ? ` · batch size ${p.batch_size}` : "";
    return `Chunk insert progress: ${p.inserted}/${p.total}${batch}`;
  }
  if (p.doc_index != null && p.doc_total != null && p.doc_id) {
    return `Document ${p.doc_index}/${p.doc_total}: ${p.doc_id}`;
  }
  if (p.heartbeat_seq != null && p.heartbeat_elapsed_s != null) {
    return `Worker heartbeat #${p.heartbeat_seq} · ${p.heartbeat_elapsed_s}s in current stage`;
  }
  if (p.chunk_count != null) {
    return `${p.chunk_count} chunks loaded from UC`;
  }
  return null;
}

function formatCheckpointTime(epochSec: number): string {
  return new Date(epochSec * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

interface PipelineDiagnosticsPanelProps {
  selectedRunId: string | null;
  progress: RunProgressSnapshot | null;
  pollError: string | null;
  pollBusy: boolean;
  lastPolledAt: number | null;
  pollAttempt: number;
  /** Live agent step map from WebSocket (for running-agent count). */
  agentSteps?: Map<string, StepStatus>;
  /** When true, render as a compact right rail beside the Agent Pipeline DAG. */
  embedded?: boolean;
}

export default function PipelineDiagnosticsPanel({
  selectedRunId,
  progress,
  pollError,
  pollBusy,
  lastPolledAt,
  pollAttempt,
  agentSteps,
  embedded = false,
}: PipelineDiagnosticsPanelProps) {
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    if (!selectedRunId) return;
    const id = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [selectedRunId]);

  const waitingForFirstPoll = Boolean(selectedRunId) && progress == null && pollAttempt === 0;
  const displayProgress: RunProgressSnapshot | null =
    progress ??
    (selectedRunId && waitingForFirstPoll
      ? {
          run_id: selectedRunId,
          status: "preparing",
          preparation_stage: "queued",
          preparation_message: "Waiting for first status update from server…",
        }
      : null);

  const prepUpdatedMs =
    displayProgress?.preparation_updated_at != null
      ? displayProgress.preparation_updated_at * 1000
      : null;
  const silenceMs = preparationSilenceMs(displayProgress, nowMs);
  const prepBlocked = isPreparationBlocked(displayProgress, nowMs);
  const stage = effectivePreparationStage(displayProgress);
  const bootstrapFinalizing =
    displayProgress != null &&
    displayProgress.status === "preparing" &&
    isSchemaBootstrapComplete(displayProgress);
  const stallThresholdMs = preparationStallThresholdMs(stage);
  const prepStalled =
    !pollError &&
    !prepBlocked &&
    !bootstrapFinalizing &&
    displayProgress?.status === "preparing" &&
    prepUpdatedMs != null &&
    nowMs - prepUpdatedMs > stallThresholdMs;

  const checkpoints = displayProgress?.preparation_progress?.checkpoints ?? [];
  const showAgentTelemetry = isAgentPhase(displayProgress);
  const agentDiag = pickAgentDiagnostics(displayProgress);
  const tokenUsage = pickTokenUsage(displayProgress);
  const agentStartedAt = effectiveAgentStartedAt(displayProgress, agentDiag);
  const llmCalls = agentDiag?.llm_calls ?? 0;
  const callsPerMin = computeLlmCallsPerMinute(llmCalls, agentStartedAt, nowMs);
  const runningAgents = countRunningAgents(displayProgress, agentSteps);
  const promptTokens =
    agentDiag?.prompt_tokens ?? tokenUsage?.prompt_tokens ?? 0;
  const completionTokens =
    agentDiag?.completion_tokens ?? tokenUsage?.completion_tokens ?? 0;
  const totalTokens =
    agentDiag?.total_tokens ??
    tokenUsage?.total_tokens ??
    promptTokens + completionTokens;
  const promptChars = agentDiag?.prompt_chars ?? 0;
  const stepEvents = recentAgentStepLogs(displayProgress);

  const subProgress = progressDetailLine(displayProgress);
  const pollTimedOut = pollError != null && isRunStatusPollTimeout(pollError);

  if (embedded && !selectedRunId) {
    return null;
  }

  const content = selectedRunId ? (
    <div
      className={
        embedded
          ? "space-y-2"
          : "rounded-lg border border-gray-200 bg-white px-3 py-2 space-y-2"
      }
    >
      {!embedded && (
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="font-mono text-gray-500 truncate" title={selectedRunId}>
            {selectedRunId}
          </span>
          {displayProgress?.status && (
            <span
              className={`shrink-0 font-medium capitalize ${
                displayProgress.status === "failed"
                  ? "text-red-700"
                  : displayProgress.status === "preparing"
                    ? "text-indigo-700"
                    : displayProgress.status === "running"
                      ? "text-emerald-700"
                      : "text-gray-700"
              }`}
            >
              {displayProgress.status.replace(/_/g, " ")}
            </span>
          )}
        </div>
      )}

      {embedded && displayProgress?.status && (
        <div className="flex items-center justify-end text-xs">
          <span
            className={`shrink-0 font-medium capitalize ${
              displayProgress.status === "failed"
                ? "text-red-700"
                : displayProgress.status === "preparing"
                  ? "text-indigo-700"
                  : displayProgress.status === "running"
                    ? "text-emerald-700"
                    : "text-gray-700"
            }`}
          >
            {displayProgress.status.replace(/_/g, " ")}
          </span>
        </div>
      )}

      {pollError && (
            <p
              className={`text-[11px] rounded px-2 py-1 ${
                pollTimedOut || pollBusy
                  ? "text-amber-800 bg-amber-50 border border-amber-100"
                  : "text-red-600 bg-red-50"
              }`}
            >
              {pollTimedOut || pollBusy
                ? `Status poll slow (${pollAttempt}) — extraction may still be running (API busy).`
                : `Poll failed (${pollAttempt}): ${pollError}`}
              {progress ? " Showing last known status." : ""}
            </p>
          )}

          {displayProgress?.status === "preparing" && silenceMs != null && (
            <p
              className={`text-[11px] rounded px-2 py-1 ${
                prepBlocked
                  ? "text-red-800 bg-red-50 border border-red-200 font-medium"
                  : silenceMs > PREPARATION_UI_MAX_SILENCE_MS * 0.6
                    ? "text-amber-800 bg-amber-50 border border-amber-100"
                    : "text-gray-600 bg-gray-50 border border-gray-100"
              }`}
            >
              {prepBlocked
                ? `BLOCKED — no server progress update for ${Math.round(silenceMs / 1000)}s (limit ${PREPARATION_UI_MAX_SILENCE_MS / 1000}s). Worker may be stuck on a gateway call or the prepare thread died. Check arango-gateway-app logs.`
                : `Last server update: ${Math.round(silenceMs / 1000)}s ago`}
            </p>
          )}

          {prepStalled && (
            <p className="text-[11px] text-amber-800 bg-amber-50 border border-amber-100 rounded px-2 py-1">
              Preparation has not advanced at stage{" "}
              <strong>{stage}</strong>
              {` for ${Math.round(stallThresholdMs / 1000)}s`}
              {stage === "gateway_health" || stage === "gateway_arango"
                ? " — gateway may be cold-starting or workers busy (first /health after redeploy is often 10–60s)."
                : stage === "run_persisted"
                  ? " — Arango write/read via gateway+tunnel can take 30–90s; see checkpoint lines below."
                  : stage === "schema_migrations"
                    ? " — a schema migration may be slow through the gateway; see migration line below."
                    : stage === "materializing_arango"
                      ? " — UC read or chunk insert may be slow; check gateway logs."
                      : " — worker may be stuck; check gateway logs."}
            </p>
          )}

          {displayProgress?.preparation_message && !showAgentTelemetry && (
            <p className="text-[11px] text-gray-600 bg-gray-50 rounded px-2 py-1 leading-relaxed">
              {displayProgress.preparation_message}
            </p>
          )}

          {showAgentTelemetry && (
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-emerald-700 uppercase tracking-wide">
                Agent &amp; LLM telemetry
              </p>
              <div className="grid grid-cols-2 gap-1.5">
                <MetricTile label="LLM calls" value={formatCompactNumber(llmCalls)} />
                <MetricTile
                  label="Calls / min"
                  value={
                    callsPerMin != null ? callsPerMin.toFixed(1) : llmCalls > 0 ? "…" : "0"
                  }
                />
                <MetricTile label="Prompt tokens" value={formatCompactNumber(promptTokens)} />
                <MetricTile
                  label="Completion tokens"
                  value={formatCompactNumber(completionTokens)}
                />
                <MetricTile label="Total tokens" value={formatCompactNumber(totalTokens)} />
                <MetricTile label="Prompt chars" value={formatCompactNumber(promptChars)} />
                <MetricTile label="Agents running" value={String(runningAgents)} />
                <MetricTile
                  label="Current step"
                  value={
                    displayProgress?.current_step
                      ? formatStepLabel(displayProgress.current_step)
                      : "—"
                  }
                  wide
                />
              </div>
              {displayProgress?.model && (
                <p className="text-[10px] text-gray-500 font-mono truncate">
                  Model: {displayProgress.model}
                </p>
              )}
              {agentDiag?.last_llm_at != null && (
                <p className="text-[10px] text-gray-500">
                  Last LLM: {formatEpochTime(agentDiag.last_llm_at)}
                  {agentDiag.last_llm_step
                    ? ` · ${formatStepLabel(agentDiag.last_llm_step)}`
                    : ""}
                </p>
              )}
              {stepEvents.length > 0 && (
                <div className="rounded border border-emerald-100 bg-emerald-50/50 px-2 py-1.5 space-y-1">
                  <p className="text-[10px] font-semibold text-emerald-800 uppercase tracking-wide">
                    Agent state changes
                  </p>
                  <ul className="space-y-0.5 max-h-36 overflow-y-auto">
                    {stepEvents.map((entry, i) => (
                      <li
                        key={`${entry.step}-${entry.started_at}-${i}`}
                        className="text-[10px] font-mono leading-snug text-gray-700"
                      >
                        <span className="text-gray-400">
                          {formatEpochTime(entry.completed_at ?? entry.started_at)}
                        </span>{" "}
                        <span className="font-semibold">
                          {entry.step ? formatStepLabel(entry.step) : "step"}
                        </span>
                        {": "}
                        <span
                          className={
                            entry.status === "failed"
                              ? "text-red-700"
                              : entry.status === "running"
                                ? "text-emerald-700"
                                : "text-gray-600"
                          }
                        >
                          {entry.status ?? "unknown"}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {llmCalls === 0 && stepEvents.length === 0 && (
                <p className="text-[11px] text-gray-500 bg-gray-50 rounded px-2 py-1">
                  Pipeline running — LLM counters update as extraction and judge calls complete.
                </p>
              )}
            </div>
          )}

          {!showAgentTelemetry && displayProgress?.status === "running" && displayProgress.current_step && (
            <p className="text-[11px] text-emerald-800 bg-emerald-50 rounded px-2 py-1">
              Agent step:{" "}
              <code className="font-mono">{displayProgress.current_step.replace(/_/g, " ")}</code>
            </p>
          )}

          {!showAgentTelemetry && subProgress && (
            <p className="text-[11px] text-indigo-800 bg-indigo-50 rounded px-2 py-1">
              {subProgress}
            </p>
          )}

          {!showAgentTelemetry && checkpoints.length > 0 && (
            <div className="rounded border border-gray-100 bg-gray-50 px-2 py-1.5 space-y-1">
              <p className="text-[10px] font-semibold text-gray-500 uppercase tracking-wide">
                Gateway checkpoints
              </p>
              <ul className="space-y-0.5 max-h-28 overflow-y-auto">
                {checkpoints.map((cp, i) => (
                  <li
                    key={`${cp.at}-${i}`}
                    className={`text-[10px] font-mono leading-snug ${
                      cp.ok ? "text-gray-600" : "text-red-700"
                    }`}
                  >
                    <span className="text-gray-400">{formatCheckpointTime(cp.at)}</span>{" "}
                    {cp.stage}: {cp.message}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!showAgentTelemetry && (
          <ol className="space-y-1.5">
            {PREPARATION_STEPS.map((step) => {
              const state = stepState(step.key, displayProgress);
              const dot =
                state === "done"
                  ? "bg-emerald-500"
                  : state === "active"
                    ? "bg-indigo-500 animate-pulse"
                    : state === "failed"
                      ? "bg-red-500"
                      : "bg-gray-300";
              return (
                <li key={step.key} className="flex items-start gap-2 text-[11px]">
                  <span className={`mt-1 h-1.5 w-1.5 rounded-full shrink-0 ${dot}`} />
                  <div className="min-w-0">
                    <span
                      className={
                        state === "active"
                          ? "font-semibold text-gray-800"
                          : state === "failed"
                            ? "font-semibold text-red-800"
                            : "text-gray-600"
                      }
                    >
                      {step.label}
                      {state === "failed" ? " — failed" : ""}
                    </span>
                    <span className="block text-gray-400 leading-snug">{step.detail}</span>
                  </div>
                </li>
              );
            })}
          </ol>
          )}

          {showAgentTelemetry && !embedded && (
            <details className="text-[11px] text-gray-500">
              <summary className="cursor-pointer hover:text-gray-700">Preparation steps (completed)</summary>
              <ol className="mt-1.5 space-y-1">
                {PREPARATION_STEPS.map((step) => (
                  <li key={step.key} className="flex items-center gap-2">
                    <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 shrink-0" />
                    <span className="text-gray-600">{step.label}</span>
                  </li>
                ))}
              </ol>
            </details>
          )}

          {!showAgentTelemetry && displayProgress?.status === "running" && !embedded && (
            <p className="text-[11px] text-emerald-700">
              Chunks are in Arango — agent pipeline is running (see DAG below; updates via REST
              when WebSocket is on another worker).
            </p>
          )}

          {displayProgress?.errors && displayProgress.errors.length > 0 && (
            <div className="text-[11px] text-red-700 bg-red-50 border border-red-100 rounded px-2 py-1 space-y-0.5">
              <p className="font-semibold">Errors</p>
              {displayProgress.errors.map((err, i) => (
                <p key={i} className="font-mono break-words">
                  {err}
                </p>
              ))}
            </div>
          )}
        </div>
  ) : null;

  if (embedded) {
    return (
      <aside
        className="flex flex-col w-full lg:w-[340px] flex-shrink-0 border-t lg:border-t-0 lg:border-l border-gray-100 bg-gray-50/40 overflow-hidden"
        style={{ height: AGENT_DAG_HEIGHT_PX }}
        aria-label="Run diagnostics"
      >
        <div className="px-3 py-2 border-b border-gray-100 shrink-0 space-y-0.5">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
              Diagnostics
            </h2>
            {lastPolledAt && (
              <span className="text-[10px] text-gray-400 shrink-0">
                {formatPolledAt(lastPolledAt)}
              </span>
            )}
          </div>
          <p className="text-[10px] text-gray-400 leading-snug">
            {showAgentTelemetry ? "Agent & LLM telemetry" : "Run progress polls"}
          </p>
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-2">{content}</div>
      </aside>
    );
  }

  return (
    <section className="border-b border-gray-200 bg-white px-4 py-3 space-y-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
            Diagnostics
          </h2>
          <p className="text-[11px] text-gray-400 mt-0.5 leading-snug">
            {showAgentTelemetry ? "Agent & LLM telemetry" : "Run progress polls"}
          </p>
        </div>
        {selectedRunId && lastPolledAt && (
          <span className="text-[10px] text-gray-400 shrink-0">
            run {formatPolledAt(lastPolledAt)}
          </span>
        )}
      </div>
      {content}
    </section>
  );
}

function MetricTile({
  label,
  value,
  wide = false,
}: {
  label: string;
  value: string;
  wide?: boolean;
}) {
  return (
    <div
      className={`rounded border border-gray-100 bg-white px-2 py-1.5 ${
        wide ? "col-span-2" : ""
      }`}
    >
      <p className="text-[9px] uppercase tracking-wide text-gray-400">{label}</p>
      <p className="text-[12px] font-semibold text-gray-800 truncate" title={value}>
        {value}
      </p>
    </div>
  );
}
