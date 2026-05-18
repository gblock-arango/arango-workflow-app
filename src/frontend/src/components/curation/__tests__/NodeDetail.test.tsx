import { render, screen, fireEvent } from "@testing-library/react";
import NodeDetail from "@/components/curation/NodeDetail";
import type { OntologyClass } from "@/types/curation";

const mockNode: OntologyClass = {
  _key: "cls_001",
  uri: "http://example.org/ontology#Person",
  label: "Person",
  description: "A human being or individual.",
  rdf_type: "owl:Class",
  confidence: 0.85,
  status: "pending",
  ontology_id: "onto_abc",
  created: "2026-03-15T10:00:00Z",
  expired: null,
};

describe("NodeDetail", () => {
  it("renders node label and URI", () => {
    render(<NodeDetail node={mockNode} />);
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(
      screen.getByText("http://example.org/ontology#Person"),
    ).toBeInTheDocument();
  });

  it("renders status badge", () => {
    render(<NodeDetail node={mockNode} />);
    const badge = screen.getByTestId("node-status-badge");
    expect(badge).toHaveTextContent("Pending");
  });

  it("displays confidence bar", () => {
    render(<NodeDetail node={mockNode} />);
    expect(screen.getByTestId("confidence-bar")).toBeInTheDocument();
    expect(screen.getByText("85% — High")).toBeInTheDocument();
  });

  it("shows description text", () => {
    render(<NodeDetail node={mockNode} />);
    expect(
      screen.getByText("A human being or individual."),
    ).toBeInTheDocument();
  });

  it("opens and saves description editor", () => {
    const onDescChange = jest.fn();
    render(
      <NodeDetail node={mockNode} onDescriptionChange={onDescChange} />,
    );

    fireEvent.click(screen.getByTestId("edit-description-btn"));
    expect(screen.getByTestId("description-textarea")).toBeInTheDocument();

    fireEvent.change(screen.getByTestId("description-textarea"), {
      target: { value: "Updated description" },
    });
    fireEvent.click(screen.getByTestId("save-description-btn"));

    expect(onDescChange).toHaveBeenCalledWith("cls_001", "Updated description");
  });

  it("shows provenance and history buttons", () => {
    const onProvenance = jest.fn();
    const onHistory = jest.fn();
    render(
      <NodeDetail
        node={mockNode}
        onShowProvenance={onProvenance}
        onShowHistory={onHistory}
      />,
    );

    fireEvent.click(screen.getByTestId("show-provenance-btn"));
    expect(onProvenance).toHaveBeenCalledWith("cls_001");

    fireEvent.click(screen.getByTestId("show-history-btn"));
    expect(onHistory).toHaveBeenCalledWith("cls_001");
  });

  it("shows low confidence label for low values", () => {
    const lowConfNode = { ...mockNode, confidence: 0.3 };
    render(<NodeDetail node={lowConfNode} />);
    expect(screen.getByText("30% — Low")).toBeInTheDocument();
  });

  it("renders metadata fields", () => {
    render(<NodeDetail node={mockNode} />);
    expect(screen.getByText("onto_abc")).toBeInTheDocument();
  });
});
