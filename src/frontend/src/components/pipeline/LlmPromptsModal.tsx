"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";
import {
  type ExtractionPromptTemplate,
  type ExtractionPromptTemplateDraft,
  fetchExtractionPromptTemplates,
  fetchLastExtractionPrompt,
  saveExtractionPromptTemplate,
} from "@/lib/extractionPrompts";

export interface LlmPromptsModalProps {
  open: boolean;
  onClose: () => void;
  selectedRunId?: string | null;
}

function formatRecordedAt(ts?: number): string {
  if (!ts) return "";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "";
  }
}

export default function LlmPromptsModal({
  open,
  onClose,
  selectedRunId,
}: LlmPromptsModalProps) {
  const [templates, setTemplates] = useState<ExtractionPromptTemplate[]>([]);
  const [selectedKey, setSelectedKey] = useState<string>("");
  const [draft, setDraft] = useState<ExtractionPromptTemplateDraft | null>(null);
  const [templatesLoading, setTemplatesLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [actualPrompt, setActualPrompt] = useState("");
  const [responseText, setResponseText] = useState("");
  const [lastMeta, setLastMeta] = useState("");

  useEffect(() => {
    if (!open) return;
    setSaveError(null);
    let cancelled = false;
    setTemplatesLoading(true);
    void fetchExtractionPromptTemplates()
      .then((items) => {
        if (cancelled) return;
        setTemplates(items);
        const initial = items[0];
        if (initial) {
          setSelectedKey(initial.key);
          setDraft({
            key: initial.key,
            system_prompt: initial.system_prompt,
            user_prompt: initial.user_prompt,
          });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSaveError(err instanceof Error ? err.message : "Could not load templates");
        }
      })
      .finally(() => {
        if (!cancelled) setTemplatesLoading(false);
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

  useEffect(() => {
    if (!open) return;
    let cancelled = false;

    const refreshLast = () => {
      void fetchLastExtractionPrompt(selectedRunId)
        .then((payload) => {
          if (cancelled) return;
          if (!payload.found) {
            setActualPrompt("");
            setResponseText("");
            setLastMeta(
              selectedRunId
                ? "No extractor LLM call recorded yet for this run."
                : "No extractor LLM call recorded yet.",
            );
            return;
          }
          setActualPrompt(payload.actual_prompt || "");
          setResponseText(payload.response_text || "");
          const parts = [
            payload.template_key ? `template: ${payload.template_key}` : null,
            payload.step ? `step: ${payload.step}` : null,
            payload.model_name ? `model: ${payload.model_name}` : null,
            payload.recorded_at ? `at: ${formatRecordedAt(payload.recorded_at)}` : null,
            selectedRunId && payload.run_id && payload.run_id !== selectedRunId
              ? `from run: ${payload.run_id}`
              : null,
          ].filter(Boolean);
          setLastMeta(parts.join(" · "));
        })
        .catch(() => {
          if (!cancelled) setLastMeta("Could not load last extractor LLM call.");
        });
    };

    refreshLast();
    const timer = window.setInterval(refreshLast, 3000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [open, selectedRunId]);

  const handleTemplateChange = (key: string) => {
    setSelectedKey(key);
    const template = templates.find((item) => item.key === key);
    if (!template) return;
    setDraft({
      key: template.key,
      system_prompt: template.system_prompt,
      user_prompt: template.user_prompt,
    });
    setSaveError(null);
  };

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await saveExtractionPromptTemplate(draft);
      setTemplates((current) =>
        current.map((item) => (item.key === saved.key ? { ...item, ...saved } : item)),
      );
      setDraft({
        key: saved.key,
        system_prompt: saved.system_prompt,
        user_prompt: saved.user_prompt,
      });
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

  if (!open) return null;

  const selectedTemplate = templates.find((item) => item.key === selectedKey);

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
        aria-labelledby="llm-prompts-title"
        aria-modal="true"
        className="w-full max-w-5xl max-h-[92vh] overflow-y-auto rounded-xl border border-gray-200 bg-white shadow-xl"
      >
        <div className="sticky top-0 z-10 flex items-start justify-between gap-3 border-b border-gray-100 bg-white px-4 py-3">
          <div>
            <h2 id="llm-prompts-title" className="text-sm font-semibold text-gray-900">
              LLM prompts
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Debug extractor templates, the latest rendered prompt, and the latest LLM response.
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

        <div className="px-4 py-4 space-y-5">
          <section className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Prompt template
              </h3>
              {selectedTemplate?.source === "override" ? (
                <span className="text-[11px] text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded">
                  UC override
                </span>
              ) : null}
            </div>
            <div>
              <label htmlFor="prompt-template-key" className="block text-xs font-medium text-gray-700 mb-1">
                Template
              </label>
              <select
                id="prompt-template-key"
                value={selectedKey}
                disabled={templatesLoading || saving || templates.length === 0}
                onChange={(event) => handleTemplateChange(event.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm text-gray-900 bg-white"
              >
                {templates.map((template) => (
                  <option key={template.key} value={template.key}>
                    {template.key}
                    {template.description ? ` — ${template.description}` : ""}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="prompt-system-template" className="block text-xs font-medium text-gray-700 mb-1">
                System prompt
              </label>
              <textarea
                id="prompt-system-template"
                value={draft?.system_prompt ?? ""}
                disabled={!draft || saving}
                onChange={(event) =>
                  setDraft((current) =>
                    current ? { ...current, system_prompt: event.target.value } : current,
                  )
                }
                rows={10}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-mono text-gray-900"
              />
            </div>
            <div>
              <label htmlFor="prompt-user-template" className="block text-xs font-medium text-gray-700 mb-1">
                User prompt
              </label>
              <textarea
                id="prompt-user-template"
                value={draft?.user_prompt ?? ""}
                disabled={!draft || saving}
                onChange={(event) =>
                  setDraft((current) =>
                    current ? { ...current, user_prompt: event.target.value } : current,
                  )
                }
                rows={8}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-mono text-gray-900"
              />
            </div>
            {saveError ? <p className="text-xs text-red-700">{saveError}</p> : null}
            <button
              type="button"
              onClick={() => void handleSave()}
              disabled={!draft || saving || templatesLoading}
              className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 font-medium"
            >
              {saving ? "Saving…" : "Save template"}
            </button>
          </section>

          <section className="space-y-2 border-t border-gray-100 pt-4">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Prompt actual
              </h3>
              {lastMeta ? <span className="text-[11px] text-gray-500">{lastMeta}</span> : null}
            </div>
            <textarea
              readOnly
              value={actualPrompt}
              rows={12}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800"
              placeholder={
                selectedRunId
                  ? "Waiting for an extractor LLM call on this run…"
                  : "Waiting for an extractor LLM call…"
              }
            />
          </section>

          <section className="space-y-2 border-t border-gray-100 pt-4">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
              LLM results
            </h3>
            <textarea
              readOnly
              value={responseText}
              rows={12}
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-xs font-mono text-gray-800"
              placeholder="Latest extractor response will appear here."
            />
          </section>

          <div className="flex justify-end border-t border-gray-100 pt-3">
            <button
              type="button"
              onClick={onClose}
              className="text-xs text-gray-600 hover:text-gray-800"
            >
              Close
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
