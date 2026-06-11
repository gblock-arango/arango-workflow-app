/** Agent-phase diagnostics derived from status polls and WebSocket step map. */

import type { RunProgressSnapshot } from "@/lib/runStatusPoll";
import type { StepStatus } from "@/types/pipeline";

export interface AgentDiagnosticsSnapshot {
  agent_started_at?: number | null;
  llm_calls?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  prompt_chars?: number;
  last_llm_at?: number | null;
  last_llm_step?: string | null;
  running_steps?: string[];
}

export interface AgentStepLogEntry {
  step?: string;
  status?: string;
  started_at?: number;
  completed_at?: number;
  error?: string;
  metadata?: Record<string, unknown>;
}

const AGENT_PHASE_STATUSES = new Set([
  "running",
  "paused",
  "completed",
  "completed_with_errors",
  "failed",
]);

export function isAgentPhase(
  progress: Pick<RunProgressSnapshot, "status"> | null,
): boolean {
  if (!progress) return false;
  return AGENT_PHASE_STATUSES.has(progress.status);
}

export function pickAgentDiagnostics(
  progress: RunProgressSnapshot | null,
): AgentDiagnosticsSnapshot | null {
  if (!progress) return null;
  const raw =
    progress.agent_diagnostics ??
    (progress.stats?.agent_diagnostics as AgentDiagnosticsSnapshot | undefined);
  if (!raw || typeof raw !== "object") return null;
  return raw;
}

export function pickTokenUsage(
  progress: RunProgressSnapshot | null,
): Record<string, number> | null {
  if (!progress) return null;
  const raw =
    progress.token_usage ??
    (progress.stats?.token_usage as Record<string, number> | undefined);
  if (!raw || typeof raw !== "object") return null;
  return raw;
}

export function effectiveAgentStartedAt(
  progress: RunProgressSnapshot | null,
  diag: AgentDiagnosticsSnapshot | null,
): number | null {
  if (diag?.agent_started_at != null) return diag.agent_started_at;
  if (progress?.started_at != null) return progress.started_at;
  return null;
}

export function computeLlmCallsPerMinute(
  llmCalls: number,
  agentStartedAt: number | null,
  nowMs: number = Date.now(),
): number | null {
  if (llmCalls <= 0 || agentStartedAt == null) return null;
  const elapsedMin = Math.max((nowMs - agentStartedAt * 1000) / 60_000, 1 / 60);
  return llmCalls / elapsedMin;
}

export function countRunningAgents(
  progress: RunProgressSnapshot | null,
  agentSteps?: Map<string, StepStatus>,
): number {
  if (agentSteps && agentSteps.size > 0) {
    let n = 0;
    for (const step of agentSteps.values()) {
      if (step.status === "running") n += 1;
    }
    if (n > 0) return n;
  }
  const diag = pickAgentDiagnostics(progress);
  if (diag?.running_steps?.length) return diag.running_steps.length;
  const logs = progress?.stats?.step_logs;
  if (!Array.isArray(logs)) return 0;
  return logs.filter(
    (entry) =>
      entry &&
      typeof entry === "object" &&
      (entry as AgentStepLogEntry).status === "running",
  ).length;
}

export function recentAgentStepLogs(
  progress: RunProgressSnapshot | null,
  limit = 12,
): AgentStepLogEntry[] {
  const logs = progress?.stats?.step_logs;
  if (!Array.isArray(logs)) return [];
  const parsed = logs
    .filter((entry): entry is AgentStepLogEntry => !!entry && typeof entry === "object")
    .slice(-limit);
  return parsed.reverse();
}

export function formatStepLabel(step: string): string {
  return step.replace(/_/g, " ");
}

export function formatEpochTime(epochSec: number | undefined): string {
  if (epochSec == null) return "—";
  return new Date(epochSec * 1000).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatCompactNumber(n: number | undefined | null): string {
  if (n == null || Number.isNaN(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 10_000) return `${Math.round(n / 1_000)}k`;
  return String(Math.round(n));
}
