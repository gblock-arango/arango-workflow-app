import {
  computeLlmCallsPerMinute,
  countRunningAgents,
  isAgentPhase,
  pickAgentDiagnostics,
} from "@/lib/agentDiagnostics";
import { mergeRunProgressSnapshots, pickProgress } from "@/lib/runStatusPoll";
import type { StepStatus } from "@/types/pipeline";

describe("isAgentPhase", () => {
  it("is true when status is running", () => {
    expect(isAgentPhase({ status: "running" })).toBe(true);
  });

  it("is false when status is preparing", () => {
    expect(isAgentPhase({ status: "preparing" })).toBe(false);
  });
});

describe("pickProgress agent fields", () => {
  it("includes agent_diagnostics from status payload", () => {
    const snap = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      stats: {
        agent_diagnostics: { llm_calls: 4, prompt_tokens: 800 },
        step_logs: [{ step: "extractor", status: "running" }],
      },
    });
    expect(pickAgentDiagnostics(snap)?.llm_calls).toBe(4);
    expect(snap.stats?.step_logs).toHaveLength(1);
  });
});

describe("computeLlmCallsPerMinute", () => {
  it("computes rate from agent start time", () => {
    const startedAt = Date.now() / 1000 - 120;
    const rate = computeLlmCallsPerMinute(12, startedAt, Date.now());
    expect(rate).not.toBeNull();
    expect(rate!).toBeGreaterThan(5);
    expect(rate!).toBeLessThan(7);
  });
});

describe("countRunningAgents", () => {
  it("prefers websocket step map", () => {
    const steps = new Map<string, StepStatus>([
      ["extractor", { status: "running" }],
      ["quality_judge", { status: "pending" }],
    ]);
    expect(
      countRunningAgents({ run_id: "r", status: "running", stats: {} }, steps),
    ).toBe(1);
  });
});

describe("mergeRunProgressSnapshots", () => {
  it("does not regress llm call counters", () => {
    const prev = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      stats: { agent_diagnostics: { llm_calls: 10 } },
    });
    const next = pickProgress({
      _key: "run_abc123def456",
      status: "running",
      stats: { agent_diagnostics: { llm_calls: 3 } },
    });
    const merged = mergeRunProgressSnapshots(prev, next);
    expect(pickAgentDiagnostics(merged)?.llm_calls).toBe(10);
  });
});
