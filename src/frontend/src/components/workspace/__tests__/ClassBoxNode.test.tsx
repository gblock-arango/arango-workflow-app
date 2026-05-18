import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";

jest.mock("reactflow", () => {
  const React = require("react");
  const actual = jest.requireActual("reactflow");
  return {
    ...actual,
    Handle: ({ type, position }: { type: string; position: string }) =>
      React.createElement("div", { "data-testid": `handle-${type}`, "data-position": position }),
    Position: actual.Position,
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement("div", null, children),
  };
});

import ClassBoxNode, { type ClassBoxNodeData } from "../ClassBoxNode";

function renderNode(overrides: Partial<ClassBoxNodeData> = {}) {
  const defaultData: ClassBoxNodeData = {
    label: "Person",
    uri: "http://example.org#Person",
    status: "approved",
    confidence: 0.9,
    headerColor: "#22c55e",
    borderColor: "#475569",
    properties: [],
    isSelected: false,
    ...overrides,
  };

  const props = {
    id: "Person",
    data: defaultData,
    type: "classBox" as const,
    selected: false,
    isConnectable: false,
    xPos: 0,
    yPos: 0,
    zIndex: 0,
    dragging: false,
  };

  return render(
    <ReactFlowProvider>
      <ClassBoxNode {...props} />
    </ReactFlowProvider>,
  );
}

describe("ClassBoxNode", () => {
  it("renders the class label", () => {
    renderNode({ label: "Vehicle" });
    expect(screen.getByText("Vehicle")).toBeInTheDocument();
  });

  it("shows 'No properties' when properties list is empty", () => {
    renderNode({ properties: [] });
    expect(screen.getByText("No properties")).toBeInTheDocument();
  });

  it("renders properties with their labels", () => {
    renderNode({
      properties: [
        { _key: "name", label: "name", range_datatype: "string" },
        { _key: "age", label: "age", range_datatype: "integer" },
      ],
    });
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("age")).toBeInTheDocument();
    expect(screen.getByText("string")).toBeInTheDocument();
    expect(screen.getByText("integer")).toBeInTheDocument();
  });

  it("shows overflow indicator when properties exceed max", () => {
    const manyProps = Array.from({ length: 15 }, (_, i) => ({
      _key: `prop_${i}`,
      label: `property_${i}`,
      range_datatype: "string",
    }));
    renderNode({ properties: manyProps });
    expect(screen.getByText("+3 more")).toBeInTheDocument();
  });

  it("applies selected styling when isSelected is true", () => {
    const { container } = renderNode({ isSelected: true });
    const box = container.firstChild?.firstChild as HTMLElement;
    expect(box.className).toContain("ring-2");
    expect(box.className).toContain("ring-indigo-400");
  });

  it("shows status dot for approved classes", () => {
    renderNode({ status: "approved" });
    const dot = screen.getByTitle("approved");
    expect(dot).toBeInTheDocument();
    expect(dot.className).toContain("bg-green-500");
  });

  it("renders source and target handles", () => {
    renderNode();
    expect(screen.getByTestId("handle-target")).toBeInTheDocument();
    expect(screen.getByTestId("handle-source")).toBeInTheDocument();
  });
});
