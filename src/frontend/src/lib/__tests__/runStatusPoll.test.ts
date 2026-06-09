import {
  mergeRunProgressSnapshots,
  pickProgress,
  preparationStageRank,
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

describe("preparationStageRank", () => {
  it("orders known preparation stages", () => {
    expect(preparationStageRank("queued")).toBeLessThan(
      preparationStageRank("launching_pipeline"),
    );
  });
});
