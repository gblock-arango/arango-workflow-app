"use client";

import { useCallback, useEffect, useState } from "react";
import { api, apiFetch } from "@/lib/api-client";
import AppLink from "@/components/layout/AppLink";

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

interface StartExtractionPanelProps {
  onRunStarted: (runId: string) => void;
}

export default function StartExtractionPanel({ onRunStarted }: StartExtractionPanelProps) {
  const [docs, setDocs] = useState<EmbeddingRow[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [ontologies, setOntologies] = useState<OntologyOption[]>([]);
  const [targetOntologyId, setTargetOntologyId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

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
  }, [loadDocs]);

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
    setBusy(true);
    setError("");
    try {
      const payload: Record<string, unknown> =
        ids.length === 1 ? { document_id: ids[0] } : { document_ids: ids };
      if (targetOntologyId) {
        payload.target_ontology_id = targetOntologyId;
      }
      const res = await apiFetch("/api/v1/extraction/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail =
          typeof body.detail === "string"
            ? body.detail
            : body.error?.message ?? `HTTP ${res.status}`;
        throw new Error(detail);
      }
      const data = (await res.json()) as { run_id?: string };
      if (!data.run_id) {
        throw new Error("No run_id returned from extraction API");
      }
      setSelected(new Set());
      onRunStarted(data.run_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="border-b border-gray-200 bg-slate-50/80 p-4 space-y-3">
      <div>
        <h2 className="text-sm font-semibold text-gray-800">Start extraction</h2>
        <p className="text-xs text-gray-500 mt-1 leading-relaxed">
          Documents must be <strong>ready</strong> (Parse &amp; Chunk → embed complete). This
          launches a new run; select it below to watch the agent pipeline.
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
      </label>

      {error && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded px-2 py-1">
          {error}
        </p>
      )}

      <button
        type="button"
        disabled={busy || selected.size === 0}
        onClick={() => void startExtraction()}
        className="w-full text-sm font-medium px-3 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-40 transition-colors"
      >
        {busy ? "Starting…" : `Start extraction (${selected.size} selected)`}
      </button>
    </section>
  );
}
