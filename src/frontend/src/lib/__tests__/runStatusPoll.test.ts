import {
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
    expect(preparationStallThresholdMs("queued")).toBe(20_000);
  });
});

describe("preparationStageRank", () => {
  it("orders known preparation stages", () => {
    expect(preparationStageRank("queued")).toBeLessThan(
      preparationStageRank("launching_pipeline"),
    );
  });
});
