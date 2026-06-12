/** Step 1: Diagnostics must expose gateway checkpoint stages (not legacy labels). */
import { readFileSync } from "fs";
import path from "path";

import { PREPARATION_STAGE_ORDER } from "@/lib/runStatusPoll";

describe("PREPARATION_STAGE_ORDER", () => {
  it("includes gateway checkpoint stages before materialize", () => {
    expect(PREPARATION_STAGE_ORDER).toEqual([
      "queued",
      "worker_auth",
      "langgraph_startup",
      "gateway_health",
      "gateway_arango",
      "run_persisted",
      "loading_uc_chunks",
      "materializing_arango",
      "schema_migrations",
      "launching_pipeline",
    ]);
  });
});

describe("PipelineDiagnosticsPanel source", () => {
  it("documents Gateway /health step in source", () => {
    const src = readFileSync(
      path.join(__dirname, "../../components/pipeline/PipelineDiagnosticsPanel.tsx"),
      "utf-8",
    );
    expect(src).toContain("gateway_health");
    expect(src).toContain("Gateway /health");
    expect(src).toContain("worker_auth");
    expect(src).toContain("langgraph_startup");
    expect(src).not.toContain('label: "Worker started"');
  });

  it("does not embed home-page Connection to Arango / useArangoConnectionStatus", () => {
    const src = readFileSync(
      path.join(__dirname, "../../components/pipeline/PipelineDiagnosticsPanel.tsx"),
      "utf-8",
    );
    expect(src).not.toContain("useArangoConnectionStatus");
    expect(src).not.toContain("Connection to Arango");
    expect(src).not.toMatch(/children:\s*"Arango gateway"/);
  });
});

describe("static export (when built)", () => {
  it("includes gateway_health and omits ConnectionStatus when frontend was rebuilt", () => {
    const outPipeline = path.join(__dirname, "../../out/_next/static/chunks/app/pipeline");
    let files: string[];
    try {
      files = require("fs").readdirSync(outPipeline) as string[];
    } catch {
      return; // out/ not built — source tests above are the gate
    }
    const bundle = files.find((f) => f.startsWith("page-") && f.endsWith(".js"));
    if (!bundle) return;
    const js = readFileSync(path.join(outPipeline, bundle), "utf-8");
    expect(js).toContain("gateway_health");
    expect(js).not.toMatch(/children:\s*"Arango gateway"/);
  });
});
