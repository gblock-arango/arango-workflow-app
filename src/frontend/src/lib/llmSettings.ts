"use client";

import { api } from "@/lib/api-client";

export type LlmUiProvider = "databricks" | "openai";
export type LlmModelFocus = "extraction" | "embedding";

export const LLM_SETTINGS_STORAGE_KEY = "aoe-llm-settings";

export const LLM_DEFAULT_MODELS: Record<
  LlmUiProvider,
  { extraction_model: string; embedding_model: string; embedding_dimension: number }
> = {
  databricks: {
    extraction_model: "databricks-meta-llama-3-3-70b-instruct",
    embedding_model: "databricks-bge-large-en",
    embedding_dimension: 1024,
  },
  openai: {
    extraction_model: "gpt-4o-mini",
    embedding_model: "text-embedding-3-small",
    embedding_dimension: 1536,
  },
};

export interface LlmSettingsPayload {
  provider: LlmUiProvider;
  extraction_model: string;
  embedding_model: string;
  embedding_dimension: number;
  openai_api_key_configured?: boolean;
  defaults?: {
    extraction_model: string;
    embedding_model: string;
    embedding_dimension: number;
  };
}

export interface LlmSettingsDraft {
  provider: LlmUiProvider;
  extraction_model: string;
  embedding_model: string;
  embedding_dimension: number;
  openai_api_key: string;
}

export function defaultModelsForProvider(provider: LlmUiProvider) {
  return LLM_DEFAULT_MODELS[provider];
}

/** Best-effort dimension hint from model name (mirrors backend logic). */
export function defaultEmbeddingDimensionForModel(model: string): number {
  const m = model.toLowerCase();
  if (m.includes("text-embedding-3") || m.includes("ada")) return 1536;
  if (m.includes("bge-small") || m.includes("bge_small")) return 384;
  if (m.includes("bge-base") || m.includes("bge_base")) return 768;
  if (
    m.includes("bge") ||
    m.includes("gte") ||
    m.includes("e5") ||
    m.includes("qwen") ||
    m.includes("embedding") ||
    m.includes("databricks-")
  ) {
    return 1024;
  }
  return 1536;
}

export function normalizeUiProvider(raw: string | null | undefined): LlmUiProvider {
  const value = (raw || "").trim().toLowerCase();
  if (value === "databricks" || value === "databricks_serving") {
    return "databricks";
  }
  return "openai";
}

export function readCachedLlmSettings(): LlmSettingsPayload | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(LLM_SETTINGS_STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<LlmSettingsPayload>;
    const provider = normalizeUiProvider(parsed.provider);
    const defaults = defaultModelsForProvider(provider);
    return {
      provider,
      extraction_model: (parsed.extraction_model || defaults.extraction_model).trim(),
      embedding_model: (parsed.embedding_model || defaults.embedding_model).trim(),
      embedding_dimension:
        typeof parsed.embedding_dimension === "number" && parsed.embedding_dimension > 0
          ? parsed.embedding_dimension
          : defaults.embedding_dimension,
      openai_api_key_configured: parsed.openai_api_key_configured,
      defaults,
    };
  } catch {
    return null;
  }
}

export function writeCachedLlmSettings(settings: LlmSettingsPayload): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(
      LLM_SETTINGS_STORAGE_KEY,
      JSON.stringify({
        provider: settings.provider,
        extraction_model: settings.extraction_model,
        embedding_model: settings.embedding_model,
        embedding_dimension: settings.embedding_dimension,
        openai_api_key_configured: settings.openai_api_key_configured,
      }),
    );
  } catch {
    // ignore quota / private mode
  }
}

