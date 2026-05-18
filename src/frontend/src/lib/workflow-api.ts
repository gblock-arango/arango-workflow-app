import { withBasePath } from "@/lib/base-path";

export interface WorkflowConfig {
  dashboard_title: string;
  arango_ui_embed_iframe_src: string;
  arango_gateway_registry_table: string;
  uc_graph_snapshot_base: string;
  gateway_base_url: string;
}

export async function fetchWorkflowConfig(): Promise<WorkflowConfig> {
  const res = await fetch(withBasePath("/api/workflow/config"));
  if (!res.ok) {
    throw new Error(`Failed to load workflow config (${res.status})`);
  }
  return res.json() as Promise<WorkflowConfig>;
}

export function gatewayApi(gatewayBase: string, path: string): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  if (!gatewayBase) return p;
  return `${gatewayBase.replace(/\/$/, "")}${p}`;
}

export async function postWorkflowChat(
  agent: "genie" | "mcp" | "ada",
  body: Record<string, unknown>,
): Promise<Response> {
  const path =
    agent === "ada"
      ? "/api/workflow/arango/chat"
      : agent === "mcp"
        ? "/api/workflow/genie-mcp/chat"
        : "/api/workflow/genie/chat";
  return fetch(withBasePath(path), {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify(body),
  });
}
