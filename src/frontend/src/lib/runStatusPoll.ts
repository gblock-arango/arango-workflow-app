/** Shared lightweight run status polling (diagnostics + agent DAG REST fallback). */

export const RUN_STATUS_POLL_MS = 2_000;
/** Faster poll while gateway / prep checkpoints advance (before agents run). */
export const PREPARATION_STATUS_POLL_MS = 1_000;
/** Short timeout — endpoint should answer from cache/gateway in <1s when workers are free. */
export const RUN_STATUS_REQUEST_TIMEOUT_MS = 12_000;

export const ACTIVE_RUN_STATUSES = new Set([
  "preparing",
  "queued",
  "running",
  "paused",
]);

const STAGE_ALIASES: Record<string, string> = {
  starting: "gateway_arango",
};

/** Min ms without a preparation update before the UI shows a stall warning. */
export const PREPARATION_STALL_MS_BY_STAGE: Record<string, number> = {
  queued: 20_000,
  gateway_health: 70_000,
  gateway_arango: 70_000,
  run_persisted: 120_000,
  starting: 20_000,
  loading_uc_chunks: 90_000,
  materializing_arango: 90_000,
  schema_migrations: 300_000,
  launching_pipeline: 30_000,
};

export const DEFAULT_PREPARATION_STALL_MS = 20_000;

/** Hard limit: UI treats prepare as blocked if the server is silent this long. */
export const PREPARATION_UI_MAX_SILENCE_MS = 15_000;

export function preparationStallThresholdMs(
  stage: string | null | undefined,
): number {
  const key = stage ?? "queued";
  return PREPARATION_STALL_MS_BY_STAGE[key] ?? DEFAULT_PREPARATION_STALL_MS;
}

/** Batch bootstrap finished but gateway may still be persisting schema_state. */
export function isSchemaBootstrapComplete(
  progress: Pick<
    RunProgressSnapshot,
    "preparation_message" | "preparation_progress"
  > | null,
): boolean {
  if (!progress) return false;
  const phase = progress.preparation_progress?.bootstrap_phase;
  if (phase === "complete" || phase === "persist") return true;
  const message = progress.preparation_message ?? "";
  return message.includes("Batch schema bootstrap complete");
}

/** UI stage while status is still preparing (gateway work after bootstrap). */
const PREP_AGENT_STEP = "prepare_arango";

function normalizeAgentStep(step: string | null | undefined): string {
  return (step ?? "").replace(/-/g, "_");
}

function isPrepareArangoAgentActive(
  progress: Pick<RunProgressSnapshot, "current_step" | "stats">,
): boolean {
  const step = normalizeAgentStep(progress.current_step);
  if (step !== PREP_AGENT_STEP) return false;
  const logs = progress.stats?.step_logs;
  if (!Array.isArray(logs)) return true;
  return !logs.some(
    (log) =>
      normalizeAgentStep(String((log as { step?: string }).step ?? "")) ===
        PREP_AGENT_STEP &&
      (log as { status?: string }).status === "completed",
  );
}

/** True when gateway/UC/schema prep is finished and post-prep agents are running. */
export function isPreparationComplete(
  progress: Pick<
    RunProgressSnapshot,
    | "status"
    | "preparation_stage"
    | "preparation_message"
    | "preparation_progress"
    | "current_step"
    | "stats"
  > | null,
): boolean {
  if (!progress) return false;
  if (
    progress.status === "completed" ||
    progress.status === "completed_with_errors"
  ) {
    return true;
  }
  if (isPrepareArangoAgentActive(progress)) return false;
  if (progress.status === "preparing" || progress.status === "queued") {
    return false;
  }

  const logs = progress.stats?.step_logs;
  const prepDone =
    Array.isArray(logs) &&
    logs.some(
      (log) =>
        normalizeAgentStep(String((log as { step?: string }).step ?? "")) ===
          PREP_AGENT_STEP &&
        (log as { status?: string }).status === "completed",
    );
  if (prepDone) return true;

  const step = normalizeAgentStep(progress.current_step);
  if (step && step !== PREP_AGENT_STEP) return true;

  const stage = effectivePreparationStage(progress);
  if (preparationStageRank(stage) < preparationStageRank("launching_pipeline")) {
    return false;
  }

  return progress.status === "running";
}

