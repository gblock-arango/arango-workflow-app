import {
  LLM_STATUS_POLL_FAIL_MS,
  LLM_STATUS_POLL_OK_MS,
} from "@/lib/useLlmConnectivityStatus";

describe("LLM connectivity poll intervals", () => {
  it("uses 10s when last probe succeeded", () => {
    expect(LLM_STATUS_POLL_OK_MS).toBe(10_000);
  });

  it("uses 1s when last probe failed", () => {
    expect(LLM_STATUS_POLL_FAIL_MS).toBe(1_000);
  });
});
