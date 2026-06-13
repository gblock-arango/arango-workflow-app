"use client";

import { api } from "@/lib/api-client";

export interface ExtractionPromptTemplate {
  key: string;
  description: string;
  system_prompt: string;
  user_prompt: string;
  has_override?: boolean;
  source?: "builtin" | "override";
}

export interface ExtractionPromptTemplateDraft {
  key: string;
  system_prompt: string;
  user_prompt: string;
}

export interface LastExtractionPromptPayload {
  found: boolean;
  run_id?: string;
  template_key?: string;
  step?: string;
  pass_number?: number;
  batch_idx?: number;
  model_name?: string;
  recorded_at?: number;
  actual_prompt: string;
  response_text: string;
}

export async function fetchExtractionPromptTemplates(): Promise<ExtractionPromptTemplate[]> {
  const payload = await api.get<{ templates: ExtractionPromptTemplate[] }>(
    "/api/v1/system/extraction-prompts/templates",
  );
  return payload.templates ?? [];
}

export async function saveExtractionPromptTemplate(
  draft: ExtractionPromptTemplateDraft,
): Promise<ExtractionPromptTemplate> {
  return api.put<ExtractionPromptTemplate>(
    `/api/v1/system/extraction-prompts/templates/${encodeURIComponent(draft.key)}`,
    {
      system_prompt: draft.system_prompt,
      user_prompt: draft.user_prompt,
    },
  );
}

export async function fetchLastExtractionPrompt(
  runId?: string | null,
): Promise<LastExtractionPromptPayload> {
  const qs = runId ? `?run_id=${encodeURIComponent(runId)}` : "";
  return api.get<LastExtractionPromptPayload>(`/api/v1/system/extraction-prompts/last${qs}`);
}
