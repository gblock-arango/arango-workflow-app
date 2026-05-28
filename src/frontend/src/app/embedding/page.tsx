"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, apiFetch, LONG_RUNNING_API_TIMEOUT_MS } from "@/lib/api-client";
import AppHeader from "@/components/layout/AppHeader";
import AppLink from "@/components/layout/AppLink";
import LlmConnectivityBadge from "@/components/layout/LlmConnectivityBadge";
import { getUploadFileKind } from "@/lib/fileAccept";
import { scheduleAfterInitialPaint } from "@/lib/scheduleAfterInitialPaint";

interface EmbeddingStatusRow {
  doc_id: string;
  filename: string;
  mime_type: string;
  volume_relative_path: string;
  file_size_bytes: number;
  status: string;
  parsed: boolean;
  chunked: boolean;
  embedded: boolean;
  chunk_count: number;
  error_message?: string | null;
}

interface UploadRow {
  rowKey: string;
  docId: string;
  displayName: string;
  filepath: string;
  sizeKb: number;
  parsed: boolean;
  chunked: boolean;
  embedded: boolean;
  status: string;
  error_message?: string | null;
}

type PipelineStage = "parse" | "chunk" | "embed";

const ACTIVE_STATUSES = new Set([
  "uploading",
  "parsing",
  "chunking",
  "embedding",
]);

function rowFlags(row: EmbeddingStatusRow) {
  const status = row.status;
  return {
    parsed:
      row.parsed ||
      ["parsed", "chunking", "chunked", "embedding", "ready"].includes(status),
    chunked:
      row.chunked ||
      ["chunked", "embedding", "ready"].includes(status) ||
      row.chunk_count > 0,
    embedded: row.embedded || status === "ready",
  };
}

function statusRowsToUploadRows(rows: EmbeddingStatusRow[]): UploadRow[] {
  return rows
    .filter((r) => getUploadFileKind(r.filename) === "document")
    .map((r) => {
      const flags = rowFlags(r);
      return {
        rowKey: r.doc_id,
        docId: r.doc_id,
        displayName: r.filename,
        filepath: r.volume_relative_path,
        sizeKb: Math.round((r.file_size_bytes || 0) / 1024),
        parsed: flags.parsed,
        chunked: flags.chunked,
        embedded: flags.embedded,
        status: r.status,
        error_message: r.error_message,
      };
    })
    .sort((a, b) => a.displayName.localeCompare(b.displayName));
}

export default function EmbeddingPage() {
  return (
    <Suspense
      fallback={
        <main className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-500">
          Loading…
        </main>
      }
    >
      <EmbeddingPageInner />
    </Suspense>
  );
}

