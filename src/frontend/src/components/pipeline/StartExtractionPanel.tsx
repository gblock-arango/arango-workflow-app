"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, apiFetchLongRunning, readApiErrorMessage } from "@/lib/api-client";
import type { RunProgressSnapshot } from "@/lib/runStatusPoll";
import { ACTIVE_RUN_STATUSES } from "@/lib/runStatusPoll";
import AppLink from "@/components/layout/AppLink";

const SELECTION_STORAGE_KEY = "aoe-pipeline-extraction-selection";

interface EmbeddingRow {
  doc_id: string;
  filename: string;
  status: string;
  embedded?: boolean;
}

interface OntologyOption {
  _key: string;
  name: string;
}

interface SavedExtractionSelection {
  runId: string;
  docIds: string[];
  targetOntologyId?: string;
  arangoDatabase?: string;
}

interface StartExtractionPanelProps {
  onRunStarted: (runId: string) => void;
  /** When true, the selected run is still preparing or running — block duplicate starts. */
  extractionInProgress?: boolean;
  selectedRunId?: string | null;
  runProgress?: RunProgressSnapshot | null;
  onRunCancelled?: () => void;
}

function readSavedSelection(runId: string): SavedExtractionSelection | null {
  try {
    const raw = localStorage.getItem(SELECTION_STORAGE_KEY);
    if (!raw) return null;
    const saved = JSON.parse(raw) as SavedExtractionSelection;
    if (saved.runId !== runId || !Array.isArray(saved.docIds) || saved.docIds.length === 0) {
      return null;
    }
    return saved;
  } catch {
    return null;
  }
}

function writeSavedSelection(selection: SavedExtractionSelection): void {
  try {
    localStorage.setItem(SELECTION_STORAGE_KEY, JSON.stringify(selection));
  } catch {
    // ignore quota / private mode
  }
}

function docIdsFromProgress(progress: RunProgressSnapshot | null | undefined): string[] {
  if (!progress) return [];
  if (Array.isArray(progress.doc_ids) && progress.doc_ids.length > 0) {
    return progress.doc_ids;
  }
  if (progress.doc_id) return [progress.doc_id];
  return [];
}