export function effectivePreparationStage(
  progress: Pick<
    RunProgressSnapshot,
    "status" | "preparation_stage" | "preparation_message" | "preparation_progress"
  > | null,
): string {
  const stage = progress?.preparation_stage ?? "queued";
  if (
    (progress?.status === "preparing" || progress?.status === "running") &&
    stage === "schema_migrations" &&
    isSchemaBootstrapComplete(progress)
  ) {
    return "launching_pipeline";
  }
  return stage;
}

export function preparationSilenceMs(
  progress: Pick<RunProgressSnapshot, "preparation_updated_at"> | null,
  nowMs: number = Date.now(),
): number | null {
  if (progress?.preparation_updated_at == null) return null;
  return Math.max(0, nowMs - progress.preparation_updated_at * 1000);
}

export function isPreparationBlocked(
  progress: Pick<RunProgressSnapshot, "status" | "preparation_updated_at"> | null,
  nowMs: number = Date.now(),
): boolean {
  if (!progress || progress.status !== "preparing") return false;
  const silence = preparationSilenceMs(progress, nowMs);
  return silence != null && silence > PREPARATION_UI_MAX_SILENCE_MS;
}

export const PREPARATION_STAGE_ORDER = [
  "queued",
  "gateway_health",
  "gateway_arango",
  "run_persisted",
  "loading_uc_chunks",
  "materializing_arango",
  "schema_migrations",
  "launching_pipeline",
] as const;

const STATUS_RANK: Record<string, number> = {
  queued: 0,
  preparing: 1,
  running: 2,
  paused: 2,
  completed: 3,
  completed_with_errors: 3,
  failed: 3,
  cancelled: 3,
};

export function preparationStageRank(stage: string | null | undefined): number {
  const normalized =
    STAGE_ALIASES[stage ?? "queued"] ?? stage ?? "queued";
  const idx = PREPARATION_STAGE_ORDER.indexOf(
    normalized as (typeof PREPARATION_STAGE_ORDER)[number],
  );
  return idx >= 0 ? idx : 0;
}

function runStatusRank(status: string): number {
  return STATUS_RANK[status] ?? 0;
}

export function effectiveDisplayStatus(
  progress: Pick<RunProgressSnapshot, "status" | "current_step" | "stats"> | null,
): string {
  if (!progress?.status) return "unknown";
  if (
    (progress.status === "running" || progress.status === "preparing") &&
    !isPreparationComplete(progress)
  ) {
    return "preparing";
  }
  return progress.status;
}

