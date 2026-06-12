import {
  parseReadyResponse,
  stripLatencyFromDetail,
} from "@/lib/useArangoConnectionStatus";

describe("stripLatencyFromDetail", () => {
  it("removes trailing ms segment from gateway detail", () => {
    expect(
      stripLatencyFromDetail("Arango 3.12.4 · local-minikube-dev · 258ms"),
    ).toBe("Arango 3.12.4 · local-minikube-dev");
  });

  it("removes standalone ms segment", () => {
    expect(stripLatencyFromDetail("145ms")).toBe("");
  });
});

describe("parseReadyResponse", () => {
  it("returns unset with Click to Connect when no profiles saved", () => {
    const result = parseReadyResponse({
      status: "not_ready",
      connection: { ui_variant: "unset", ui_message: "Click to Connect" },
    });
    expect(result.health).toBe("unset");
    expect(result.healthDetail).toBe("Click to Connect");
  });

  it("returns failed with Connection Failed when profile saved but not connected", () => {
    const result = parseReadyResponse({
      status: "not_ready",
      connection: {
        ui_variant: "failed",
        ui_message: "Connection Failed",
        active_profile_display_name: "AWS Prod",
      },
    });
    expect(result.health).toBe("failed");
    expect(result.healthDetail).toBe("Connection Failed");
    expect(result.profileName).toBe("AWS Prod");
  });

  it("returns connected with profile display name and connection meta", () => {
    const result = parseReadyResponse({
      status: "ready",
      connection: {
        ui_variant: "connected",
        ui_message: "AWS Production",
        active_profile_display_name: "AWS Production",
      },
      probe: {
        status: "ok",
        details: { response_preview: '{"version":"3.12.4"}' },
      },
      registry: { status: "ok", cluster_name: "aws-prod" },
    });
    expect(result.health).toBe("connected");
    expect(result.profileName).toBe("AWS Production");
    expect(result.connectionMeta).toBe("Arango 3.12.4 | aws-prod");
  });
});
