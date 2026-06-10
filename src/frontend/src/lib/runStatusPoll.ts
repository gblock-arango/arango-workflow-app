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
  materializing_arango: 90_000,
  schema_migrations: 120_000,
  launching_pipeline: 30_000,
};

export const DEFAULT_PREPARATION_STALL_MS = 20_000;

export function preparationStallThresholdMs(
  stage: string | null | undefined,
): number {
  const key = stage ?? "queued";
  return PREPARATION_STALL_MS_BY_STAGE[key] ?? DEFAULT_PREPARATION_STALL_MS;
}

export const PREPARATION_STAGE_ORDER = [
  "queued",
  "gateway_health",
  "gateway_arango",
  "run_persisted",
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

/** Ignore stale polls that regress preparation stage or active run status. */
export function mergeRunProgressSnapshots(
  prev: RunProgressSnapshot | null,
  next: RunProgressSnapshot,
): RunProgressSnapshot {
  if (!prev) return next;
  if (next.status === "failed" || next.status === "cancelled") return next;

  const prevStage = preparationStageRank(prev.preparation_stage);
  const nextStage = preparationStageRank(next.preparation_stage);
  if (nextStage < prevStage) return prev;

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
  doc_id?: string | null;
  doc_ids?: string[] | null;
  target_ontology_id?: string | null;
  arango_database?: string | null;
  preparation_stage?: string | null;
  preparation_message?: string | null;
  preparation_updated_at?: number | null;
  preparation_progress?: PreparationProgressDetail | null;
  current_step?: string | null;
  errors?: string[];
  chunk_count?: number;
  /** Raw stats subset when fetched from status endpoint (for DAG step_logs). */
  stats?: {
    step_logs?: unknown[];
    errors?: unknown[];
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
  return {
    run_id: String(raw._key ?? ""),
    status: String(raw.status ?? "unknown"),
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
    errors,
    chunk_count: typeof raw.chunk_count === "number" ? raw.chunk_count : undefined,
    stats: {
      step_logs: Array.isArray(stats.step_logs) ? stats.step_logs : undefined,
      errors: Array.isArray(stats.errors) ? stats.errors : undefined,
    },
  };
}

export function isRunStatusPollTimeout(message: string): boolean {
  return /timed out|AbortError|signal timed out/i.test(message);
}