/** Ignore stale polls that regress preparation stage or active run status. */
export function mergeRunProgressSnapshots(
  prev: RunProgressSnapshot | null,
  next: RunProgressSnapshot,
): RunProgressSnapshot {
  if (!prev) return next;
  if (next.status === "failed" || next.status === "cancelled") return next;

  // Stale cache may say "running" with no agent activity — accept a fresher "preparing".
  if (
    prev.status === "running" &&
    next.status === "preparing" &&
    !isPreparationComplete(prev)
  ) {
    return next;
  }

  const prevStage = preparationStageRank(prev.preparation_stage);
  const nextStage = preparationStageRank(next.preparation_stage);
  if (nextStage < prevStage) {
    // Stale in-memory snapshot advanced to launching_pipeline while server still
    // reports gateway / UC / schema stages during prepare_arango.
    if (
      isPrepareArangoAgentActive(prev) ||
      isPrepareArangoAgentActive(next) ||
      !isPreparationComplete(prev)
    ) {
      return {
        ...prev,
        ...next,
        status:
          next.status === "preparing" || !isPreparationComplete(next)
            ? "preparing"
            : prev.status,
        preparation_stage: next.preparation_stage ?? prev.preparation_stage,
        preparation_message: next.preparation_message ?? prev.preparation_message,
        preparation_updated_at:
          next.preparation_updated_at ?? prev.preparation_updated_at,
        preparation_progress: next.preparation_progress ?? prev.preparation_progress,
        stats: {
          ...prev.stats,
          ...next.stats,
          preparation_stage:
            next.preparation_stage ?? next.stats?.preparation_stage ?? prev.preparation_stage,
          preparation_message:
            next.preparation_message ??
            next.stats?.preparation_message ??
            prev.preparation_message,
          preparation_updated_at:
            next.preparation_updated_at ??
            next.stats?.preparation_updated_at ??
            prev.preparation_updated_at,
          preparation_progress:
            next.preparation_progress ??
            next.stats?.preparation_progress ??
            prev.preparation_progress,
          step_logs:
            (next.stats?.step_logs?.length ?? 0) >= (prev.stats?.step_logs?.length ?? 0)
              ? next.stats?.step_logs
              : prev.stats?.step_logs,
          current_step: next.current_step ?? next.stats?.current_step ?? prev.stats?.current_step,
        },
      };
    }
    return prev;
  }

  if (
    runStatusRank(next.status) < runStatusRank(prev.status) &&
    (prev.status === "running" || prev.status === "paused")
  ) {
    return prev;
  }

  const prevLogs = prev.stats?.step_logs?.length ?? 0;
  const nextLogs = next.stats?.step_logs?.length ?? 0;
  if (nextLogs < prevLogs) {
    return {
      ...next,
      stats: {
        ...next.stats,
        step_logs: prev.stats?.step_logs,
      },
    };
  }

  const prevDiag = prev.agent_diagnostics ?? prev.stats?.agent_diagnostics;
  const nextDiag = next.agent_diagnostics ?? next.stats?.agent_diagnostics;
  if (prevDiag && typeof prevDiag === "object" && typeof nextDiag === "object") {
    const prevCalls = Number((prevDiag as Record<string, unknown>).llm_calls ?? 0);
    const nextCalls = Number((nextDiag as Record<string, unknown>).llm_calls ?? 0);
    if (nextCalls < prevCalls) {
      return {
        ...next,
        agent_diagnostics: prev.agent_diagnostics ?? prevDiag,
        stats: {
          ...next.stats,
          agent_diagnostics: prev.stats?.agent_diagnostics ?? prevDiag,
        },
      };
    }
  }

  return next;
}

export interface PreparationProgressDetail {
  phase?: string;
  doc_id?: string;
  doc_index?: number;
  doc_total?: number;
  inserted?: number;
  total?: number;
  batch_size?: number;
  chunk_count?: number;
  embedding_count?: number;
  collections_created?: string[];
  status?: string;
  migration?: string;
  migration_index?: number;
  migration_pending?: number;
  migration_total?: number;
  migration_elapsed_s?: number;
  migration_elapsed_ms?: number;
  migration_ok?: boolean;
  bootstrap?: boolean;
  bootstrap_phase?: string;
  bootstrap_elapsed_ms?: number;
  heartbeat_elapsed_s?: number;
  heartbeat_at?: number;
  heartbeat_seq?: number;
  confirm_run_status?: boolean;
  index_step?: string;
  index_done?: number;
  index_total?: number;
  gateway_ok?: boolean;
  gateway_url?: string;
  gateway_message?: string;
  latency_ms?: number;
  connect_latency_ms?: number;
  arango_verified?: boolean;
  run_status?: string;
  checkpoints?: Array<{
    at: number;
    stage: string;
    ok: boolean;
    message: string;
  }>;
}