export async function fetchLlmSettings(): Promise<LlmSettingsPayload> {
  const payload = await api.get<LlmSettingsPayload>("/api/v1/system/llm-settings");
  const provider = normalizeUiProvider(payload.provider);
  const normalized: LlmSettingsPayload = {
    provider,
    extraction_model: (payload.extraction_model || defaultModelsForProvider(provider).extraction_model).trim(),
    embedding_model: (payload.embedding_model || defaultModelsForProvider(provider).embedding_model).trim(),
    embedding_dimension:
      typeof payload.embedding_dimension === "number" && payload.embedding_dimension > 0
        ? payload.embedding_dimension
        : defaultEmbeddingDimensionForModel(payload.embedding_model || ""),
    openai_api_key_configured: payload.openai_api_key_configured,
    defaults: payload.defaults ?? defaultModelsForProvider(provider),
  };
  writeCachedLlmSettings(normalized);
  return normalized;
}

export async function saveLlmSettings(draft: LlmSettingsDraft): Promise<LlmSettingsPayload> {
  const body: Record<string, string | number> = {
    provider: draft.provider,
    extraction_model: draft.extraction_model.trim(),
    embedding_model: draft.embedding_model.trim(),
    embedding_dimension: draft.embedding_dimension,
  };
  if (draft.openai_api_key.trim()) {
    body.openai_api_key = draft.openai_api_key.trim();
  }
  const saved = await api.put<LlmSettingsPayload>("/api/v1/system/llm-settings", body);
  const provider = normalizeUiProvider(saved.provider);
  const normalized: LlmSettingsPayload = {
    provider,
    extraction_model: (saved.extraction_model || draft.extraction_model).trim(),
    embedding_model: (saved.embedding_model || draft.embedding_model).trim(),
    embedding_dimension:
      typeof saved.embedding_dimension === "number" && saved.embedding_dimension > 0
        ? saved.embedding_dimension
        : draft.embedding_dimension,
    openai_api_key_configured:
      saved.openai_api_key_configured ?? Boolean(draft.openai_api_key.trim()),
    defaults: saved.defaults ?? defaultModelsForProvider(provider),
  };
  writeCachedLlmSettings(normalized);
  return normalized;
}

export function draftFromSettings(settings: LlmSettingsPayload): LlmSettingsDraft {
  return {
    provider: settings.provider,
    extraction_model: settings.extraction_model,
    embedding_model: settings.embedding_model,
    embedding_dimension: settings.embedding_dimension,
    openai_api_key: "",
  };
}

export function applyProviderDefaults(
  draft: LlmSettingsDraft,
  nextProvider: LlmUiProvider,
): LlmSettingsDraft {
  const currentDefaults = defaultModelsForProvider(draft.provider);
  const nextDefaults = defaultModelsForProvider(nextProvider);
  const extractionMatchesDefault =
    draft.extraction_model.trim() === currentDefaults.extraction_model;
  const embeddingMatchesDefault =
    draft.embedding_model.trim() === currentDefaults.embedding_model;
  const dimensionMatchesDefault =
    draft.embedding_dimension === currentDefaults.embedding_dimension ||
    draft.embedding_dimension ===
      defaultEmbeddingDimensionForModel(draft.embedding_model);
  return {
    ...draft,
    provider: nextProvider,
    extraction_model: extractionMatchesDefault
      ? nextDefaults.extraction_model
      : draft.extraction_model,
    embedding_model: embeddingMatchesDefault
      ? nextDefaults.embedding_model
      : draft.embedding_model,
    embedding_dimension: dimensionMatchesDefault
      ? nextDefaults.embedding_dimension
      : draft.embedding_dimension,
  };
}

export function applyEmbeddingModelChange(
  draft: LlmSettingsDraft,
  embeddingModel: string,
): LlmSettingsDraft {
  const previousSuggested = defaultEmbeddingDimensionForModel(draft.embedding_model);
  const dimensionLooksDerived = draft.embedding_dimension === previousSuggested;
  return {
    ...draft,
    embedding_model: embeddingModel,
    embedding_dimension: dimensionLooksDerived
      ? defaultEmbeddingDimensionForModel(embeddingModel)
      : draft.embedding_dimension,
  };
}
