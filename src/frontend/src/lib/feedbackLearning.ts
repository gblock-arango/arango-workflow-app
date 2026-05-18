import { api } from "@/lib/api-client";

export interface FeedbackLearningExample {
  decision_key?: string | null;
  run_id?: string | null;
  entity_key?: string | null;
  entity_type?: string | null;
  action?: string | null;
  issue_reasons: string[];
  notes?: string | null;
  changed_fields?: string[];
  before?: Record<string, unknown>;
  after?: Record<string, unknown>;
  prompt_guidance?: string;
}

export interface HitlRegressionFixtureDocument {
  id: string;
  text: string;
  gold_classes: Array<Record<string, unknown>>;
  gold_relations: Array<Record<string, unknown>>;
  negative_classes: Array<Record<string, unknown>>;
  negative_relations: Array<Record<string, unknown>>;
  source_meta?: Record<string, unknown>;
}

export interface HitlRegressionFixture {
  schema_version: "hitl-regression-v1";
  ontology_id?: string | null;
  generated_from: string;
  documents: HitlRegressionFixtureDocument[];
  summary: {
    documents: number;
    negative_examples: number;
    positive_classes: number;
    positive_relations: number;
  };
}

export interface FeedbackLearningArtifacts {
  ontology_id?: string | null;
  status: "ready" | "not_available" | string;
  auto_apply: false;
  summary: {
    total_examples: number;
    regression_candidates: number;
    by_action: Record<string, number>;
    by_issue_reason: Record<string, number>;
  };
  examples: FeedbackLearningExample[];
  regression_candidates: FeedbackLearningExample[];
  benchmark_fixture: HitlRegressionFixture;
}

export async function loadFeedbackLearningArtifacts(options: {
  ontologyId?: string | null;
  limit?: number;
} = {}): Promise<FeedbackLearningArtifacts> {
  const params = new URLSearchParams();
  if (options.ontologyId) params.set("ontology_id", options.ontologyId);
  if (options.limit != null) params.set("limit", String(options.limit));
  const suffix = params.toString() ? `?${params.toString()}` : "";
  return api.get<FeedbackLearningArtifacts>(`/api/v1/admin/feedback-learning${suffix}`);
}