export interface RunProgressSnapshot {
  run_id: string;
  status: string;
  started_at?: number | null;
  doc_id?: string | null;
  doc_ids?: string[] | null;
  target_ontology_id?: string | null;
  arango_database?: string | null;
  preparation_stage?: string | null;
  preparation_message?: string | null;
  preparation_updated_at?: number | null;
  preparation_progress?: PreparationProgressDetail | null;
  current_step?: string | null;
  model?: string | null;
  agent_diagnostics?: Record<string, unknown> | null;
  token_usage?: Record<string, number> | null;
  errors?: string[];
  chunk_count?: number;
  /** Raw stats subset when fetched from status endpoint (for DAG step_logs). */
  stats?: {
    step_logs?: unknown[];
    errors?: unknown[];
    agent_diagnostics?: Record<string, unknown>;
    token_usage?: Record<string, number>;
    current_step?: string;
    preparation_stage?: string | null;
    preparation_message?: string | null;
    preparation_updated_at?: number | null;
    preparation_progress?: PreparationProgressDetail | null;
  };
}

export function pickProgress(raw: Record<string, unknown>): RunProgressSnapshot {
  const stats = (raw.stats as Record<string, unknown> | undefined) ?? {};
  const errorsRaw = stats.errors ?? raw.preparation_errors;
  const errors = Array.isArray(errorsRaw)
    ? errorsRaw.map((e) => String(e))
    : [];
  const progressRaw =
    (raw.preparation_progress as Record<string, unknown> | undefined) ??
    (stats.preparation_progress as Record<string, unknown> | undefined);
  const docIdsRaw = raw.doc_ids;
  const docIds = Array.isArray(docIdsRaw)
    ? docIdsRaw.map((id) => String(id))
    : null;
  const agentDiagnosticsRaw =
    (raw.agent_diagnostics as Record<string, unknown> | undefined) ??
    (stats.agent_diagnostics as Record<string, unknown> | undefined);
  const tokenUsageRaw =
    (raw.token_usage as Record<string, number> | undefined) ??
    (stats.token_usage as Record<string, number> | undefined);
  return {
    run_id: String(raw._key ?? ""),
    status: String(raw.status ?? "unknown"),
    started_at: typeof raw.started_at === "number" ? raw.started_at : null,
    doc_id: typeof raw.doc_id === "string" ? raw.doc_id : null,
    doc_ids: docIds,
    target_ontology_id:
      typeof raw.target_ontology_id === "string" ? raw.target_ontology_id : null,
    arango_database:
      typeof raw.arango_database === "string" ? raw.arango_database : null,
    preparation_stage:
      (raw.preparation_stage as string | undefined) ??
      (stats.preparation_stage as string | undefined) ??
      null,
    preparation_message:
      (raw.preparation_message as string | undefined) ??
      (stats.preparation_message as string | undefined) ??
      null,
    preparation_updated_at:
      (raw.preparation_updated_at as number | undefined) ??
      (stats.preparation_updated_at as number | undefined) ??
      null,
    preparation_progress: progressRaw
      ? (progressRaw as PreparationProgressDetail)
      : null,
    current_step:
      (raw.current_step as string | undefined) ??
      (stats.current_step as string | undefined) ??
      null,
    model: typeof raw.model === "string" ? raw.model : null,
    agent_diagnostics: agentDiagnosticsRaw ?? null,
    token_usage: tokenUsageRaw ?? null,
    errors,
    chunk_count: typeof raw.chunk_count === "number" ? raw.chunk_count : undefined,
    stats: {
      step_logs: Array.isArray(stats.step_logs) ? stats.step_logs : undefined,
      errors: Array.isArray(stats.errors) ? stats.errors : undefined,
      agent_diagnostics: agentDiagnosticsRaw,
      token_usage: tokenUsageRaw,
      current_step:
        (stats.current_step as string | undefined) ??
        (raw.current_step as string | undefined),
    },
  };
}

export function isRunStatusPollTimeout(message: string): boolean {
  return /timed out|AbortError|signal timed out/i.test(message);
}
