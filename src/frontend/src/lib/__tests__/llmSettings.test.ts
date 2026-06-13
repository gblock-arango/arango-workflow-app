import {
  LLM_DEFAULT_MODELS,
  applyEmbeddingModelChange,
  applyProviderDefaults,
  defaultEmbeddingDimensionForModel,
  defaultModelsForProvider,
  normalizeUiProvider,
} from "@/lib/llmSettings";

describe("llmSettings", () => {
  it("normalizes provider aliases", () => {
    expect(normalizeUiProvider("databricks_serving")).toBe("databricks");
    expect(normalizeUiProvider("openai")).toBe("openai");
  });

  it("exposes provider-specific default models", () => {
    expect(defaultModelsForProvider("databricks")).toEqual(LLM_DEFAULT_MODELS.databricks);
    expect(defaultModelsForProvider("openai")).toEqual(LLM_DEFAULT_MODELS.openai);
  });

  it("switches default models when provider changes and values still match defaults", () => {
    const draft = {
      provider: "databricks" as const,
      extraction_model: LLM_DEFAULT_MODELS.databricks.extraction_model,
      embedding_model: LLM_DEFAULT_MODELS.databricks.embedding_model,
      embedding_dimension: LLM_DEFAULT_MODELS.databricks.embedding_dimension,
      openai_api_key: "",
    };
    const next = applyProviderDefaults(draft, "openai");
    expect(next.provider).toBe("openai");
    expect(next.extraction_model).toBe(LLM_DEFAULT_MODELS.openai.extraction_model);
    expect(next.embedding_model).toBe(LLM_DEFAULT_MODELS.openai.embedding_model);
    expect(next.embedding_dimension).toBe(LLM_DEFAULT_MODELS.openai.embedding_dimension);
  });

  it("updates dimension when embedding model changes and dimension was derived", () => {
    const draft = {
      provider: "openai" as const,
      extraction_model: "gpt-4o-mini",
      embedding_model: "text-embedding-3-small",
      embedding_dimension: defaultEmbeddingDimensionForModel("text-embedding-3-small"),
      openai_api_key: "",
    };
    const next = applyEmbeddingModelChange(draft, "databricks-bge-large-en");
    expect(next.embedding_model).toBe("databricks-bge-large-en");
    expect(next.embedding_dimension).toBe(1024);
  });
});
