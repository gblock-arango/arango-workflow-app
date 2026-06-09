import {
  stripLatencyFromDetail,
} from "@/lib/useArangoConnectionStatus";

// parseReadyResponse is not exported — exercise via stripLatency and document expected /ready shapes in backend tests.

describe("stripLatencyFromDetail", () => {
  it("removes trailing ms segment from gateway detail", () => {
    expect(
      stripLatencyFromDetail("Arango 3.12.4 · local-minikube-dev · 258ms"),
    ).toBe("Arango 3.12.4 · local-minikube-dev");
  });

  it("removes standalone ms segment", () => {
    expect(stripLatencyFromDetail("145ms")).toBe("");
  });

  it("leaves detail unchanged when no ms segment", () => {
    expect(stripLatencyFromDetail("Arango 3.12.4 · local-minikube-dev")).toBe(
      "Arango 3.12.4 · local-minikube-dev",
    );
  });

  it("does not strip probe error messages", () => {
    expect(stripLatencyFromDetail("probe=error, registry=error")).toBe(
      "probe=error, registry=error",
    );
  });
});
