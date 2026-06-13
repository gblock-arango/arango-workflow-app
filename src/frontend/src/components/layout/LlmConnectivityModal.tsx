"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import {
  type LlmModelFocus,
  type LlmSettingsDraft,
  type LlmSettingsPayload,
  applyEmbeddingModelChange,
  applyProviderDefaults,
  draftFromSettings,
  fetchLlmSettings,
  readCachedLlmSettings,
  saveLlmSettings,
} from "@/lib/llmSettings";
import {
  useLlmConnectivityStatus,
  type LlmStatusPayload,
} from "@/lib/useLlmConnectivityStatus";

export interface LlmConnectivityModalProps {
  open: boolean;
  onClose: () => void;
  /** Highlight extraction vs embedding model field for the current page. */
  modelFocus?: LlmModelFocus;
}

function modelFieldClass(focused: boolean): string {
  return focused
    ? "rounded-lg border border-indigo-300 bg-indigo-50/40 p-2.5"
    : "rounded-lg border border-transparent p-2.5";
}

export default function LlmConnectivityModal({
  open,
  onClose,
  modelFocus,
}: LlmConnectivityModalProps) {
  const { status, loading, refresh } = useLlmConnectivityStatus();
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedSettings, setSavedSettings] = useState<LlmSettingsPayload | null>(null);
  const [draft, setDraft] = useState<LlmSettingsDraft | null>(null);

  useEffect(() => {
    if (!open) return;
    setSaveError(null);
    const cached = readCachedLlmSettings();
    if (cached) {
      setSavedSettings(cached);
      setDraft(draftFromSettings(cached));
    }
    let cancelled = false;
    setSettingsLoading(true);
    void fetchLlmSettings()
      .then((payload) => {
        if (cancelled) return;
        setSavedSettings(payload);
        setDraft(draftFromSettings(payload));
      })
      .catch((err) => {
        if (cancelled) return;
        if (!cached) {
          setSaveError(err instanceof Error ? err.message : "Could not load LLM settings");
        }
      })
      .finally(() => {
        if (!cancelled) setSettingsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (!open) return null;

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await saveLlmSettings(draft);
      setSavedSettings(saved);
      setDraft(draftFromSettings(saved));
      refresh({ force: true });
    } catch (err) {
      setSaveError(
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error
            ? err.message
            : "Save failed",
      );
    } finally {
      setSaving(false);
    }
  };

  const keyConfigured =
    savedSettings?.openai_api_key_configured ?? status?.openai_api_key_configured ?? false;

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/50"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-labelledby="llm-connectivity-title"
        aria-modal="true"
        className="w-full max-w-xl max-h-[90vh] overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-xl"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-gray-100 bg-white px-4 py-3">
          <div>
            <h2 id="llm-connectivity-title" className="text-sm font-semibold text-gray-900">
              LLM connection
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Choose provider and models for extraction and chunk embeddings.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 text-xs text-gray-500 hover:text-gray-800 font-medium px-1"
            aria-label="Close"
          >
            Close
          </button>
        </div>

        <div className="px-4 py-4 space-y-4">
          <section className="space-y-3">
            <div>
              <label htmlFor="llm-provider" className="block text-xs font-medium text-gray-700 mb-1">
                LLM provider
              </label>
              <select
                id="llm-provider"
                value={draft?.provider ?? "databricks"}
                disabled={!draft || saving}
                onChange={(event) => {
                  if (!draft) return;
                  setDraft(
                    applyProviderDefaults(
                      draft,
                      event.target.value as LlmSettingsDraft["provider"],
                    ),
                  );
                }}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 bg-white"
              >
                <option value="databricks">Databricks</option>
                <option value="openai">OpenAI</option>
              </select>
            </div>

            <div className={modelFieldClass(modelFocus === "extraction")}>
              <label
                htmlFor="llm-extraction-model"
                className="block text-xs font-medium text-gray-700 mb-1"
              >
                Extraction pipeline model
              </label>
              <input
                id="llm-extraction-model"
                type="text"
                value={draft?.extraction_model ?? ""}
                disabled={!draft || saving}
                onChange={(event) =>
                  setDraft((current) =>
                    current ? { ...current, extraction_model: event.target.value } : current,
                  )
                }
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-900"
                placeholder={savedSettings?.defaults?.extraction_model}
              />
              <p className="mt-1 text-[11px] text-gray-500">
                Default for {draft?.provider === "openai" ? "OpenAI" : "Databricks"}:{" "}
                <span className="font-mono">
                  {savedSettings?.defaults?.extraction_model ??
                    (draft?.provider === "openai"
                      ? "gpt-4o-mini"
                      : "databricks-meta-llama-3-3-70b-instruct")}
                </span>
              </p>
            </div>

            <div className={modelFieldClass(modelFocus === "embedding")}>
              <label
                htmlFor="llm-embedding-model"
                className="block text-xs font-medium text-gray-700 mb-1"
              >
                Chunk embedding model
              </label>
              <div className="flex gap-2 items-start">
                <input
                  id="llm-embedding-model"
                  type="text"
                  value={draft?.embedding_model ?? ""}
                  disabled={!draft || saving}
                  onChange={(event) =>
                    setDraft((current) =>
                      current
                        ? applyEmbeddingModelChange(current, event.target.value)
                        : current,
                    )
                  }
                  className="min-w-0 flex-1 rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-900"
                  placeholder={savedSettings?.defaults?.embedding_model}
                />
                <div className="w-24 shrink-0">
                  <label htmlFor="llm-embedding-dimension" className="sr-only">
                    Embedding dimension
                  </label>
                  <input
                    id="llm-embedding-dimension"
                    type="number"
                    min={1}
                    max={8192}
                    value={draft?.embedding_dimension ?? ""}
                    disabled={!draft || saving}
                    onChange={(event) => {
                      const parsed = Number.parseInt(event.target.value, 10);
                      setDraft((current) =>
                        current
                          ? {
                              ...current,
                              embedding_dimension:
                                Number.isFinite(parsed) && parsed > 0 ? parsed : current.embedding_dimension,
                            }
                          : current,
                      );
                    }}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-900"
                    aria-label="Embedding dimension"
                    title="Vector dimension (must match embedding model)"
                  />
                  <p className="mt-1 text-[10px] text-gray-500 text-center">dim</p>
                </div>
              </div>
              <p className="mt-1 text-[11px] text-gray-500">
                Default for {draft?.provider === "openai" ? "OpenAI" : "Databricks"}:{" "}
                <span className="font-mono">
                  {savedSettings?.defaults?.embedding_model ??
                    (draft?.provider === "openai"
                      ? "text-embedding-3-small"
                      : "databricks-bge-large-en")}
                </span>
                {" · "}
                dimension{" "}
                <span className="font-mono">
                  {savedSettings?.defaults?.embedding_dimension ??
                    (draft?.provider === "openai" ? 1536 : 1024)}
                </span>
              </p>
            </div>

            <div>
              <label htmlFor="openai-api-key" className="block text-xs font-medium text-gray-700 mb-1">
                OpenAI API key
              </label>
              <input
                id="openai-api-key"
                type="password"
                autoComplete="off"
                value={draft?.openai_api_key ?? ""}
                disabled={!draft || saving}
                onChange={(event) =>
                  setDraft((current) =>
                    current ? { ...current, openai_api_key: event.target.value } : current,
                  )
                }
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-900"
                placeholder={keyConfigured ? "Saved — paste to replace" : "sk-..."}
              />
              <p className="mt-1 text-[11px] text-gray-500">
                Required when provider is OpenAI. Stored on the app volume; leave blank to keep the
                current key.
              </p>
            </div>

            {saveError ? (
              <p className="text-xs text-red-700">{saveError}</p>
            ) : null}

            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => void handleSave()}
                disabled={!draft || saving || settingsLoading}
                className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 font-medium"
              >
                {saving ? "Saving…" : "Save settings"}
              </button>
              {settingsLoading ? (
                <span className="text-xs text-gray-500">Loading saved settings…</span>
              ) : null}
            </div>
          </section>

          <section className="border-t border-gray-100 pt-4 space-y-3">
            <ConnectivityDetails status={status} loading={loading} />
            <div className="flex items-center gap-4">
              <button
                type="button"
                onClick={() => refresh({ force: true })}
                className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
              >
                Re-test
              </button>
              <button
                type="button"
                onClick={onClose}
                className="text-xs text-gray-600 hover:text-gray-800"
              >
                Close
              </button>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function ConnectivityDetails({
  status,
  loading,
}: {
  status: LlmStatusPayload | null;
  loading: boolean;
}) {
  if (loading && !status) {
    return <p className="text-xs text-gray-500">Checking embedding and extraction models…</p>;
  }
  if (!status) {
    return <p className="text-xs text-gray-500">Connectivity status unavailable.</p>;
  }

  return (
    <>
      {!status.ok && status.summary ? (
        <p className="text-xs text-red-700">{status.summary}</p>
      ) : null}
      <dl className="space-y-2 text-xs text-gray-600">
        <div>
          <dt className="font-medium text-gray-500">Embedding model (live)</dt>
          <dd className="font-mono">
            {status.embedding_model || "—"}
            {status.embedding_dimension != null ? ` (dim=${status.embedding_dimension})` : ""}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-gray-500">Extraction model (live)</dt>
          <dd className="font-mono">{status.extraction_model || "—"}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-500">Provider (live)</dt>
          <dd>{status.provider}</dd>
        </div>
        <div>
          <dt className="font-medium text-gray-500">Embedding probe</dt>
          <dd className={status.embedding.ok ? "text-emerald-700" : "text-red-700"}>
            {status.embedding.message}
            {status.embedding.latency_ms != null ? ` (${status.embedding.latency_ms}ms)` : ""}
          </dd>
        </div>
        <div>
          <dt className="font-medium text-gray-500">Extraction probe</dt>
          <dd className={status.extraction.ok ? "text-emerald-700" : "text-red-700"}>
            {status.extraction.message}
            {status.extraction.latency_ms != null ? ` (${status.extraction.latency_ms}ms)` : ""}
          </dd>
        </div>
        {status.openai_base_url ? (
          <div>
            <dt className="font-medium text-gray-500">Base URL</dt>
            <dd className="break-all font-mono text-[10px]">{status.openai_base_url}</dd>
          </div>
        ) : null}
      </dl>
      <div className="text-[11px] text-gray-500 space-y-0.5">
        <p>
          API key on app: OpenAI {status.openai_api_key_configured ? "yes" : "no"}
          {" · "}
          Anthropic {status.anthropic_api_key_configured ? "yes" : "no"}
        </p>
      </div>
      {status.hints && status.hints.length > 0 ? (
        <ul className="space-y-1 text-[11px] text-amber-800 list-disc pl-4">
          {status.hints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
      {status.curl_examples && status.curl_examples.length > 0 ? (
        <div className="border-t border-gray-100 pt-2">
          <p className="text-[11px] font-medium text-gray-600 mb-1">
            Test from your shell (export OPENAI_API_KEY first):
          </p>
          {status.curl_examples.map((cmd) => (
            <pre
              key={cmd.slice(0, 40)}
              className="mt-1 text-[10px] bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto whitespace-pre-wrap break-all font-mono text-gray-800"
            >
              {cmd}
            </pre>
          ))}
        </div>
      ) : null}
    </>
  );
}
