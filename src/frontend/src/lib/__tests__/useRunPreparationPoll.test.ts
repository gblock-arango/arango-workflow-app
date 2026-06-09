import { pickProgress } from "@/lib/runStatusPoll";

describe("pickProgress", () => {
  it("flattens preparation fields from stats", () => {
    const snap = pickProgress({
      _key: "run_abc",
      status: "preparing",
      stats: {
        preparation_stage: "materializing_arango",
        preparation_message: "insert 10/50",
        preparation_updated_at: 100,
        preparation_progress: { inserted: 10, total: 50 },
        errors: ["err1"],
      },
    });
    expect(snap.run_id).toBe("run_abc");
    expect(snap.preparation_stage).toBe("materializing_arango");
    expect(snap.preparation_message).toBe("insert 10/50");
    expect(snap.preparation_progress?.inserted).toBe(10);
    expect(snap.errors).toEqual(["err1"]);
  });
});
