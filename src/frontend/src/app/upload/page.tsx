"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  apiFetch,
  apiFetchLongRunning,
  apiUploadWithProgress,
  readApiErrorMessage,
  VOLUME_BROWSE_TIMEOUT_MS,
} from "@/lib/api-client";
import { withBasePath } from "@/lib/base-path";
import { scheduleAfterInitialPaint } from "@/lib/scheduleAfterInitialPaint";
import { formatOperationError } from "@/lib/upload-errors";
import AppHeader from "@/components/layout/AppHeader";
import AppLink from "@/components/layout/AppLink";
import OperationErrorPanel from "@/components/upload/OperationErrorPanel";
import {
  getUploadFileKind,
  isOntologyImportFilename,
  type UploadFileKind,
  UNIFIED_UPLOAD_FILE_ACCEPT,
} from "@/lib/fileAccept";

function UploadFileKindBadge({ kind }: { kind: UploadFileKind }) {
  if (kind === "ontology") {
    return (
      <span
        className="inline-flex shrink-0 items-center rounded-full bg-violet-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-violet-800"
        title="Direct graph import (no parse/chunk step)"
      >
        Ontology
      </span>
    );
  }
  return (
    <span
      className="inline-flex shrink-0 items-center rounded-full bg-sky-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-800"
      title="Next: Parse & Chunk on the embedding page"
    >
      Document
    </span>
  );
}

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
  doc_id: string;
  filename: string;
  status: string;
  mime_type: string;
  created_at?: string;
  chunk_count: number;
}

interface ImportResultData {
  ontology_id?: string;
  name?: string;
  class_count?: number;
  property_count?: number;
  triple_count?: number;
  vertex_count?: number;
  edge_count?: number;
  graph_name?: string;
  named_graph?: string;
}

interface ImportJobProgress {
  stage?: string;
  progress_pct?: number;
  status_message?: string;
}

function importStageLabel(stage?: string): string {
  switch (stage) {
    case "queued":
      return "Queued";
    case "schema":
      return "Schema migrations";
    case "loading":
      return "Loading graph";
    case "registry":
      return "Registry";
    case "completed":
      return "Complete";
    default:
      return stage ? stage.replace(/_/g, " ") : "Running";
  }
}

function LinearProgressBar({
  percent,
  message,
  stageLabel,
}: {
  percent: number;
  message?: string;
  stageLabel?: string;
}) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <div className="w-full space-y-2">
      <div className="flex items-center justify-between gap-2 text-xs">
        {stageLabel ? (
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 font-semibold uppercase tracking-wide text-blue-800">
            {stageLabel}
          </span>
        ) : (
          <span />
        )}
        <span className="tabular-nums text-blue-600">{clamped}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-blue-100">
        <div
          className="h-full rounded-full bg-blue-600 transition-all duration-300"
          style={{ width: `${clamped}%` }}
        />
      </div>
      {message ? <p className="text-sm text-blue-700">{message}</p> : null}
    </div>
  );
}

type UploadState = "idle" | "uploading" | "success" | "error";

