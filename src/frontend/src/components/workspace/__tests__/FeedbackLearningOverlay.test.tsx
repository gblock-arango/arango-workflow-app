import { render, screen, waitFor } from "@testing-library/react";
import FeedbackLearningOverlay from "../FeedbackLearningOverlay";

const loadFeedbackLearningArtifacts = jest.fn();

jest.mock("@/lib/feedbackLearning", () => ({
  loadFeedbackLearningArtifacts: (...args: unknown[]) => loadFeedbackLearningArtifacts(...args),
}));

const artifacts = {
  ontology_id: "onto_1",
  status: "ready",
  auto_apply: false,
  summary: {
    total_examples: 2,
    regression_candidates: 1,
    by_action: { edit: 1, reject: 1 },
    by_issue_reason: { hallucinated: 1, bad_label: 1 },
  },
  examples: [
    {
      decision_key: "d1",
      entity_key: "Customer",
      entity_type: "class",
      action: "edit",
      issue_reasons: ["bad_label"],
      prompt_guidance: "Prefer Customer.",
    },
  ],
  regression_candidates: [
    {
      decision_key: "d2",
      entity_key: "Ghost",
      entity_type: "class",
      action: "reject",
      issue_reasons: ["hallucinated"],
      prompt_guidance: "Do not extract unsupported classes.",
    },
  ],
  benchmark_fixture: {
    schema_version: "hitl-regression-v1",
    ontology_id: "onto_1",
    generated_from: "curation_decisions",
    documents: [
      {
        id: "hitl-d2-Ghost",
        text: "No source support.",
        gold_classes: [],
        gold_relations: [],
        negative_classes: [{ label: "Ghost", type: "" }],
        negative_relations: [],
      },
    ],
    summary: {
      documents: 1,
      negative_examples: 1,
      positive_classes: 1,
      positive_relations: 0,
    },
  },
};

describe("FeedbackLearningOverlay", () => {
  beforeEach(() => {
    loadFeedbackLearningArtifacts.mockReset();
    loadFeedbackLearningArtifacts.mockResolvedValue(artifacts);
  });

  it("loads scoped feedback artifacts and renders summaries", async () => {
    render(
      <FeedbackLearningOverlay
        ontologyId="onto_1"
        ontologyName="Customer Ontology"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(loadFeedbackLearningArtifacts).toHaveBeenCalledWith({
        ontologyId: "onto_1",
        limit: 100,
      });
    });

    expect(screen.getByText("Customer Ontology")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
    expect(screen.getByText("Prompt Guidance Examples (1)")).toBeInTheDocument();
    expect(screen.getByText("Regression Candidates (1)")).toBeInTheDocument();
    expect(screen.getByText("Prefer Customer.")).toBeInTheDocument();
    expect(screen.getByText("Do not extract unsupported classes.")).toBeInTheDocument();
    expect(screen.getAllByText(/hitl-regression-v1/).length).toBeGreaterThan(0);
  });

  it("shows an error when loading fails", async () => {
    loadFeedbackLearningArtifacts.mockRejectedValue(new Error("backend unavailable"));

    render(<FeedbackLearningOverlay onClose={() => {}} />);

    expect(await screen.findByText("backend unavailable")).toBeInTheDocument();
  });
});
