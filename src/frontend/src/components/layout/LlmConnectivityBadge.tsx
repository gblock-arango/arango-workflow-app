"use client";

import { useState } from "react";
import LlmConnectivityModal from "@/components/layout/LlmConnectivityModal";
import {
  useLlmConnectivityStatus,
  type LlmStatusPayload,
} from "@/lib/useLlmConnectivityStatus";
import type { LlmModelFocus } from "@/lib/llmSettings";

export type { LlmStatusPayload };

export default function LlmConnectivityBadge({
  modelFocus,
}: {
  /** Highlight extraction vs embedding model field in the settings modal. */
  modelFocus?: LlmModelFocus;
}) {
  const { status, loading } = useLlmConnectivityStatus();
  const [open, setOpen] = useState(false);

  const connected = status?.ok === true;
  const apiBusy = status?.provider === "busy";
  const dotClass = loading
    ? "bg-amber-400 animate-pulse"
    : connected
      ? "bg-emerald-500"
      : apiBusy
        ? "bg-amber-500"
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
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs shadow-sm hover:bg-gray-50 transition-colors max-w-md"
        title={buttonTitle}
        aria-label={buttonTitle}
        aria-haspopup="dialog"
        aria-expanded={open}
      >
        <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${dotClass}`} />
        <span className="text-gray-700 font-medium truncate">
          {loading
            ? "Checking LLM…"
            : connected
              ? "LLM connected"
              : apiBusy
                ? "API busy"
                : "LLM unavailable"}
        </span>
      </button>
      <LlmConnectivityModal
        open={open}
        onClose={() => setOpen(false)}
        modelFocus={modelFocus}
      />
    </>
  );
}