export default function StartExtractionPanel({
  onRunStarted,
  extractionInProgress = false,
  selectedRunId = null,
  runProgress = null,
  onRunCancelled,
}: StartExtractionPanelProps) {
  const [docs, setDocs] = useState<EmbeddingRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ontologies, setOntologies] = useState<OntologyOption[]>([]);
  const [targetOntologyId, setTargetOntologyId] = useState("");
  const [arangoDatabase, setArangoDatabase] = useState("");
  const [defaultDatabaseLoaded, setDefaultDatabaseLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [cancelBusy, setCancelBusy] = useState(false);
  const [error, setError] = useState("");
  const [cancelError, setCancelError] = useState("");
  const restoredForRunRef = useRef<string | null>(null);

  const loadDocs = useCallback(async () => {
    try {
      const res = await api.get<{ data: EmbeddingRow[] }>(
        "/api/v1/embedding/status?limit=500",
      );
      const ready = (res.data ?? []).filter(
        (r) => r.status === "ready" || r.embedded === true,
      );
      setDocs(ready);
      setError("");
    } catch (err) {
      setDocs([]);
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void loadDocs();
    api
      .get<{ data: OntologyOption[] }>("/api/v1/ontology/library?limit=100")
      .then((res) => setOntologies(res.data ?? []))
      .catch(() => setOntologies([]));
    api
      .get<{ name?: string }>("/api/v1/extraction/default-database-name")
      .then((res) => {
        if (res.name) setArangoDatabase(res.name);
      })
      .catch(() => {
        if (!arangoDatabase) setArangoDatabase("AutoGraph_1");
      })
      .finally(() => setDefaultDatabaseLoaded(true));
  }, [loadDocs]);

  useEffect(() => {
    restoredForRunRef.current = null;
  }, [selectedRunId]);

  useEffect(() => {
    if (!selectedRunId || !loaded) return;
    if (restoredForRunRef.current === selectedRunId) return;

    const applySelection = (
      ids: string[],
      targetOntology?: string,
      databaseName?: string,
    ): boolean => {
      if (ids.length === 0) return false;
      setSelected(new Set(ids));
      if (targetOntology) setTargetOntologyId(targetOntology);
      if (databaseName) setArangoDatabase(databaseName);
      restoredForRunRef.current = selectedRunId;
      return true;
    };

    const fromProgress = docIdsFromProgress(runProgress);
    if (
      applySelection(
        fromProgress,
        runProgress?.target_ontology_id ?? undefined,
        runProgress?.arango_database ?? undefined,
      )
    ) {
      return;
    }

    const saved = readSavedSelection(selectedRunId);
    if (
      saved &&
      applySelection(saved.docIds, saved.targetOntologyId, saved.arangoDatabase)
    ) {
      return;
    }

    let cancelled = false;
    api
      .get<{
        doc_id?: string;
        doc_ids?: string[];
        target_ontology_id?: string;
        arango_database?: string;
      }>(`/api/v1/extraction/runs/${selectedRunId}`)
      .then((run) => {
        if (cancelled || restoredForRunRef.current === selectedRunId) return;
        const ids =
          Array.isArray(run.doc_ids) && run.doc_ids.length > 0
            ? run.doc_ids
            : run.doc_id
              ? [run.doc_id]
              : [];
        applySelection(ids, run.target_ontology_id, run.arango_database);
      })
      .catch(() => {});

    return () => {
      cancelled = true;
    };
  }, [selectedRunId, loaded, runProgress]);

  const toggle = (docId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId);
      else next.add(docId);
      return next;
    });
  };

  const startExtraction = async () => {
    const ids = [...selected];
    if (ids.length === 0) {
      setError("Select at least one document with status ready.");
      return;
    }
    const dbName = arangoDatabase.trim();
    if (!dbName) {
      setError("Enter an Arango database name (created automatically when extraction starts).");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> =
        ids.length === 1 ? { document_id: ids[0] } : { document_ids: ids };
      payload.arango_database = dbName;
      if (targetOntologyId) {
        payload.target_ontology_id = targetOntologyId;
      }
      const res = await apiFetchLongRunning("/api/v1/extraction/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }
      const data = (await res.json()) as { run_id?: string };
      if (!data.run_id) {
        throw new Error("No run_id returned from extraction API");
      }
      writeSavedSelection({
        runId: data.run_id,
        docIds: ids,
        targetOntologyId: targetOntologyId || undefined,
        arangoDatabase: dbName,
      });
      setError("");
      onRunStarted(data.run_id);
    } catch (err) {
      const raw = err instanceof Error ? err.message : String(err);
      const timedOut = /timed out|AbortError|signal timed out/i.test(raw);
      setError(
        timedOut
          ? "Request timed out creating the run record (Arango gateway connect may be slow). Check Diagnostics below and Extraction Runs."
          : raw,
      );
    } finally {
      setBusy(false);
    }
  };

  const canCancel =
    Boolean(selectedRunId) &&
    Boolean(runProgress?.status) &&
    ACTIVE_RUN_STATUSES.has(runProgress!.status);

  async function handleCancelExtraction() {
    if (!selectedRunId || cancelBusy) return;
    if (!confirm("Cancel this extraction run? The worker will stop at the next checkpoint.")) {
      return;
    }
    setCancelBusy(true);
    setCancelError("");
    try {
      await api.post<{ run_id: string; status: string }>(
        `/api/v1/extraction/runs/${selectedRunId}/cancel`,
      );
      onRunCancelled?.();
    } catch (err) {
      setCancelError(err instanceof Error ? err.message : String(err));
    } finally {
      setCancelBusy(false);
    }
  }

  return (
    <section className="border-b border-gray-200 bg-slate-50/80 p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-gray-800">Start extraction</h2>
        <p className="text-xs text-gray-500 mt-1 leading-relaxed">
          Documents must be <strong>ready</strong> (Parse &amp; Chunk → embed complete). This
          launches a new run; select it below to watch the agent pipeline. The first start may
          take a few minutes while chunks are copied to Arango and schema migrations run.
        </p>
      </div>

      {!loaded ? (
        <p className="text-xs text-gray-400">Loading ready documents…</p>
      ) : docs.length === 0 ? (
        <p className="text-xs text-gray-500">
          No ready documents. Finish{" "}
          <AppLink href="/embedding" className="text-indigo-600 underline">
            Parse &amp; Chunk
          </AppLink>{" "}
          first, or use{" "}
          <AppLink href="/upload" className="text-indigo-600 underline">
            Upload
          </AppLink>
          .
        </p>
      ) : (
        <ul className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-white divide-y divide-gray-100">
          {docs.map((doc) => (
            <li key={doc.doc_id}>
              <label className="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-gray-50">
                <input
                  type="checkbox"
                  checked={selected.has(doc.doc_id)}
                  onChange={() => toggle(doc.doc_id)}
                  className="rounded border-gray-300"
                />
                <span className="truncate flex-1" title={doc.filename}>
                  {doc.filename}
                </span>
                <span className="text-[10px] text-gray-400 font-mono shrink-0">
                  {doc.doc_id.slice(0, 8)}
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      <label className="block text-xs text-gray-600">
        Arango database
        <input
          type="text"
          value={arangoDatabase}
          onChange={(e) => setArangoDatabase(e.target.value)}
          placeholder={defaultDatabaseLoaded ? "AutoGraph_1" : "Loading suggestion…"}
          className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm font-mono"
          spellCheck={false}
        />
        <span className="mt-1 block text-[11px] text-gray-500 leading-relaxed">
          Created automatically in Arango when extraction starts (empty graph database).
          Each run can use its own database; default is the next{" "}
          <code className="text-[10px]">AutoGraph_&lt;n&gt;</code> name.
        </span>
      </label>

      <label className="block text-xs text-gray-600">
        Target ontology (optional)
        <select
          value={targetOntologyId}
          onChange={(e) => setTargetOntologyId(e.target.value)}
          className="mt-1 w-full rounded-lg border border-gray-300 bg-white px-2 py-1.5 text-sm"
        >
          <option value="">Create new ontology</option>
          {ontologies.map((o) => (
            <option key={o._key} value={o._key}>
              {o.name}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[11px] text-gray-500 leading-relaxed">
          Which ontology in the graph to merge into — not the Arango database name.
        </span>
      </label>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
          {error}
        </p>
      )}

      <button
        type="button"
        disabled={
          busy || selected.size === 0 || extractionInProgress || !arangoDatabase.trim()
        }
        onClick={() => void startExtraction()}
        className="w-full text-sm font-medium px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
      >
        {extractionInProgress
          ? "Extraction in progress…"
          : busy
            ? "Starting… (preparing run)"
            : `Start extraction (${selected.size} selected)`}
      </button>

      {canCancel && (
        <button
          type="button"
          onClick={() => void handleCancelExtraction()}
          disabled={cancelBusy}
          className="w-full text-sm font-medium px-3 py-2 border border-red-200 text-red-600 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
        >
          {cancelBusy ? "Cancelling…" : "Cancel extraction"}
        </button>
      )}

      {cancelError && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
          Cancel failed: {cancelError}
        </p>
      )}
    </section>
  );
}
