"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  fetchWorkflowConfig,
  gatewayApi,
  postWorkflowChat,
  type WorkflowConfig,
} from "@/lib/workflow-api";
import { withBasePath } from "@/lib/base-path";
import { wf } from "./wf-classes";
import { useWorkflowShellStyles } from "./useWorkflowShellStyles";

type ShellTab =
  | "platform"
  | "workspace"
  | "pipeline"
  | "upload"
  | "library"
  | "curation"
  | "quality";

const ONTO_TABS: { key: ShellTab; label: string; href: string }[] = [
  { key: "workspace", label: "Workspace", href: "/workspace" },
  { key: "pipeline", label: "Pipeline", href: "/pipeline" },
  { key: "upload", label: "Upload", href: "/upload" },
  { key: "library", label: "Library", href: "/library" },
  { key: "curation", label: "Curation", href: "/curation" },
  { key: "quality", label: "Quality", href: "/dashboard" },
];

type AgentType = "genie" | "mcp" | "ada";

function useProgress() {
  const [pct, setPct] = useState(0);
  const reset = useCallback(() => setPct(0), []);
  const complete = useCallback(() => {
    setPct(100);
    window.setTimeout(() => setPct(0), 2600);
  }, []);
  const simulate = useCallback(() => {
    setPct(1);
    let p = 1;
    const id = window.setInterval(() => {
      if (p < 90) p += 1.2 + Math.random() * 5;
      setPct(Math.min(90, Math.floor(p)));
    }, 150);
    return () => window.clearInterval(id);
  }, []);
  return { pct, setPct, reset, complete, simulate };
}

function ProgressBar({ pct }: { pct: number }) {
  return (
    <div className={wf.dgProgress} aria-valuenow={pct} role="progressbar">
      <div
        className={wf.dgProgressFill}
        style={{ width: `${pct}%` }}
      />
      <span className={wf.dgProgressLabel}>{pct}%</span>
    </div>
  );
}

export default function WorkflowShell() {
  useWorkflowShellStyles();

  const [activeTab, setActiveTab] = useState<ShellTab>("platform");
  const [config, setConfig] = useState<WorkflowConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);

  useEffect(() => {
    fetchWorkflowConfig()
      .then(setConfig)
      .catch((e: Error) => setConfigError(e.message));
  }, []);

  const embedSrc = config?.arango_ui_embed_iframe_src ?? "";
  const gatewayBase = config?.gateway_base_url ?? "";
  const ucSnapshotBase = config?.uc_graph_snapshot_base ?? "";

  const ontoFrameSrc = useMemo(() => {
    const tab = ONTO_TABS.find((t) => t.key === activeTab);
    return tab ? withBasePath(tab.href) : "";
  }, [activeTab]);

  return (
    <div className={wf.page}>
      <header className={wf.header}>
        <Image
          className={wf.headerLogo}
          src={withBasePath("/images/arango-logo-cropped.png")}
          alt="ArangoDB"
          width={200}
          height={44}
          priority
        />
        <h1 className={wf.headerTitle}>
          {config?.dashboard_title ??
            "Arango on Databricks: Context Changes Everything"}
        </h1>
        <Image
          className={wf.headerMascot}
          src={withBasePath("/images/arangoai-mascot.png")}
          alt=""
          width={156}
          height={68}
          aria-hidden
        />
      </header>

      <nav className={wf.tabBar} aria-label="Workflow sections">
        <button
          type="button"
          className={`${wf.tab} ${activeTab === "platform" ? wf.tabActive : ""}`}
          onClick={() => setActiveTab("platform")}
        >
          Platform
        </button>
        {ONTO_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`${wf.tab} ${activeTab === t.key ? wf.tabActive : ""}`}
            onClick={() => setActiveTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        <Link href={withBasePath("/")} className={wf.tab} style={{ marginLeft: "auto" }}>
          OntoExtract home
        </Link>
      </nav>

      {configError && (
        <p className={wf.dgStatus} style={{ color: "#f87171" }}>
          Config error: {configError}
        </p>
      )}

      <div className={wf.body}>
        {activeTab === "platform" ? (
          <PlatformView
            embedSrc={embedSrc}
            gatewayBase={gatewayBase}
            ucSnapshotBase={ucSnapshotBase}
            registryTable={config?.arango_gateway_registry_table ?? ""}
          />
        ) : (
          <iframe
            title={`OntoExtract ${activeTab}`}
            className={wf.embedFrame}
            src={ontoFrameSrc}
          />
        )}
      </div>
    </div>
  );
}

