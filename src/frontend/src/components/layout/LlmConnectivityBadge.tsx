"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api-client";

export interface LlmStatusPayload {
  ok: boolean;
  provider: string;
  embedding_model: string;
  extraction_model: string;
  openai_base_url?: string | null;
  openai_api_key_configured?: boolean;
  anthropic_api_key_configured?: boolean;
  summary?: string;
  hints?: string[];
  curl_examples?: string[];
  embedding: { ok: boolean; message: string; latency_ms?: number };
  extraction: { ok: boolean; message: string; latency_ms?: number };
}

export default function LlmConnectivityBadge() {
  const [status, setStatus] = useState<LlmStatusPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async (opts?: { force?: boolean }) => {
    setLoading(true);
    try {
      const qs = opts?.force ? "?force=true" : "";
      const data = await api.get<LlmStatusPayload>(`/api/v1/system/llm-status${qs}`);
      setStatus(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setStatus({
        ok: false,
        provider: "error",
        embedding_model: "",
        extraction_model: "",
        summary: `Probe request failed: ${msg}`,
        hints: ["Check that the workflow-app API is reachable from the browser."],
        embedding: { ok: false, message: msg },
        extraction: { ok: false, message: "Probe request failed" },
      });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Defer probe so page paint and primary API calls are not queued behind LLM checks.
    const defer = window.setTimeout(() => void refresh(), 2_000);
    const id = window.setInterval(() => void refresh(), 300_000);
    return () => {
      window.clearTimeout(defer);
      window.clearInterval(id);
    };
  }, [refresh]);

  const connected = status?.ok === true;
  const dotClass = loading
    ? "bg-amber-400 animate-pulse"
    : connected
      ? "bg-emerald-500"
      : "bg-red-500";

  const hoverDetail = status
    ? [
        status.summary,
        !status.embedding.ok ? `Embedding: ${status.embedding.message}` : null,
        !status.extraction.ok ? `Extraction: ${status.extraction.message}` : null,
        status.openai_api_key_configured === false
          ? "OPENAI_API_KEY not configured on app"
          : null,
      ]
        .filter(Boolean)
        .join("\n")
    : "";

  const buttonTitle =
    hoverDetail ||
    (loading
      ? "Checking embedding and extraction models"
      : connected
        ? "LLM probes succeeded"
        : "LLM probes failed — click for details");

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs shadow-sm hover:bg-gray-50 transition-colors max-w-md"
        title={buttonTitle}
        aria-label={buttonTitle}
        aria-expanded={open}
      >
        <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${dotClass}`} />
        <span className="text-gray-700 font-medium truncate">
          {loading ? "Checking LLM…" : connected ? "LLM connected" : "LLM unavailable"}
        </span>
      </button>
      {open && status && (
        <div
          className="absolute right-0 mt-1 z-30 w-[28rem] max-w-[95vw] rounded-lg border border-gray-200 bg-white p-3 shadow-lg text-left"
          role="dialog"
          aria-label="LLM connectivity details"
        >
          <div className="flex items-start justify-between gap-2 mb-1">
            <p className="text-xs font-semibold text-gray-800">LLM connectivity</p>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="shrink-0 text-xs text-gray-500 hover:text-gray-800 font-medium px-1"
              aria-label="Close"
            >
              Close
            </button>
          </div>
          {!status.ok && status.summary && (
            <p className="text-xs text-red-700 mb-2">{status.summary}</p>
          )}
          <dl className="space-y-2 text-xs text-gray-600">
            <div>
              <dt className="font-medium text-gray-500">Embedding model</dt>
              <dd className="font-mono">{status.embedding_model || "—"}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500">Extraction model</dt>
              <dd className="font-mono">{status.extraction_model || "—"}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500">Provider</dt>
              <dd>{status.provider}</dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500">Embedding probe</dt>
              <dd className={status.embedding.ok ? "text-emerald-700" : "text-red-700"}>
                {status.embedding.message}
                {status.embedding.latency_ms != null
                  ? ` (${status.embedding.latency_ms}ms)`
                  : ""}
              </dd>
            </div>
            <div>
              <dt className="font-medium text-gray-500">Extraction probe</dt>
              <dd className={status.extraction.ok ? "text-emerald-700" : "text-red-700"}>
                {status.extraction.message}
                {status.extraction.latency_ms != null
                  ? ` (${status.extraction.latency_ms}ms)`
                  : ""}
              </dd>
            </div>
            {status.openai_base_url && (
              <div>
                <dt className="font-medium text-gray-500">Base URL</dt>
                <dd className="break-all font-mono text-[10px]">{status.openai_base_url}</dd>
              </div>
            )}
          </dl>
          <div className="mt-2 text-[11px] text-gray-500 space-y-0.5">
            <p>
              API key on app: OpenAI{" "}
              {status.openai_api_key_configured ? "yes" : "no"}
              {" · "}
              Anthropic {status.anthropic_api_key_configured ? "yes" : "no"}
            </p>
          </div>
          {status.hints && status.hints.length > 0 && (
            <ul className="mt-2 space-y-1 text-[11px] text-amber-800 list-disc pl-4">
              {status.hints.map((h) => (
                <li key={h}>{h}</li>
              ))}
            </ul>
          )}
          {status.curl_examples && status.curl_examples.length > 0 && (
            <div className="mt-3 border-t border-gray-100 pt-2">
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
          )}
          <div className="mt-3 flex items-center gap-4">
            <button
              type="button"
              onClick={() => void refresh({ force: true })}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              Re-test
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-xs text-gray-600 hover:text-gray-800"
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
