"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, backendUrl } from "@/lib/api-client";
import { withBasePath } from "@/lib/base-path";
import AppHeader from "@/components/layout/AppHeader";
import {
  DOCUMENT_UPLOAD_FILE_ACCEPT,
  isOntologyImportFilename,
  ONTOLOGY_IMPORT_FILE_ACCEPT,
} from "@/lib/fileAccept";

interface UploadResult {
  doc_id: string;
  filename: string;
  status: string;
  volume_path?: string;
}

interface VolumeFileEntry {
  path: string;
  name: string;
  size_bytes: number;
  category: string;
  mime_type?: string;
}

interface DocumentEntry {
  _key: string;
  filename: string;
  status: string;
  mime_type: string;
  upload_date: string;
  chunk_count: number;
}

interface OntologyOption {
  _key: string;
  name: string;
  class_count: number;
  tier: string;
}

interface ImportResultData {
  ontology_id?: string;
  name?: string;
  class_count?: number;
}

interface ExtractionRunResponse {
  run_id?: string;
}

type UploadState = "idle" | "uploading" | "extracting" | "success" | "error";

export default function UploadPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [extractionRunId, setExtractionRunId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [extractingDocs, setExtractingDocs] = useState<Set<string>>(new Set());
  const [ontologyOptions, setOntologyOptions] = useState<OntologyOption[]>([]);
  const [targetOntologyId, setTargetOntologyId] = useState<string>("");
  const [docOntologies, setDocOntologies] = useState<Record<string, { _key: string; name: string }[]>>({});
  const [mode, setMode] = useState<"extract" | "import">("extract");
  const [importState, setImportState] = useState<
    "idle" | "uploading" | "processing" | "success" | "error"
  >("idle");
  const [importName, setImportName] = useState("");
  const [importResult, setImportResult] = useState<ImportResultData | null>(null);
  const [importError, setImportError] = useState("");
  const importFileRef = useRef<HTMLInputElement>(null);
  const [builtinFiles, setBuiltinFiles] = useState<VolumeFileEntry[]>([]);
  const [builtinLoaded, setBuiltinLoaded] = useState(false);
  const [builtinIngesting, setBuiltinIngesting] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const res = await api.get<{ data: DocumentEntry[] }>("/api/v1/documents");
      const docs = res.data ?? [];
      setDocuments(docs);
      setDocsLoaded(true);

      const mapping: Record<string, { _key: string; name: string }[]> = {};
      await Promise.all(
        docs.map(async (doc) => {
          try {
            const ontRes = await api.get<{ ontologies: { _key: string; name: string }[] }>(
              `/api/v1/documents/${doc._key}/ontologies`,
            );
            if (ontRes.ontologies?.length) {
              mapping[doc._key] = ontRes.ontologies;
            }
          } catch { /* ignore */ }
        }),
      );
      setDocOntologies(mapping);
    } catch {
      setDocsLoaded(true);
    }
  }, []);

  const loadOntologies = useCallback(async () => {
    try {
      const res = await api.get<{ data: OntologyOption[] }>(
        "/api/v1/ontology/library?limit=100",
      );
      setOntologyOptions(res.data ?? []);
    } catch {
      /* non-critical */
    }
  }, []);

  const loadBuiltinFiles = useCallback(async () => {
    try {
      const res = await api.get<{ files: VolumeFileEntry[] }>(
        "/api/v1/documents/volume/browse?prefix=builtin",
      );
      setBuiltinFiles(res.files ?? []);
    } catch {
      setBuiltinFiles([]);
    } finally {
      setBuiltinLoaded(true);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
    loadOntologies();
    loadBuiltinFiles();
  }, [loadDocuments, loadOntologies, loadBuiltinFiles]);

  const triggerExtraction = async (
    docId: string,
    ontologyId?: string,
  ): Promise<string | null> => {
    try {
      const payload: Record<string, unknown> = { document_id: docId };
      if (ontologyId) {
        payload.target_ontology_id = ontologyId;
      }
      const res = await fetch(backendUrl("/api/v1/extraction/run"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      const data = await res.json() as ExtractionRunResponse;
      return data.run_id ?? null;
    } catch {
      return null;
    }
  };

  const importOWLFile = async (file: File) => {
    setImportState("uploading");
    setImportError("");
    setImportResult(null);

    const formData = new FormData();
    formData.append("file", file);

    const label = importName.trim() || file.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
    const id = `import_${Date.now().toString(36)}`;

    try {
      const params = new URLSearchParams({
        ontology_id: id,
        ontology_label: label,
      });
      const res = await fetch(backendUrl(`/api/v1/ontology/import?${params}`), {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || errBody.message || `Import failed (${res.status})`);
      }

      // New contract (202): backend runs the import asynchronously and we poll
      // /import/{id}/status until it reports completed or failed. Large OWL
      // files can take minutes (per-triple writes against a remote cluster),
      // so a single synchronous HTTP request would exceed the proxy timeout.
      setImportState("processing");
      const accepted = await res.json();
      const ontologyId = accepted.ontology_id || id;

      const finalResult = await pollImportStatus(ontologyId);
      setImportResult(finalResult);
      setImportState("success");
      loadDocuments();
      loadOntologies();
    } catch (err) {
      setImportError(err instanceof Error ? err.message : String(err));
      setImportState("error");
    }
  };

  const pollImportStatus = async (
    ontologyId: string,
    {
      intervalMs = 2000,
      timeoutMs = 15 * 60 * 1000,
    }: { intervalMs?: number; timeoutMs?: number } = {},
  ): Promise<ImportResultData> => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
      const statusRes = await fetch(
        backendUrl(`/api/v1/ontology/import/${encodeURIComponent(ontologyId)}/status`),
      );
      if (!statusRes.ok) {
        if (statusRes.status === 404) continue;
        const errBody = await statusRes.json().catch(() => ({}));
        throw new Error(
          errBody.detail || errBody.message || `Status check failed (${statusRes.status})`,
        );
      }
      const job = await statusRes.json();
      if (job.status === "completed") {
        const result = (job.result ?? {}) as Record<string, unknown>;
        return {
          ontology_id: (result.registry_key as string) ?? ontologyId,
          name: result.name as string | undefined,
          class_count: result.class_count as number | undefined,
        };
      }
      if (job.status === "failed") {
        throw new Error(job.error || "Import failed on the server");
      }
    }
    throw new Error("Import timed out waiting for the server to finish");
  };

  const extractDocument = async (docId: string) => {
    setExtractingDocs((prev) => new Set(prev).add(docId));
    const runId = await triggerExtraction(
      docId,
      targetOntologyId || undefined,
    );
    setExtractingDocs((prev) => {
      const next = new Set(prev);
      next.delete(docId);
      return next;
    });
    if (runId) {
      window.location.href = withBasePath(`/pipeline?runId=${runId}`);
    }
  };

  const waitForDocumentReady = async (
    docId: string,
    maxWaitMs = 120_000,
  ): Promise<void> => {
    const start = Date.now();
    const pollInterval = 1500;

    while (Date.now() - start < maxWaitMs) {
      try {
        const res = await fetch(backendUrl(`/api/v1/documents/${docId}`));
        if (res.ok) {
          const doc = await res.json();
          const status = doc.status ?? doc.data?.status;
          if (status === "ready") return;
          if (status === "failed") {
            const errMsg = doc.error_message ?? doc.data?.error_message ?? "Ingestion failed";
            throw new Error(`Document processing failed: ${errMsg}`);
          }
        }
      } catch (err) {
        if (err instanceof Error && err.message.startsWith("Document processing failed")) {
          throw err;
        }
      }
      await new Promise((r) => setTimeout(r, pollInterval));
    }
    throw new Error("Document processing timed out — please try extracting manually once it's ready.");
  };

  const isJsonImportFile = (file: File) => isOntologyImportFilename(file.name);

  const ingestFromVolume = async (path: string, displayName: string) => {
    setBuiltinIngesting(path);
    setUploadState("uploading");
    setErrorMsg("");
    setResult(null);
    setExtractionRunId(null);

    try {
      const res = await fetch(backendUrl("/api/v1/documents/ingest-from-volume"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          err.detail ?? err.error?.message ?? `Ingest failed (${res.status})`,
        );
      }
      const data: UploadResult = await res.json();
      setResult({ ...data, filename: data.filename || displayName });
      loadDocuments();
      await waitForDocumentReady(data.doc_id);
      loadDocuments();
      setUploadState("extracting");
      const runId = await triggerExtraction(
        data.doc_id,
        targetOntologyId || undefined,
      );
      setExtractionRunId(runId);
      setUploadState("success");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setUploadState("error");
    } finally {
      setBuiltinIngesting(null);
    }
  };

  const uploadFile = async (file: File) => {
    if (isJsonImportFile(file)) {
      setMode("import");
      if (!importName.trim()) {
        setImportName(file.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " "));
      }
      await importOWLFile(file);
      return;
    }

    setUploadState("uploading");
    setErrorMsg("");
    setResult(null);
    setExtractionRunId(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch(backendUrl("/api/v1/documents/upload"), {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          err.detail ?? err.error?.message ?? `Upload failed (${res.status})`
        );
      }

      const data: UploadResult = await res.json();
      setResult(data);
      loadDocuments();

      // Wait for ingestion pipeline (parse → chunk → embed) to finish
      await waitForDocumentReady(data.doc_id);
      loadDocuments();

      setUploadState("extracting");
      const runId = await triggerExtraction(
        data.doc_id,
        targetOntologyId || undefined,
      );
      setExtractionRunId(runId);
      setUploadState("success");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setUploadState("error");
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
  };

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title={mode === "extract" ? "Upload Document" : "Import Ontology"}
        subtitle={
          mode === "extract"
            ? "Ingest documents for ontology extraction"
            : "Import OWL, TTL, RDF, or graph/ontology JSON"
        }
        contentClassName="max-w-4xl"
        footer={
          <div className="flex gap-4 pb-1">
            <button
              onClick={() => setMode("extract")}
              className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${mode === "extract" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
            >
              Extract from Document
            </button>
            <button
              onClick={() => setMode("import")}
              className={`text-sm px-4 py-2 rounded-lg font-medium transition-colors ${mode === "import" ? "bg-blue-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
            >
              Import OWL / TTL / RDF / JSON
            </button>
          </div>
        }
      />

      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">

        {/* === IMPORT MODE === */}
        {mode === "import" && (
          <>
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5 space-y-4">
              <div>
                <label htmlFor="import-name" className="block text-sm font-medium text-gray-700 mb-1">
                  Ontology Name (optional)
                </label>
                <input
                  id="import-name"
                  type="text"
                  value={importName}
                  onChange={(e) => setImportName(e.target.value)}
                  placeholder="e.g., FIBO Financial Instruments"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                />
                <p className="mt-1 text-xs text-gray-400">
                  If blank, the name will be derived from the file.
                </p>
              </div>

              <div
                onClick={() => importFileRef.current?.click()}
                onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.add("border-blue-500", "bg-blue-50"); }}
                onDragLeave={(e) => { e.currentTarget.classList.remove("border-blue-500", "bg-blue-50"); }}
                onDrop={(e) => {
                  e.preventDefault();
                  e.stopPropagation();
                  e.currentTarget.classList.remove("border-blue-500", "bg-blue-50");
                  const file = e.dataTransfer.files?.[0];
                  if (file) importOWLFile(file);
                }}
                className="border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors border-gray-300 bg-white hover:border-blue-400 hover:bg-blue-50"
              >
                <input
                  ref={importFileRef}
                  type="file"
                  accept={ONTOLOGY_IMPORT_FILE_ACCEPT}
                  className="hidden"
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) importOWLFile(file);
                    e.target.value = "";
                  }}
                />
                <div className="text-4xl text-gray-300 mb-3">🦉</div>
                <p className="text-gray-600 font-medium">
                  Drop an OWL, Turtle, RDF, SKOS, or JSON graph/ontology file here — or click to browse
                </p>
                <p className="text-sm text-gray-400 mt-1">
                  Supported: .ttl, .owl, .rdf, .n3, .nt, .jsonld, .json, .xml, .skos
                </p>
              </div>
            </div>

            {importState === "uploading" && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
                <div className="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-blue-700 font-medium">Uploading file...</p>
              </div>
            )}

            {importState === "processing" && (
              <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
                <div className="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                <p className="text-blue-700 font-medium">
                  Importing ontology via ArangoRDF... this can take a few minutes for large files.
                </p>
              </div>
            )}

            {importState === "success" && importResult && (
              <div className="bg-green-50 border border-green-200 rounded-lg p-4">
                <p className="text-green-700 font-medium">Import successful</p>
                <div className="mt-2 text-sm text-green-600 space-y-1">
                  {importResult.ontology_id && (
                    <p><span className="font-mono">ontology_id:</span> {String(importResult.ontology_id)}</p>
                  )}
                  {importResult.name && (
                    <p><span className="font-mono">name:</span> {String(importResult.name)}</p>
                  )}
                  {importResult.class_count != null && (
                    <p><span className="font-mono">classes:</span> {String(importResult.class_count)}</p>
                  )}
                </div>
                <div className="mt-3 flex gap-3">
                  {importResult.ontology_id && (
                    <a
                      href={withBasePath(
                        `/dashboard?ontologyId=${encodeURIComponent(String(importResult.ontology_id))}`,
                      )}
                      className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
                    >
                      Open in Dashboard
                    </a>
                  )}
                  <a href={withBasePath("/library")} className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors">
                    View in Library
                  </a>
                  {importResult.ontology_id && (
                    <a href={withBasePath(`/ontology/edit?ontologyId=${importResult.ontology_id}`)} className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors">
                      Edit Graph
                    </a>
                  )}
                </div>
              </div>
            )}

            {importState === "error" && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-4">
                <p className="text-red-700 font-medium">Import failed</p>
                <p className="mt-1 text-sm text-red-600">{importError}</p>
              </div>
            )}
          </>
        )}

        {/* === EXTRACT MODE === */}
        {mode === "extract" && (
        <>
        {/* Target ontology selector */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <label
            htmlFor="target-ontology"
            className="block text-sm font-medium text-gray-700 mb-2"
          >
            Target Ontology
          </label>
          <select
            id="target-ontology"
            value={targetOntologyId}
            onChange={(e) => setTargetOntologyId(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Create New Ontology</option>
            {ontologyOptions.map((o) => (
              <option key={o._key} value={o._key}>
                {o.name} ({o.class_count} classes)
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-xs text-gray-400">
            {targetOntologyId
              ? "Extraction results will be merged into the selected ontology."
              : "A new ontology will be created from the extraction results."}
          </p>
        </div>

        {/* Built-in corpora on UC volume (not available via OS file picker) */}
        <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">
            Built-in sample documents
          </h2>
          <p className="text-xs text-gray-400 mb-4">
            Seeded under Unity Catalog workflow-data/builtin (from repo datasets/).
            Choose a file here instead of browsing your laptop.
          </p>
          {!builtinLoaded ? (
            <p className="text-sm text-gray-400">Loading volume catalog…</p>
          ) : builtinFiles.length === 0 ? (
            <p className="text-sm text-gray-400">
              No built-in files found yet. Redeploy the app or wait for startup seeding.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-lg max-h-64 overflow-y-auto">
              {builtinFiles.map((f) => (
                <li
                  key={f.path}
                  className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-gray-50"
                >
                  <div className="min-w-0 pr-3">
                    <p className="font-medium text-gray-800 truncate">{f.name}</p>
                    <p className="text-xs text-gray-400 truncate">{f.path}</p>
                  </div>
                  <button
                    type="button"
                    disabled={builtinIngesting !== null || uploadState === "uploading"}
                    onClick={() => ingestFromVolume(f.path, f.name)}
                    className="shrink-0 text-xs px-3 py-1.5 bg-gray-800 text-white rounded-lg hover:bg-gray-900 disabled:opacity-50 transition-colors font-medium"
                  >
                    {builtinIngesting === f.path ? "Starting…" : "Use this file"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Drop zone — local upload is copied to UC workflow-data/uploads by the API */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={`
            border-2 border-dashed rounded-xl p-12 text-center cursor-pointer
            transition-colors
            ${
              dragActive
                ? "border-blue-500 bg-blue-50"
                : "border-gray-300 bg-white hover:border-gray-400"
            }
          `}
        >
          <input
            ref={fileRef}
            type="file"
            accept={DOCUMENT_UPLOAD_FILE_ACCEPT}
            onChange={handleFileSelect}
            className="hidden"
          />
          <div className="text-4xl mb-3">📄</div>
          <p className="text-lg font-medium text-gray-700">
            Drop a file here or click to browse
          </p>
          <p className="mt-1 text-sm text-gray-400">
            Supported formats: PDF, DOCX, PPTX, Markdown. Files are stored on the UC volume
            under workflow-data/uploads, then ingested.
          </p>
        </div>

        {/* Upload status */}
        {uploadState === "uploading" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
            <div className="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-blue-700 font-medium">
              Uploading and processing document (parsing, chunking, embedding)…
            </p>
          </div>
        )}

        {uploadState === "extracting" && (
          <div className="bg-violet-50 border border-violet-200 rounded-lg p-4 flex items-center gap-3">
            <div className="h-5 w-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-violet-700 font-medium">
              Starting ontology extraction…
            </p>
          </div>
        )}

        {uploadState === "success" && result && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-green-700 font-medium">
              Upload successful — extraction {extractionRunId ? "started" : "queued"}
            </p>
            <div className="mt-2 text-sm text-green-600 space-y-1">
              <p>
                <span className="font-mono">doc_id:</span> {result.doc_id}
              </p>
              <p>
                <span className="font-mono">filename:</span> {result.filename}
              </p>
              {extractionRunId && (
                <p>
                  <span className="font-mono">run_id:</span> {extractionRunId}
                </p>
              )}
            </div>
            <div className="mt-3 flex gap-3">
              <a
                href={withBasePath(
                  extractionRunId ? `/pipeline?runId=${extractionRunId}` : "/pipeline",
                )}
                className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                View Extraction Pipeline →
              </a>
              <a
                href={withBasePath("/library")}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Ontology Library
              </a>
            </div>
          </div>
        )}

        {uploadState === "error" && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700 font-medium">Upload failed</p>
            <p className="mt-1 text-sm text-red-600">{errorMsg}</p>
          </div>
        )}

        {/* Document list */}
        {docsLoaded && (
          <section>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
              Recent Documents ({documents.length})
            </h2>
            {documents.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No documents uploaded yet.
              </p>
            ) : (
              <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 shadow-sm">
                {documents.map((doc) => (
                  <div
                    key={doc._key}
                    className="px-5 py-4 flex items-center justify-between"
                  >
                    <div>
                      <p className="font-medium text-gray-900">
                        {doc.filename}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {doc.mime_type} · {doc.chunk_count} chunks ·{" "}
                        {doc.upload_date
                          ? new Date(doc.upload_date).toLocaleDateString()
                          : ""}
                      </p>
                      {docOntologies[doc._key]?.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-1.5">
                          {docOntologies[doc._key].map((ont) => (
                            <a
                              key={ont._key}
                              href={withBasePath(`/ontology/edit?ontologyId=${ont._key}`)}
                              className="inline-flex items-center text-[11px] px-2 py-0.5 bg-blue-50 text-blue-700 rounded-full hover:bg-blue-100 transition-colors"
                              title={`View ontology: ${ont.name}`}
                            >
                              {ont.name}
                            </a>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      {(doc.status === "ready" || doc.status === "processed") && (
                        extractingDocs.has(doc._key) ? (
                          <span className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-violet-100 text-violet-700 rounded-lg font-medium">
                            <span className="h-3 w-3 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                            Extracting…
                          </span>
                        ) : (
                          <button
                            onClick={() => extractDocument(doc._key)}
                            className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
                          >
                            Extract
                          </button>
                        )
                      )}
                      <span
                        className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                          doc.status === "processed" || doc.status === "ready"
                            ? "bg-green-100 text-green-700"
                            : doc.status === "processing"
                              ? "bg-yellow-100 text-yellow-700"
                              : doc.status === "error"
                                ? "bg-red-100 text-red-700"
                                : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {doc.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
        </>
        )}
      </div>
    </main>
  );
}
