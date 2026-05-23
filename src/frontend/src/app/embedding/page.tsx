"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, apiFetch } from "@/lib/api-client";
import AppHeader from "@/components/layout/AppHeader";
import AppLink from "@/components/layout/AppLink";
import LlmConnectivityBadge from "@/components/layout/LlmConnectivityBadge";
import { getUploadFileKind } from "@/lib/fileAccept";

interface DocumentEntry {
  _key: string;
  filename: string;
  status: string;
  mime_type: string;
  upload_date: string;
  chunk_count: number;
  error_message?: string;
}

interface ChunkEntry {
  _key: string;
  chunk_index: number;
  text: string;
  token_count?: number;
  embedding?: number[];
}

interface PrepareResponse {
  doc_id: string;
  filename: string;
  status: string;
  schema?: { applied?: string[]; skipped?: boolean };
}

const PROCESSING_STATUSES = new Set([
  "uploading",
  "parsing",
  "chunking",
  "embedding",
]);

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

  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [preparingDocs, setPreparingDocs] = useState<Set<string>>(new Set());
  const [lastPrepare, setLastPrepare] = useState<PrepareResponse | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [selectedDocId, setSelectedDocId] = useState<string | null>(docFromUrl);
  const [chunks, setChunks] = useState<ChunkEntry[]>([]);
  const [chunksLoading, setChunksLoading] = useState(false);
  const [chunksError, setChunksError] = useState("");

  const loadDocuments = useCallback(async () => {
    try {
      const res = await api.get<{ data: DocumentEntry[] }>("/api/v1/documents?limit=50");
      setDocuments((res.data ?? []).filter((d) => getUploadFileKind(d.filename) === "document"));
    } catch {
      /* ignore */
    } finally {
      setDocsLoaded(true);
    }
  }, []);

  const loadChunks = useCallback(async (docId: string) => {
    setChunksLoading(true);
    setChunksError("");
    try {
      const res = await api.get<{ data: ChunkEntry[] }>(
        `/api/v1/documents/${docId}/chunks?limit=20`,
      );
      setChunks(res.data ?? []);
      if ((res.data ?? []).length === 0) {
        setChunksError("No chunks stored yet — run Parse & chunk first.");
      }
    } catch (err) {
      setChunks([]);
      setChunksError(err instanceof Error ? err.message : String(err));
    } finally {
      setChunksLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
    const hasProcessing = documents.some((d) => PROCESSING_STATUSES.has(d.status));
    if (!hasProcessing) return;
    const id = window.setInterval(() => void loadDocuments(), 3000);
    return () => window.clearInterval(id);
  }, [loadDocuments, documents]);

  useEffect(() => {
    if (docFromUrl) setSelectedDocId(docFromUrl);
  }, [docFromUrl]);

  useEffect(() => {
    if (selectedDocId) void loadChunks(selectedDocId);
  }, [selectedDocId, loadChunks]);

  const waitForDocumentReady = async (docId: string, maxWaitMs = 180_000) => {
    const start = Date.now();
    while (Date.now() - start < maxWaitMs) {
      const res = await apiFetch(`/api/v1/documents/${docId}`);
      if (res.ok) {
        const doc = await res.json();
        const status = doc.status ?? doc.data?.status;
        if (status === "ready") return;
        if (status === "failed") {
          throw new Error(doc.error_message ?? doc.data?.error_message ?? "Processing failed");
        }
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    throw new Error("Timed out waiting for parse/chunk/embed to finish");
  };

  const prepareDocument = async (docId: string) => {
    setPreparingDocs((prev) => new Set(prev).add(docId));
    setErrorMsg("");
    setLastPrepare(null);
    try {
      const res = await apiFetch(`/api/v1/documents/${docId}/prepare`, { method: "POST" });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail ?? err.error?.message ?? `Prepare failed (${res.status})`);
      }
      const data = (await res.json()) as PrepareResponse;
      setLastPrepare(data);
      setSelectedDocId(docId);
      await waitForDocumentReady(docId);
      await loadDocuments();
      await loadChunks(docId);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      await loadDocuments();
    } finally {
      setPreparingDocs((prev) => {
        const next = new Set(prev);
        next.delete(docId);
        return next;
      });
    }
  };

  const stagedCount = documents.filter((d) => d.status === "staged" || d.status === "failed").length;
  const readyCount = documents.filter((d) => d.status === "ready" || d.chunk_count > 0).length;
  const processingCount = documents.filter((d) => PROCESSING_STATUSES.has(d.status)).length;

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title="Parse & Chunk"
        subtitle="Parse, chunk, and embed staged documents. Stage new files on Upload Documents first."
        contentClassName="max-w-5xl"
        actions={<LlmConnectivityBadge />}
      />

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-4 py-3 shadow-sm">
          <p className="text-sm text-gray-600">
            Documents are staged on the{" "}
            <AppLink href="/upload" className="font-medium text-indigo-600 hover:text-indigo-800">
              Upload Documents
            </AppLink>{" "}
            page. Return here to parse, chunk, and verify embeddings.
          </p>
        </div>

        <div className="grid sm:grid-cols-3 gap-3">
          <SummaryCard label="Awaiting parse" value={docsLoaded ? String(stagedCount) : "…"} />
          <SummaryCard label="Processing" value={docsLoaded ? String(processingCount) : "…"} highlight={processingCount > 0} />
          <SummaryCard label="Ready" value={docsLoaded ? String(readyCount) : "…"} ok />
        </div>

        {lastPrepare && (
          <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 text-sm">
            <p className="font-medium text-emerald-800">Last prepare completed</p>
            <p className="mt-1 text-emerald-700">
              {lastPrepare.filename} → <code>{lastPrepare.status}</code>
              {lastPrepare.schema?.applied?.length ? (
                <> · schema: {lastPrepare.schema.applied.join(", ")}</>
              ) : null}
            </p>
          </div>
        )}

        {errorMsg && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
            {errorMsg}
          </div>
        )}

        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-3">
            Documents
          </h2>
          {!docsLoaded ? (
            <p className="text-sm text-gray-400">Loading…</p>
          ) : documents.length === 0 ? (
            <div className="bg-white rounded-xl border border-gray-200 p-6 text-sm text-gray-500">
              <p>No staged documents yet.</p>
              <AppLink
                href="/upload"
                className="mt-2 inline-block font-medium text-indigo-600 hover:text-indigo-800"
              >
                Upload Documents →
              </AppLink>
            </div>
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 shadow-sm">
              {documents.map((doc) => (
                <div
                  key={doc._key}
                  className="px-5 py-4 flex flex-wrap items-center justify-between gap-3"
                >
                  <div className="min-w-0 flex-1">
                    <p className="font-medium text-gray-900 truncate">{doc.filename}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {doc.chunk_count} chunks ·{" "}
                      <StatusPill status={doc.status} />
                    </p>
                    {doc.status === "failed" && doc.error_message && (
                      <p className="text-xs text-red-600 mt-1 line-clamp-2">{doc.error_message}</p>
                    )}
                  </div>
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {(doc.status === "staged" || doc.status === "failed") && (
                      preparingDocs.has(doc._key) || PROCESSING_STATUSES.has(doc.status) ? (
                        <span className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-amber-100 text-amber-800 rounded-lg font-medium">
                          <span className="h-3 w-3 border-2 border-amber-600 border-t-transparent rounded-full animate-spin" />
                          {doc.status === "staged" || doc.status === "failed" ? "Parsing…" : doc.status}
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => void prepareDocument(doc._key)}
                          className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 font-medium"
                        >
                          Parse &amp; chunk
                        </button>
                      )
                    )}
                    {PROCESSING_STATUSES.has(doc.status) && !preparingDocs.has(doc._key) && (
                      <span className="text-xs px-3 py-1.5 bg-yellow-100 text-yellow-800 rounded-lg font-medium capitalize">
                        {doc.status}…
                      </span>
                    )}
                    {(doc.status === "ready" || doc.chunk_count > 0) && (
                      <button
                        type="button"
                        onClick={() => setSelectedDocId(doc._key)}
                        className={`text-xs px-3 py-1.5 rounded-lg font-medium border ${
                          selectedDocId === doc._key
                            ? "bg-indigo-600 text-white border-indigo-600"
                            : "border-gray-300 text-gray-700 hover:bg-gray-50"
                        }`}
                      >
                        View chunks
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {selectedDocId && (
          <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
              <h2 className="text-sm font-semibold text-gray-700">
                Chunk preview
                <span className="ml-2 font-mono text-xs text-gray-400">{selectedDocId}</span>
              </h2>
              {documents.find((d) => d._key === selectedDocId)?.status === "ready" && (
                <AppLink
                  href="/pipeline"
                  className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                >
                  Run extraction →
                </AppLink>
              )}
            </div>
            {chunksLoading ? (
              <p className="text-sm text-gray-400 animate-pulse">Loading chunks…</p>
            ) : chunksError ? (
              <p className="text-sm text-amber-700">{chunksError}</p>
            ) : (
              <ul className="space-y-3 max-h-[28rem] overflow-y-auto">
                {chunks.map((c) => (
                  <li key={c._key} className="border border-gray-100 rounded-lg p-3 text-sm">
                    <div className="flex justify-between text-xs text-gray-500 mb-1">
                      <span>#{c.chunk_index}</span>
                      <span>
                        {c.token_count != null ? `${c.token_count} tokens` : ""}
                        {c.embedding?.length ? ` · embedding dim ${c.embedding.length}` : ""}
                      </span>
                    </div>
                    <p className="text-gray-800 line-clamp-4 whitespace-pre-wrap">{c.text}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
        )}
      </div>
    </main>
  );
}

function SummaryCard({
  label,
  value,
  ok,
  highlight,
}: {
  label: string;
  value: string;
  ok?: boolean;
  highlight?: boolean;
}) {
  return (
    <div className="bg-white rounded-lg border border-gray-200 px-4 py-3 shadow-sm">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</p>
      <p
        className={`mt-1 text-sm font-semibold ${
          highlight ? "text-amber-700" : ok ? "text-emerald-700" : "text-gray-900"
        }`}
      >
        {value}
      </p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const className =
    status === "ready" || status === "processed"
      ? "text-emerald-700"
      : status === "staged"
        ? "text-sky-700"
        : status === "failed"
          ? "text-red-700"
          : PROCESSING_STATUSES.has(status)
            ? "text-amber-700"
            : "text-gray-600";
  return <span className={`font-medium capitalize ${className}`}>{status}</span>;
}
