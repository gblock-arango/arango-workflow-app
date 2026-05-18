import { loadFeedbackLearningArtifacts } from "../feedbackLearning";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
  },
}));

describe("loadFeedbackLearningArtifacts", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockResolvedValue({ auto_apply: false });
  });

  it("calls the unscoped endpoint by default", async () => {
    await loadFeedbackLearningArtifacts();

    expect(get).toHaveBeenCalledWith("/api/v1/admin/feedback-learning");
  });

  it("adds ontology and limit query params", async () => {
    await loadFeedbackLearningArtifacts({ ontologyId: "onto 1", limit: 25 });

    expect(get).toHaveBeenCalledWith(
      "/api/v1/admin/feedback-learning?ontology_id=onto+1&limit=25",
    );
  });
});