export default function UploadPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [importState, setImportState] = useState<
    "idle" | "uploading" | "processing" | "success" | "error"
  >("idle");
  const [importResult, setImportResult] = useState<ImportResultData | null>(null);
  const [importProgress, setImportProgress] = useState<ImportJobProgress | null>(null);
  const [importError, setImportError] = useState("");
  const [docUploadPercent, setDocUploadPercent] = useState<number | null>(null);
  const [docUploadStage, setDocUploadStage] = useState("");
  const [builtinFiles, setBuiltinFiles] = useState<VolumeFileEntry[]>([]);
  const [builtinLoaded, setBuiltinLoaded] = useState(false);
  const [builtinIngesting, setBuiltinIngesting] = useState<string | null>(null);
  const [builtinOntologyFiles, setBuiltinOntologyFiles] = useState<VolumeFileEntry[]>([]);
  const [builtinOntologyLoaded, setBuiltinOntologyLoaded] = useState(false);
  const [builtinOntologyIngesting, setBuiltinOntologyIngesting] = useState<string | null>(null);
  const [volumeBuiltinPath, setVolumeBuiltinPath] = useState("");
  const [volumeUploadsHint, setVolumeUploadsHint] = useState("");
  const [volumeAccessMode, setVolumeAccessMode] = useState<string>("");
  const [volumeReachable, setVolumeReachable] = useState<boolean | null>(null);
  const [builtinLoadError, setBuiltinLoadError] = useState("");

  const loadDocuments = useCallback(async () => {
    try {
      const res = await api.get<{ data: DocumentEntry[] }>("/api/v1/embedding/status");
      setDocuments(res.data ?? []);
    } catch {
      setDocuments([]);
    } finally {
      setDocsLoaded(true);
    }
  }, []);

  const loadVolumeInfo = useCallback(async () => {
    try {
      const status = await api.get<{
        builtin_uc_path?: string;
        workflow_data_root?: string;
        uploads_subdir?: string;
        access_mode?: string;
        exists?: boolean;
        files_api_reachable?: boolean;
      }>("/api/v1/documents/volume/status");
      if (status.builtin_uc_path) {
        setVolumeBuiltinPath(status.builtin_uc_path);
      }
      if (status.workflow_data_root && status.uploads_subdir) {
        setVolumeUploadsHint(
          `${status.workflow_data_root}/${status.uploads_subdir}/<doc-id>/`,
        );
      }
      if (status.access_mode) {
        setVolumeAccessMode(status.access_mode);
      }
      if (typeof status.exists === "boolean") {
        setVolumeReachable(status.exists);
      }
    } catch {
      /* non-critical */
    }
  }, []);

  const fetchBuiltinBrowse = useCallback(
    async (path: string) =>
      api.get<{
        files: VolumeFileEntry[];
        exists?: boolean;
        access_mode?: string;
        files_api_reachable?: boolean;
      }>(path, { timeoutMs: VOLUME_BROWSE_TIMEOUT_MS }),
    [],
  );

  const loadBuiltinFiles = useCallback(async () => {
    setBuiltinLoadError("");
    const path = "/api/v1/documents/volume/browse?prefix=builtin&file_kind=document";
    try {
      const res = await fetchBuiltinBrowse(path);
      setBuiltinFiles(res.files ?? []);
      if (res.access_mode) {
        setVolumeAccessMode(res.access_mode);
      }
      if (typeof res.exists === "boolean") {
        setVolumeReachable(res.exists);
      }
      if ((res.files ?? []).length === 0 && res.exists === false) {
        setBuiltinLoadError(
          "Unity Catalog volume is not reachable from this app (check workflow-volume resource and READ/WRITE VOLUME grants).",
        );
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const timedOut = /timed out|AbortError|signal timed out/i.test(msg);
      setBuiltinFiles([]);
      setBuiltinLoadError(
        timedOut
          ? "Listing built-in documents from the UC volume timed out. Refresh the page to retry (results are cached server-side for 2 minutes)."
          : msg || "Failed to list built-in files from UC volume.",
      );
    } finally {
      setBuiltinLoaded(true);
    }
  }, [fetchBuiltinBrowse]);

  const loadBuiltinOntologies = useCallback(async () => {
    const path =
      "/api/v1/documents/volume/browse?prefix=builtin/ontologies&file_kind=ontology";
    try {
      const res = await fetchBuiltinBrowse(path);
      setBuiltinOntologyFiles(res.files ?? []);
    } catch {
      setBuiltinOntologyFiles([]);
    } finally {
      setBuiltinOntologyLoaded(true);
    }
  }, [fetchBuiltinBrowse]);

  useEffect(() => {
    const cancelCatalog = scheduleAfterInitialPaint(() => {
      void loadDocuments();
    }, 0);
    const cancelVolume = scheduleAfterInitialPaint(() => {
      void loadVolumeInfo();
    }, 400);
    const cancelBuiltinDocs = scheduleAfterInitialPaint(() => {
      void loadBuiltinFiles();
    }, 1200);
    const cancelBuiltinOnt = scheduleAfterInitialPaint(() => {
      void loadBuiltinOntologies();
    }, 2000);
    return () => {
      cancelCatalog();
      cancelVolume();
      cancelBuiltinDocs();
      cancelBuiltinOnt();
    };
  }, [loadDocuments, loadVolumeInfo, loadBuiltinFiles, loadBuiltinOntologies]);

  const importOWLFile = async (file: File) => {
    setImportState("uploading");
    setImportError("");
    setImportResult(null);
    setImportProgress(null);

    const formData = new FormData();
    formData.append("file", file);

    const label = file.name.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
    const id = `import_${Date.now().toString(36)}`;

    try {
      const params = new URLSearchParams({
        ontology_id: id,
        ontology_label: label,
      });
      const res = await apiFetchLongRunning(`/api/v1/ontology/import?${params}`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }

      // New contract (202): backend runs the import asynchronously and we poll
      // /import/{id}/status until it reports completed or failed. Large OWL
      // files can take minutes (per-triple writes against a remote cluster),
      // so a single synchronous HTTP request would exceed the proxy timeout.
      setImportState("processing");
      setImportProgress({
        stage: "queued",
        progress_pct: 0,
        status_message: "Import queued…",
      });
      const accepted = await res.json();
      const ontologyId = accepted.ontology_id || id;

      const finalResult = await pollImportStatus(ontologyId);
      setImportResult(finalResult);
      setImportState("success");
      loadDocuments();
    } catch (err) {
      setImportProgress(null);
      setImportError(
        formatOperationError(err, {
          operation: "Ontology file upload (POST /api/v1/ontology/import)",
          filename: file.name,
        }),
      );
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
      const statusRes = await apiFetch(
        `/api/v1/ontology/import/${encodeURIComponent(ontologyId)}/status`,
      );
      if (!statusRes.ok) {
        if (statusRes.status === 404) continue;
        throw new Error(await readApiErrorMessage(statusRes));
      }
      const job = await statusRes.json();
      if (job.status === "running") {
        setImportProgress({
          stage: job.stage as string | undefined,
          progress_pct:
            typeof job.progress_pct === "number" ? job.progress_pct : undefined,
          status_message: job.status_message as string | undefined,
        });
      }
      if (job.status === "completed") {
        const result = (job.result ?? {}) as Record<string, unknown>;
        setImportProgress({
          stage: "completed",
          progress_pct: 100,
          status_message: "Import complete",
        });
        return {
          ontology_id: (result.registry_key as string) ?? ontologyId,
          name: result.name as string | undefined,
          class_count: result.class_count as number | undefined,
          property_count: result.property_count as number | undefined,
          triple_count: result.triple_count as number | undefined,
          vertex_count: result.vertex_count as number | undefined,
          edge_count: result.edge_count as number | undefined,
          graph_name: result.graph_name as string | undefined,
          named_graph: result.named_graph as string | undefined,
        };
      }
      if (job.status === "failed") {
        const parts = [
          job.error || "Import failed on the server",
          job.error_kind ? `error_kind: ${job.error_kind}` : null,
          job.volume_path ? `volume_path: ${job.volume_path}` : null,
          job.filename ? `filename: ${job.filename}` : null,
          job.ontology_id ? `ontology_id: ${job.ontology_id}` : null,
        ].filter(Boolean);
        throw new Error(parts.join("\n"));
      }
    }
    throw new Error("Import timed out waiting for the server to finish");
  };

  const importOntologyFromVolume = async (path: string, displayName: string) => {
    setBuiltinOntologyIngesting(path);
    setImportState("uploading");
    setImportError("");
    setImportResult(null);
    setImportProgress(null);
    const label = displayName.replace(/\.[^.]+$/, "").replace(/[_-]/g, " ");
    const id = `import_${Date.now().toString(36)}`;
    try {
      const res = await apiFetchLongRunning("/api/v1/ontology/import-from-volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path,
          ontology_id: id,
          ontology_label: label,
        }),
      });
      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }
      setImportState("processing");
      setImportProgress({
        stage: "queued",
        progress_pct: 0,
        status_message: "Import queued…",
      });
      const accepted = await res.json();
      const ontologyId = accepted.ontology_id || id;
      const finalResult = await pollImportStatus(ontologyId);
      setImportResult(finalResult);
      setImportState("success");
      loadDocuments();
    } catch (err) {
      setImportProgress(null);
      setImportError(
        formatOperationError(err, {
          operation: "Builtin ontology import (POST /api/v1/ontology/import-from-volume)",
          path,
          filename: displayName,
        }),
      );
      setImportState("error");
    } finally {
      setBuiltinOntologyIngesting(null);
    }
  };

  const ingestFromVolume = async (path: string, displayName: string) => {
    setBuiltinIngesting(path);
    setUploadState("uploading");
    setErrorMsg("");
    setResult(null);
    try {
      const res = await apiFetchLongRunning("/api/v1/documents/ingest-from-volume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }
      const data: UploadResult = await res.json();
      setResult({ ...data, filename: data.filename || displayName });
      loadDocuments();
      setUploadState("success");
    } catch (err) {
      setErrorMsg(
        formatOperationError(err, {
          operation: "Document ingest from volume (POST /api/v1/documents/ingest-from-volume)",
          path,
          filename: displayName,
        }),
      );
      setUploadState("error");
    } finally {
      setBuiltinIngesting(null);
    }
  };

  const uploadFile = async (file: File) => {
    if (isOntologyImportFilename(file.name)) {
      setUploadState("idle");
      setResult(null);
      setErrorMsg("");
      await importOWLFile(file);
      return;
    }

    setImportState("idle");
    setImportResult(null);
    setImportError("");
    setUploadState("uploading");
    setErrorMsg("");
    setResult(null);
    setDocUploadPercent(0);
    setDocUploadStage("Uploading file to server…");
    const formData = new FormData();
    formData.append("file", file, file.name);

    const uploadHeaders: Record<string, string> = {};
    if (file.name) {
      uploadHeaders["X-Original-Filename"] = encodeURIComponent(file.name);
    }

    try {
      const res = await apiUploadWithProgress("/api/v1/documents/upload", formData, {
        headers: uploadHeaders,
        onProgress: ({ percent }) => {
          setDocUploadPercent(percent);
          if (percent >= 100) {
            setDocUploadStage("Saving to UC volume and registering catalog entry…");
          } else {
            setDocUploadStage("Uploading file to server…");
          }
        },
      });

      if (!res.ok) {
        throw new Error(await readApiErrorMessage(res));
      }

      const data: UploadResult = await res.json();
      setDocUploadPercent(100);
      setDocUploadStage("Complete");
      setResult(data);
      loadDocuments();
      setUploadState("success");
    } catch (err) {
      setErrorMsg(
        formatOperationError(err, {
          operation: "Document upload to UC volume (POST /api/v1/documents/upload)",
          filename: file.name,
        }),
      );
      setUploadState("error");
    } finally {
      setDocUploadPercent(null);
      setDocUploadStage("");
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
        title="Upload Documents"
        subtitle="Step 1: stage documents on Unity Catalog. Continue with Parse & Chunk, then run extraction on the Pipeline page."
        contentClassName="max-w-4xl"
      />

      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">

        <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">
            Built-in sample ontologies
          </h2>
          <p className="text-xs text-gray-400 mb-4">
            Seeded from repo <code className="text-gray-500">datasets/</code> under Unity Catalog
          </p>
          {!builtinOntologyLoaded ? (
            <p className="text-sm text-gray-400">Loading volume catalog…</p>
          ) : builtinOntologyFiles.length === 0 ? (
            <p className="text-sm text-gray-400">
              No built-in ontology files on the volume yet. Redeploy with dataset seeding or upload
              .ttl / .owl / .jsonld via the drop zone below.
            </p>
          ) : (
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-lg max-h-48 overflow-y-auto">
              {builtinOntologyFiles.map((f) => (
                <li
                  key={f.path}
                  className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-gray-50"
                >
                  <div className="min-w-0 pr-3">
                    <p className="font-medium text-gray-800 truncate flex items-center gap-2">
                      <span className="truncate">{f.name}</span>
                      <UploadFileKindBadge kind="ontology" />
                    </p>
                    <p className="text-xs text-gray-400 truncate">{f.path}</p>
                  </div>
                  <button
                    type="button"
                    disabled={builtinOntologyIngesting !== null || importState === "processing"}
                    onClick={() => void importOntologyFromVolume(f.path, f.name)}
                    className="shrink-0 text-xs px-3 py-1.5 bg-violet-700 text-white rounded-lg hover:bg-violet-800 disabled:opacity-50 transition-colors font-medium"
                  >
                    {builtinOntologyIngesting === f.path ? "Importing…" : "Use this file"}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Built-in sample domains on UC volume (not available via OS file picker) */}
        <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-1">
            Built-in sample documents
          </h2>
          <p className="text-xs text-gray-400 mb-4">
            Seeded from repo <code className="text-gray-500">datasets/</code> under Unity Catalog
          </p>
          {!builtinLoaded ? (
            <p className="text-sm text-gray-400">Loading volume catalog…</p>
          ) : builtinFiles.length === 0 ? (
            <div className="text-sm text-gray-400 space-y-1">
              {builtinLoadError ? (
                <p className="text-amber-700">{builtinLoadError}</p>
              ) : (
                <p>
                  No built-in files found yet. Run{" "}
                  <code className="text-gray-500">
                    scripts/seed_workflow_volume_datasets.py --force
                  </code>{" "}
                  from deploy, or redeploy with startup seeding enabled.
                </p>
              )}
              {volumeAccessMode === "files_api" && volumeReachable && (
                <p className="text-xs">
                  Listing via Databricks Files API (no local /Volumes mount).
                </p>
              )}
            </div>
          ) : (
            <ul className="divide-y divide-gray-100 border border-gray-100 rounded-lg max-h-64 overflow-y-auto">
              {builtinFiles.map((f) => (
                <li
                  key={f.path}
                  className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-gray-50"
                >
                  <div className="min-w-0 pr-3">
                    <p className="font-medium text-gray-800 truncate flex items-center gap-2">
                      <span className="truncate">{f.name}</span>
                      <UploadFileKindBadge kind={getUploadFileKind(f.name)} />
                    </p>
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
            accept={UNIFIED_UPLOAD_FILE_ACCEPT}
            onChange={handleFileSelect}
            className="hidden"
          />
          <div className="text-4xl mb-3">📄</div>
          <p className="text-lg font-medium text-gray-700">
            Drop a file here or click to browse
          </p>
          <p className="mt-1 text-sm text-gray-400">
            <strong>Documents:</strong> PDF, DOCX, PPTX, Markdown → file bytes on the UC volume
            {volumeUploadsHint ? (
              <>
                {" "}
                at <code className="text-gray-500 break-all">{volumeUploadsHint}</code>
              </>
            ) : (
              <> under workflow-data/uploads/</>
            )}
            ; catalog row in Unity Catalog <code className="text-gray-500">embedding_status</code>{" "}
            (not a copy of the file). Next: <strong>Parse &amp; Chunk</strong>, then start{" "}
            <strong>extraction</strong> on the Pipeline page (Arango is used only at extraction).
            <br />
            <strong>Ontology files:</strong> .ttl, .owl, .rdf, .n3, .nt, .jsonld, .json, .xml, .skos →
            direct graph import (no chunking).
          </p>
        </div>

        {importState === "uploading" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
            <div className="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-blue-700 font-medium">Uploading ontology file…</p>
          </div>
        )}

        {importState === "processing" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
            <LinearProgressBar
              percent={importProgress?.progress_pct ?? 5}
              stageLabel={importStageLabel(importProgress?.stage)}
              message={
                importProgress?.status_message ??
                "Importing ontology into ArangoDB… large files can take several minutes."
              }
            />
          </div>
        )}

        {importState === "success" && importResult && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-green-700 font-medium">Ontology import successful</p>
            <div className="mt-2 text-sm text-green-600 space-y-1">
              {importResult.ontology_id && (
                <p>
                  <span className="font-mono">ontology_id:</span>{" "}
                  {String(importResult.ontology_id)}
                </p>
              )}
              {importResult.name && (
                <p>
                  <span className="font-mono">name:</span> {String(importResult.name)}
                </p>
              )}
              {importResult.class_count != null && (
                <p>
                  <span className="font-mono">classes:</span> {String(importResult.class_count)}
                </p>
              )}
              {importResult.property_count != null && (
                <p>
                  <span className="font-mono">properties:</span>{" "}
                  {String(importResult.property_count)}
                </p>
              )}
              {importResult.triple_count != null && (
                <p>
                  <span className="font-mono">triples:</span> {String(importResult.triple_count)}
                </p>
              )}
              {importResult.vertex_count != null && (
                <p>
                  <span className="font-mono">vertices:</span>{" "}
                  {String(importResult.vertex_count)}
                </p>
              )}
              {importResult.edge_count != null && (
                <p>
                  <span className="font-mono">edges:</span> {String(importResult.edge_count)}
                </p>
              )}
              {importResult.graph_name && (
                <p>
                  <span className="font-mono">graph:</span> {importResult.graph_name}
                </p>
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
              <a
                href={withBasePath("/library")}
                className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                View in Library
              </a>
              {importResult.ontology_id && (
                <a
                  href={withBasePath(`/ontology/edit?ontologyId=${importResult.ontology_id}`)}
                  className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                >
                  Edit Graph
                </a>
              )}
            </div>
          </div>
        )}

        {importState === "error" && importError && (
          <OperationErrorPanel title="Ontology import failed" detail={importError} />
        )}

        {/* Document upload status */}
        {uploadState === "uploading" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 space-y-3">
            <LinearProgressBar
              percent={docUploadPercent ?? 0}
              stageLabel="Upload"
              message={docUploadStage || "Saving to UC volume…"}
            />
          </div>
        )}

        {uploadState === "success" && result && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-green-700 font-medium">Saved to UC volume (catalog registered)</p>
            <p className="mt-1 text-xs text-green-700">
              File content is on the UC volume; catalog metadata is in{" "}
              <code className="text-green-800">embedding_status</code>. Arango is not used until
              extraction.
            </p>
            <div className="mt-2 text-sm text-green-600 space-y-1">
              <p>
                <span className="font-mono">doc_id:</span> {result.doc_id}
              </p>
              <p>
                <span className="font-mono">filename:</span> {result.filename}
              </p>
              {result.volume_path && (
                <p>
                  <span className="font-mono">volume_path:</span> {result.volume_path}
                </p>
              )}
            </div>
            <p className="mt-2 text-sm text-green-700">
              Continue on{" "}
              <a
                href={withBasePath(`/embedding?doc=${result.doc_id}`)}
                className="font-semibold text-emerald-800 underline hover:text-emerald-900"
              >
                Parse &amp; Chunk
              </a>{" "}
              to parse and embed. When status is <code className="text-green-800">ready</code>, run
              extraction on the{" "}
              <AppLink
                href="/pipeline"
                className="font-semibold text-emerald-800 underline hover:text-emerald-900"
              >
                Pipeline
              </AppLink>{" "}
              page.
            </p>
          </div>
        )}

        {uploadState === "error" && errorMsg && (
          <OperationErrorPanel title="Upload failed" detail={errorMsg} />
        )}

        {/* Document list — UC embedding_status catalog only */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            Recent Documents
            {docsLoaded ? ` (${documents.length})` : ""}
          </h2>
          {!docsLoaded ? (
            <p className="text-gray-400 text-sm">Loading recent documents…</p>
          ) : documents.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No documents uploaded yet.
              </p>
            ) : (
              <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 shadow-sm">
                {documents.map((doc) => {
                  const fileKind = getUploadFileKind(doc.filename);
                  const isDocument = fileKind === "document";
                  return (
                  <div
                    key={doc.doc_id}
                    className="px-5 py-4 flex items-center justify-between"
                  >
                    <div>
                      <p className="font-medium text-gray-900 flex items-center gap-2">
                        <span className="truncate">{doc.filename}</span>
                        <UploadFileKindBadge kind={fileKind} />
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {doc.mime_type} · {doc.chunk_count} chunks ·{" "}
                        {doc.created_at
                          ? new Date(doc.created_at).toLocaleDateString()
                          : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {isDocument &&
                        (doc.status === "staged" || doc.status === "failed") && (
                        <a
                          href={withBasePath(`/embedding?doc=${doc.doc_id}`)}
                          className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700 transition-colors font-medium"
                        >
                          Parse &amp; chunk →
                        </a>
                      )}
                      {isDocument &&
                        (doc.status === "ready" || doc.status === "processed") && (
                        <AppLink
                          href="/pipeline"
                          className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
                        >
                          Run extraction →
                        </AppLink>
                      )}
                      <span
                        className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                          doc.status === "processed" || doc.status === "ready"
                            ? "bg-green-100 text-green-700"
                            : doc.status === "staged"
                              ? "bg-sky-100 text-sky-800"
                              : doc.status === "failed"
                                ? "bg-red-100 text-red-700"
                                : doc.status === "parsing" ||
                                    doc.status === "chunking" ||
                                    doc.status === "embedding" ||
                                    doc.status === "uploading"
                                  ? "bg-yellow-100 text-yellow-700"
                                  : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {doc.status}
                      </span>
                    </div>
                  </div>
                  );
                })}
              </div>
            )}
        </section>
      </div>
    </main>
  );
}