function PlatformView({
  embedSrc,
  gatewayBase,
  ucSnapshotBase,
  registryTable,
}: {
  embedSrc: string;
  gatewayBase: string;
  ucSnapshotBase: string;
  registryTable: string;
}) {
  const [status, setStatus] = useState("");
  const schemaProgress = useProgress();
  const docsProgress = useProgress();
  const corpusProgress = useProgress();

  const [agentType, setAgentType] = useState<AgentType>("genie");
  const [prompt, setPrompt] = useState("");
  const [reply, setReply] = useState("");
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [chatBusy, setChatBusy] = useState(false);

  const [ucModalOpen, setUcModalOpen] = useState(false);
  const [docModalOpen, setDocModalOpen] = useState(false);

  const buildExtractPayload = useCallback(
    (extra?: Record<string, unknown>) => {
      const payload: Record<string, unknown> = {
        ...(extra ?? {}),
        stream_progress: true,
      };
      if (ucSnapshotBase) {
        payload.jsonl_export = {
          volume_base_path: ucSnapshotBase,
          use_staging_directory: true,
          include_graph_in_response: false,
        };
      }
      return payload;
    },
    [ucSnapshotBase],
  );

  const runExtractSchema = useCallback(
    async (extra?: Record<string, unknown>) => {
      schemaProgress.reset();
      const stopSim = schemaProgress.simulate();
      setStatus("Extracting schema… (UC → manifest / JSONL → Arango)");
      try {
        const res = await fetch(
          gatewayApi(gatewayBase, "/api/databricks-graph/extract-schema"),
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Accept: "application/x-ndjson",
            },
            body: JSON.stringify(buildExtractPayload(extra)),
          },
        );
        if (!res.ok || !res.body) {
          throw new Error(await res.text());
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed) continue;
            const ev = JSON.parse(trimmed) as {
              event?: string;
              pct?: number;
              result?: {
                summary?: { node_count?: number; edge_count?: number; tables_scanned?: number };
                message?: string;
              };
              error?: string;
            };
            if (ev.event === "manifest_ready") schemaProgress.setPct(20);
            if (ev.event === "arango_progress")
              schemaProgress.setPct(Math.round(Number(ev.pct) || 0));
            if (ev.event === "done") {
              schemaProgress.complete();
              const s = ev.result?.summary;
              setStatus(
                s
                  ? `nodes ${s.node_count}, edges ${s.edge_count}, tables ${s.tables_scanned}`
                  : ev.result?.message ?? "Done.",
              );
            }
            if (ev.event === "error") {
              schemaProgress.reset();
              setStatus(ev.error ?? "Request failed");
            }
          }
        }
      } catch (e) {
        schemaProgress.reset();
        setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        stopSim();
      }
    },
    [gatewayBase, buildExtractPayload, schemaProgress],
  );

  const sendChat = useCallback(async () => {
    const text = prompt.trim();
    if (!text) return;
    setChatBusy(true);
    setReply(
      agentType === "genie"
        ? "Waiting for Genie…"
        : agentType === "mcp"
          ? "Waiting for MCP…"
          : "Waiting for ADA…",
    );
    const body: Record<string, unknown> = { content: text };
    if (conversationId) body.conversation_id = conversationId;
    try {
      const res = await postWorkflowChat(agentType, body);
      const j = (await res.json()) as {
        ok?: boolean;
        error?: string;
        conversation_id?: string;
        message?: { content?: string };
        tools_invoked?: string[];
      };
      if (j.ok && j.message) {
        setConversationId(j.conversation_id ?? conversationId);
        let out = String(j.message.content ?? JSON.stringify(j.message, null, 2));
        if (agentType === "mcp" && j.tools_invoked?.length) {
          out += `\n\n[MCP tools: ${j.tools_invoked.join(", ")}]`;
        }
        setReply(out);
      } else {
        setReply(`Error: ${j.error ?? `HTTP ${res.status}`}`);
      }
    } catch (e) {
      setReply(`Error: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setChatBusy(false);
    }
  }, [agentType, conversationId, prompt]);

  return (
    <div className={wf.widgets}>
      <section className={`${wf.widget} ${wf.widgetChromeless}`}>
        <div className={wf.iframeWrap}>
          {embedSrc ? (
            <iframe title="ArangoDB web interface" src={embedSrc} />
          ) : (
            <div className={wf.iframePlaceholder} role="status">
              <div>
                No Arango UI URL available. Set <code>ARANGO_GATEWAY_BASE_URL</code> or ensure{" "}
                <code>{registryTable || "ARANGO_GATEWAY_REGISTRY_TABLE"}</code> has an active row.
              </div>
            </div>
          )}
        </div>
      </section>

      <aside className={wf.widgetsRight}>
        <section className={wf.widget}>
          <h2>Databricks Graph</h2>
          <div className={wf.dgActions}>
            <div className={wf.dgActionRow}>
              <button type="button" className={wf.dgBtn} onClick={() => setUcModalOpen(true)}>
                Select Tables and Extract Schema
              </button>
              <ProgressBar pct={schemaProgress.pct} />
            </div>
            <div className={wf.dgActionRow}>
              <button type="button" className={wf.dgBtn} onClick={() => setDocModalOpen(true)}>
                Add Your Documents
              </button>
              <ProgressBar pct={docsProgress.pct} />
            </div>
            <div className={wf.dgActionRow}>
              <button
                type="button"
                className={wf.dgBtn}
                onClick={async () => {
                  corpusProgress.reset();
                  const stop = corpusProgress.simulate();
                  setStatus("Starting corpus graph build…");
                  try {
                    const res = await fetch(
                      gatewayApi(gatewayBase, "/api/databricks-graph/build-corpus-graphs"),
                      {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: "{}",
                      },
                    );
                    const j = (await res.json()) as { message?: string; error?: string };
                    setStatus(j.message ?? j.error ?? (res.ok ? "Done." : "Failed"));
                    corpusProgress.complete();
                  } catch (e) {
                    corpusProgress.reset();
                    setStatus(`Error: ${e instanceof Error ? e.message : String(e)}`);
                  } finally {
                    stop();
                  }
                }}
              >
                Build Corpus Graphs
              </button>
              <ProgressBar pct={corpusProgress.pct} />
            </div>
          </div>
          <p className={wf.dgStatus}>{status}</p>
        </section>

        <section className={wf.widget}>
          <div className={wf.genieHeadingRow}>
            <h2>Arango AI: Graph-Enabled Genie</h2>
            <label>
              <span style={{ marginRight: 8, fontSize: "0.8125rem" }}>Agent type</span>
              <select
                value={agentType}
                onChange={(e) => {
                  setAgentType(e.target.value as AgentType);
                  setConversationId(null);
                  setReply("");
                }}
              >
                <option value="genie">Genie</option>
                <option value="mcp">MCP</option>
                <option value="ada">ADA</option>
              </select>
            </label>
          </div>
          <div className={wf.genieStack}>
            <div className={wf.geniePanes}>
              <div className={wf.geniePaneOutput}>
                <label className={wf.dgStatus}>Response</label>
                <textarea
                  className={`${wf.genieTextarea} ${wf.genieOutput}`}
                  readOnly
                  value={reply}
                  placeholder="Agent replies appear here."
                />
              </div>
              <div className={wf.geniePaneInput}>
                <label className={wf.dgStatus}>Your question</label>
                <textarea
                  className={wf.genieTextarea}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      void sendChat();
                    }
                  }}
                />
              </div>
            </div>
            <div className={wf.genieActions}>
              <button
                type="button"
                className={wf.dgBtn}
                disabled={chatBusy}
                onClick={() => void sendChat()}
              >
                Send
              </button>
              <button
                type="button"
                className={wf.genieSecondary}
                disabled={chatBusy}
                onClick={() => {
                  setConversationId(null);
                  setReply("");
                }}
              >
                New conversation
              </button>
            </div>
          </div>
        </section>
      </aside>

      {ucModalOpen && (
        <UcTablesModal
          gatewayBase={gatewayBase}
          onClose={() => setUcModalOpen(false)}
          onExtract={(sel) => {
            setUcModalOpen(false);
            void runExtractSchema(sel);
          }}
        />
      )}

      {docModalOpen && (
        <DocumentsModal
          gatewayBase={gatewayBase}
          onClose={() => setDocModalOpen(false)}
          onStatus={setStatus}
          onProgress={(pct) => docsProgress.setPct(pct)}
        />
      )}
    </div>
  );
}

function UcTablesModal({
  gatewayBase,
  onClose,
  onExtract,
}: {
  gatewayBase: string;
  onClose: () => void;
  onExtract: (payload: { table_ids: string[]; table_full_names: string[] }) => void;
}) {
  const [rows, setRows] = useState<
    { table_id: string; full_name: string; checked?: boolean }[]
  >([]);
  const [msg, setMsg] = useState("Loading…");

  useEffect(() => {
    fetch(gatewayApi(gatewayBase, "/api/databricks-graph/uc-tables"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then((r) => r.json())
      .then((j: { tables?: { table_id: string; full_name: string }[]; error?: string }) => {
        if (j.error) {
          setMsg(j.error);
          return;
        }
        setRows((j.tables ?? []).map((t) => ({ ...t, checked: false })));
        setMsg(`${(j.tables ?? []).length} tables from UC`);
      })
      .catch((e: Error) => setMsg(e.message));
  }, [gatewayBase]);

  return (
    <div className={wf.modalBackdrop} onClick={onClose}>
      <div className={wf.modalPanel} onClick={(e) => e.stopPropagation()}>
        <h3>Select Unity Catalog tables</h3>
        <p className={wf.dgStatus}>{msg}</p>
        <div style={{ maxHeight: 320, overflowY: "auto", marginBottom: 12 }}>
          {rows.map((row, i) => (
            <label key={`${row.table_id}-${i}`} style={{ display: "flex", gap: 8, padding: 6 }}>
              <input
                type="checkbox"
                checked={!!row.checked}
                onChange={(e) => {
                  setRows((prev) =>
                    prev.map((r, j) => (j === i ? { ...r, checked: e.target.checked } : r)),
                  );
                }}
              />
              <span>
                <strong>{row.full_name}</strong>
                <br />
                <code style={{ fontSize: "0.72rem" }}>{row.table_id}</code>
              </span>
            </label>
          ))}
        </div>
        <div className={wf.modalActions}>
          <button type="button" className={wf.genieSecondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={wf.dgBtnInline}
            onClick={() => {
              const selected = rows.filter((r) => r.checked);
              onExtract({
                table_ids: selected.map((r) => r.table_id).filter(Boolean),
                table_full_names: selected.map((r) => r.full_name).filter(Boolean),
              });
            }}
          >
            Extract selected
          </button>
        </div>
      </div>
    </div>
  );
}

function DocumentsModal({
  gatewayBase,
  onClose,
  onStatus,
  onProgress,
}: {
  gatewayBase: string;
  onClose: () => void;
  onStatus: (s: string) => void;
  onProgress: (pct: number) => void;
}) {
  const [files, setFiles] = useState<File[]>([]);

  const upload = async () => {
    if (!files.length) return;
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f));
    onProgress(0);
    try {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", gatewayApi(gatewayBase, "/api/databricks-graph/documents"));
      xhr.upload.onprogress = (ev) => {
        if (ev.lengthComputable && ev.total > 0) {
          onProgress(Math.round((100 * ev.loaded) / ev.total));
        }
      };
      await new Promise<void>((resolve, reject) => {
        xhr.onload = () => {
          onProgress(100);
          try {
            const j = JSON.parse(xhr.responseText || "{}") as { message?: string; error?: string };
            onStatus(j.message ?? j.error ?? "Upload complete.");
          } catch {
            onStatus("Upload complete.");
          }
          resolve();
        };
        xhr.onerror = () => reject(new Error("Network error"));
        xhr.send(fd);
      });
      onClose();
    } catch (e) {
      onProgress(0);
      onStatus(`Upload error: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div className={wf.modalBackdrop} onClick={onClose}>
      <div className={wf.modalPanel} onClick={(e) => e.stopPropagation()}>
        <h3>Add your documents</h3>
        <input
          type="file"
          multiple
          accept=".pdf,.txt,.md"
          onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
        />
        <p className={wf.dgStatus}>
          {files.length ? `${files.length} file(s) selected` : "PDF, TXT, or Markdown"}
        </p>
        <div className={wf.modalActions}>
          <button type="button" className={wf.genieSecondary} onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className={wf.dgBtnInline}
            disabled={!files.length}
            onClick={() => void upload()}
          >
            Upload
          </button>
        </div>
      </div>
    </div>
  );
}