function EmbeddingPageInner() {
  const searchParams = useSearchParams();
  const docFromUrl = searchParams.get("doc");

  const [statusRows, setStatusRows] = useState<EmbeddingStatusRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set());
  const [stageProgress, setStageProgress] = useState<Record<PipelineStage, number>>({
    parse: 0,
    chunk: 0,
    embed: 0,
  });
  const [activeStage, setActiveStage] = useState<PipelineStage | null>(null);
  const cancelRef = useRef(false);

  const loadStatus = useCallback(async () => {
    try {
      const res = await api.get<{ data: EmbeddingStatusRow[] }>(
        "/api/v1/embedding/status?limit=500",
        { timeoutMs: LONG_RUNNING_API_TIMEOUT_MS },
      );
      setStatusRows(res.data ?? []);
      setErrorMsg("");
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setErrorMsg(`Embedding status (UC table): ${msg}`);
      setStatusRows([]);
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    const cancel = scheduleAfterInitialPaint(() => {
      void loadStatus();
    }, 100);
    return () => cancel();
  }, [loadStatus]);

  useEffect(() => {
    const hasActive = statusRows.some((r) => ACTIVE_STATUSES.has(r.status));
    if (!hasActive && !activeStage) return;
    const id = window.setInterval(() => void loadStatus(), 2000);
    return () => window.clearInterval(id);
  }, [loadStatus, statusRows, activeStage]);

  const rows = useMemo(() => statusRowsToUploadRows(statusRows), [statusRows]);

  useEffect(() => {
    if (!docFromUrl || rows.length === 0) return;
    const row = rows.find((r) => r.docId === docFromUrl);
    if (row) setSelectedKeys(new Set([row.rowKey]));
  }, [docFromUrl, rows]);

  const selectedRows = useMemo(
    () => rows.filter((r) => selectedKeys.has(r.rowKey)),
    [rows, selectedKeys],
  );

  const selectedDocIds = useMemo(
    () => selectedRows.map((r) => r.docId),
    [selectedRows],
  );

  const badgeCounts = useMemo(() => {
    const parsed = rows.filter((r) => r.parsed).length;
    const chunked = rows.filter((r) => r.chunked).length;
    const embedded = rows.filter((r) => r.embedded).length;
    const completed = rows.filter((r) => r.status === "ready").length;
    return {
      inQueue: selectedKeys.size,
      parsed,
      chunked,
      embedded,
      completed,
    };
  }, [rows, selectedKeys.size]);

  const toggleRow = (rowKey: string) => {
    setSelectedKeys((prev) => {
      const next = new Set(prev);
      if (next.has(rowKey)) next.delete(rowKey);
      else next.add(rowKey);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedKeys.size === rows.length) {
      setSelectedKeys(new Set());
    } else {
      setSelectedKeys(new Set(rows.map((r) => r.rowKey)));
    }
  };

  const eligibleForStage = (stage: PipelineStage): string[] => {
    return selectedRows
      .filter((row) => {
        if (!row.docId) return false;
        if (stage === "parse") {
          return row.status === "staged" || row.status === "failed" || !row.parsed;
        }
        if (stage === "chunk") {
          return row.parsed && !row.chunked;
        }
        return row.chunked && !row.embedded;
      })
      .map((r) => r.docId as string);
  };

  const waitForStage = async (docIds: string[], stage: PipelineStage) => {
    const deadline = Date.now() + 300_000;
    while (Date.now() < deadline) {
      if (cancelRef.current) throw new Error("Cancelled");
      try {
        const res = await api.get<{ data: EmbeddingStatusRow[] }>(
          "/api/v1/embedding/status?limit=500",
          { timeoutMs: LONG_RUNNING_API_TIMEOUT_MS },
        );
        const list = res.data ?? [];
        setStatusRows(list);
        let done = 0;
        for (const id of docIds) {
          const row = list.find((r) => r.doc_id === id);
          if (!row) continue;
          if (row.status === "failed") {
            throw new Error(row.error_message ?? `Processing failed for ${id}`);
          }
          const flags = rowFlags(row);
          if (stage === "parse" && flags.parsed) done += 1;
          else if (stage === "chunk" && flags.chunked) done += 1;
          else if (stage === "embed" && row.status === "ready") done += 1;
        }
        const pct = docIds.length ? Math.round((done / docIds.length) * 100) : 100;
        setStageProgress((p) => ({ ...p, [stage]: pct }));
        if (done >= docIds.length) return;
      } catch (err) {
        if (err instanceof Error && err.message !== "Cancelled") {
          const timedOut = /timed out|AbortError|signal timed out/i.test(err.message);
          if (timedOut) throw err;
        }
        throw err;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    throw new Error(`Timed out waiting for ${stage} to finish`);
  };

  const runStage = async (stage: PipelineStage, docIds?: string[]) => {
    const ids = docIds ?? eligibleForStage(stage);
    if (ids.length === 0) {
      setErrorMsg(`No selected documents are eligible for ${stage}.`);
      return;
    }
    setErrorMsg("");
    cancelRef.current = false;
    setActiveStage(stage);
    setStageProgress((p) => ({ ...p, [stage]: 0 }));
    try {
      const res = await apiFetch(
        "/api/v1/embedding/pipeline/batch",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ doc_ids: ids, stage }),
        },
        LONG_RUNNING_API_TIMEOUT_MS,
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? err.error?.message ?? `${stage} failed (${res.status})`);
      }
      await waitForStage(ids, stage);
      setStageProgress((p) => ({ ...p, [stage]: 100 }));
      await loadStatus();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      await loadStatus();
    } finally {
      setActiveStage(null);
    }
  };

  const cancelStage = async (stage: PipelineStage) => {
    cancelRef.current = true;
    const ids = eligibleForStage(stage);
    if (ids.length > 0) {
      await apiFetch("/api/v1/embedding/pipeline/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_ids: ids }),
      });
    }
    setActiveStage(null);
    setStageProgress((p) => ({ ...p, [stage]: 0 }));
    await loadStatus();
  };

  const docIdsEligible = async (stage: PipelineStage): Promise<string[]> => {
    const res = await api.get<{ data: EmbeddingStatusRow[] }>(
      "/api/v1/embedding/status?limit=500",
    );
    const list = res.data ?? [];
    const selectedIds = new Set(
      rows.filter((r) => selectedKeys.has(r.rowKey)).map((r) => r.docId),
    );
    return list
      .filter((r) => selectedIds.has(r.doc_id))
      .filter((r) => {
        const flags = rowFlags(r);
        if (stage === "parse") {
          return r.status === "staged" || r.status === "failed" || !flags.parsed;
        }
        if (stage === "chunk") return flags.parsed && !flags.chunked;
        return flags.chunked && !flags.embedded;
      })
      .map((r) => r.doc_id);
  };

  const processAll = async () => {
    setErrorMsg("");
    cancelRef.current = false;
    try {
      for (const stage of ["parse", "chunk", "embed"] as const) {
        const ids = await docIdsEligible(stage);
        if (ids.length > 0) await runStage(stage, ids);
      }
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    }
  };

  const allSelected = rows.length > 0 && selectedKeys.size === rows.length;

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title="Parse & Chunk"
        subtitle="Select staged uploads, then parse, chunk, and embed in separate steps."
        contentClassName="max-w-6xl"
        actions={<LlmConnectivityBadge />}
      />

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <div className="rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm text-sm text-gray-600">
          Pipeline status is stored in Unity Catalog{" "}
          <code className="text-gray-500">embedding_status</code>; file bytes and artifacts live
          under UC{" "}
          <code className="text-gray-500">workflow-data/uploads/</code>. Stage new files on{" "}
          <AppLink href="/upload" className="font-medium text-indigo-600 hover:text-indigo-800">
            Upload Documents
          </AppLink>
          .
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
          <SummaryBadge label="In Queue" value={badgeCounts.inQueue} accent="sky" />
          <SummaryBadge label="Parsed" value={badgeCounts.parsed} accent="amber" />
          <SummaryBadge label="Chunked" value={badgeCounts.chunked} accent="violet" />
          <SummaryBadge label="Embedded" value={badgeCounts.embedded} accent="indigo" />
          <SummaryBadge label="Completed" value={badgeCounts.completed} accent="emerald" />
        </div>

        {errorMsg && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
            {errorMsg}
          </div>
        )}

        <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100 flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">
              Documents
            </h2>
            <button
              type="button"
              onClick={() => void processAll()}
              disabled={selectedDocIds.length === 0 || activeStage !== null}
              className="text-sm px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 font-medium"
            >
              Process All
            </button>
          </div>

          {!loaded ? (
            <p className="px-5 py-8 text-sm text-gray-400">Loading embedding status…</p>
          ) : rows.length === 0 ? (
            <div className="px-5 py-8 text-sm text-gray-500">
              <p>No documents in embedding_status yet.</p>
              <AppLink
                href="/upload"
                className="mt-2 inline-block font-medium text-indigo-600 hover:text-indigo-800"
              >
                Upload Documents →
              </AppLink>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="min-w-full text-sm">
                <thead className="bg-gray-50 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  <tr>
                    <th className="px-4 py-3 w-10">
                      <input
                        type="checkbox"
                        checked={allSelected}
                        onChange={toggleAll}
                        aria-label="Select all documents"
                        className="rounded border-gray-300"
                      />
                    </th>
                    <th className="px-4 py-3">File</th>
                    <th className="px-4 py-3">Path</th>
                    <th className="px-4 py-3 text-right">Size (kB)</th>
                    <th className="px-4 py-3 text-center">Parsed</th>
                    <th className="px-4 py-3 text-center">Chunked</th>
                    <th className="px-4 py-3 text-center">Embedded</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {rows.map((row) => (
                    <tr
                      key={row.rowKey}
                      className={selectedKeys.has(row.rowKey) ? "bg-indigo-50/40" : undefined}
                    >
                      <td className="px-4 py-3">
                        <input
                          type="checkbox"
                          checked={selectedKeys.has(row.rowKey)}
                          onChange={() => toggleRow(row.rowKey)}
                          aria-label={`Select ${row.displayName}`}
                          className="rounded border-gray-300"
                        />
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-900 max-w-[12rem] truncate">
                        {row.displayName}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-gray-500 max-w-[16rem] truncate">
                        {row.filepath}
                      </td>
                      <td className="px-4 py-3 text-right text-gray-600 tabular-nums">
                        {row.sizeKb > 0 ? row.sizeKb : "—"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <BoolCell value={row.parsed} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <BoolCell value={row.chunked} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <BoolCell value={row.embedded} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <div className="grid md:grid-cols-3 gap-4">
          <StageWidget
            title="Parse"
            stage="parse"
            progress={stageProgress.parse}
            running={activeStage === "parse"}
            disabled={selectedDocIds.length === 0}
            onStart={() => void runStage("parse")}
            onCancel={() => void cancelStage("parse")}
          />
          <StageWidget
            title="Chunk"
            stage="chunk"
            progress={stageProgress.chunk}
            running={activeStage === "chunk"}
            disabled={selectedDocIds.length === 0}
            onStart={() => void runStage("chunk")}
            onCancel={() => void cancelStage("chunk")}
          />
          <StageWidget
            title="Embed"
            stage="embed"
            progress={stageProgress.embed}
            running={activeStage === "embed"}
            disabled={selectedDocIds.length === 0}
            onStart={() => void runStage("embed")}
            onCancel={() => void cancelStage("embed")}
          />
        </div>
      </div>
    </main>
  );
}

function SummaryBadge({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: "sky" | "amber" | "violet" | "indigo" | "emerald";
}) {
  const colors = {
    sky: "text-sky-800 bg-sky-50 border-sky-200",
    amber: "text-amber-800 bg-amber-50 border-amber-200",
    violet: "text-violet-800 bg-violet-50 border-violet-200",
    indigo: "text-indigo-800 bg-indigo-50 border-indigo-200",
    emerald: "text-emerald-800 bg-emerald-50 border-emerald-200",
  };
  return (
    <div className={`rounded-lg border px-4 py-3 shadow-sm ${colors[accent]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
    </div>
  );
}

function BoolCell({ value }: { value: boolean }) {
  return (
    <span
      className={`inline-flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
        value ? "bg-emerald-100 text-emerald-800" : "bg-gray-100 text-gray-400"
      }`}
      aria-label={value ? "yes" : "no"}
    >
      {value ? "✓" : "—"}
    </span>
  );
}

function StageWidget({
  title,
  progress,
  running,
  disabled,
  onStart,
  onCancel,
}: {
  title: string;
  stage: PipelineStage;
  progress: number;
  running: boolean;
  disabled: boolean;
  onStart: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-4">
      <h3 className="text-sm font-semibold text-gray-800 uppercase tracking-wide">{title}</h3>
      <div>
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>Progress</span>
          <span className="tabular-nums">{progress}%</span>
        </div>
        <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
          <div
            className="h-full bg-indigo-600 transition-all duration-300"
            style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
          />
        </div>
      </div>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onStart}
          disabled={disabled || running}
          className="flex-1 text-sm px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 font-medium"
        >
          {running ? "Running…" : "Start"}
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={!running}
          className="text-sm px-3 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-40"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
