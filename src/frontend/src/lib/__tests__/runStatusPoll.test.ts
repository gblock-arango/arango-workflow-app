import {
  effectiveDisplayStatus,
  effectivePreparationStage,
  isPreparationBlocked,
  isPreparationComplete,
  isSchemaBootstrapComplete,
  mergeRunProgressSnapshots,
  pickProgress,
  preparationStageRank,
  preparationStallThresholdMs,
} from "@/lib/runStatusPoll";

describe("mergeRunProgressSnapshots", () => {
  it("ignores a stale poll that regresses preparation stage", () => {
    const prev = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "launching_pipeline",
      preparation_message: "starting agents",
    });
    const stale = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      preparation_stage: "queued",
      preparation_message: "Queued — will copy UC chunks",
      preparation_updated_at: 1,
    });
    const merged = mergeRunProgressSnapshots(prev, stale);
    expect(merged.preparation_stage).toBe("launching_pipeline");
    expect(merged.status).toBe("running");
  });
});

describe("pickProgress", () => {
  it("includes document ids from status payload", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      doc_id: "doc_a",
      doc_ids: ["doc_a", "doc_b"],
      target_ontology_id: "onto_1",
    });
    expect(snap.doc_ids).toEqual(["doc_a", "doc_b"]);
    expect(snap.doc_id).toBe("doc_a");
    expect(snap.target_ontology_id).toBe("onto_1");
  });
});

describe("isPreparationComplete", () => {
  it("does not treat bare running status as complete", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "materializing_arango",
    });
    expect(isPreparationComplete(snap)).toBe(false);
  });

  it("does not treat prepare_arango agent step as preparation complete", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "gateway_health",
      current_step: "prepare_arango",
    });
    expect(isPreparationComplete(snap)).toBe(false);
  });

  it("treats running past prepare_arango as complete", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "launching_pipeline",
      current_step: "extraction_agent",
    });
    expect(isPreparationComplete(snap)).toBe(true);
  });
});

describe("mergeRunProgressSnapshots stale stage during prepare_arango", () => {
  it("accepts a lower preparation stage when prev snapshot over-advanced", () => {
    const prev = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "launching_pipeline",
      current_step: "prepare_arango",
      stats: {
        step_logs: [{ step: "prepare_arango", status: "running" }],
      },
    });
    const next = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      preparation_stage: "loading_uc_chunks",
      preparation_message: "(1/1) Loading chunks from UC volume",
    });
    const merged = mergeRunProgressSnapshots(prev, next);
    expect(merged.preparation_stage).toBe("loading_uc_chunks");
    expect(merged.status).toBe("preparing");
    expect(isPreparationComplete(merged)).toBe(false);
  });
});

describe("effectiveDisplayStatus", () => {
  it("shows preparing while prepare_arango is active even if status is running", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "gateway_arango",
      current_step: "prepare_arango",
    });
    expect(effectiveDisplayStatus(snap)).toBe("preparing");
  });
});

describe("mergeRunProgressSnapshots cancelled", () => {
  it("accepts cancelled status from a fresh poll", () => {
    const prev = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      preparation_stage: "launching_pipeline",
    });
    const cancelled = pickProgress({
      _key: "run_abc123def456",
      status: "cancelled",
      preparation_message: "Cancelled by user",
    });
    expect(mergeRunProgressSnapshots(prev, cancelled).status).toBe("cancelled");
  });
});

describe("preparationStallThresholdMs", () => {
  it("allows longer stalls for gateway-heavy stages", () => {
    expect(preparationStallThresholdMs("run_persisted")).toBeGreaterThan(60_000);
    expect(preparationStallThresholdMs("gateway_health")).toBeGreaterThan(60_000);
    expect(preparationStallThresholdMs("worker_auth")).toBe(90_000);
    expect(preparationStallThresholdMs("langgraph_startup")).toBe(120_000);
    expect(preparationStallThresholdMs("queued")).toBe(20_000);
  });
});

describe("preparationStageRank", () => {
  it("orders known preparation stages", () => {
    expect(preparationStageRank("queued")).toBeLessThan(
      preparationStageRank("worker_auth"),
    );
    expect(preparationStageRank("worker_auth")).toBeLessThan(
      preparationStageRank("langgraph_startup"),
    );
    expect(preparationStageRank("langgraph_startup")).toBeLessThan(
      preparationStageRank("gateway_health"),
    );
    expect(preparationStageRank("gateway_health")).toBeLessThan(
      preparationStageRank("launching_pipeline"),
    );
  });
});

describe("isSchemaBootstrapComplete", () => {
  it("detects bootstrap completion from progress and message", () => {
    expect(
      isSchemaBootstrapComplete({
        preparation_message: "Batch schema bootstrap complete (17 doc + 13 edge, 3m 25s)",
        preparation_progress: { bootstrap_phase: "complete" },
      }),
    ).toBe(true);
    expect(
      isSchemaBootstrapComplete({
        preparation_message: "Persisting schema migration state…",
        preparation_progress: { bootstrap_phase: "persist" },
      }),
    ).toBe(true);
  });
});

describe("effectivePreparationStage", () => {
  it("advances UI past schema when bootstrap finished but status is still preparing", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      preparation_stage: "schema_migrations",
      preparation_message: "Batch schema bootstrap complete (17 doc + 13 edge, 3m 25s)",
      preparation_progress: { bootstrap_phase: "complete" },
    });
    expect(effectivePreparationStage(snap)).toBe("launching_pipeline");
  });
});

describe("isPreparationBlocked", () => {
  it("flags blocked when server silence exceeds 15s during preparing", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      preparation_updated_at: Date.now() / 1000 - 20,
    });
    expect(isPreparationBlocked(snap, Date.now())).toBe(true);
  });

  it("does not flag blocked when heartbeat is fresh", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "preparing",
      preparation_updated_at: Date.now() / 1000 - 5,
    });
    expect(isPreparationBlocked(snap, Date.now())).toBe(false);
  });
});
