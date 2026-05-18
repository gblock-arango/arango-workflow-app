import { render, screen } from "@testing-library/react";

jest.mock("sigma/rendering", () => ({
  __esModule: true,
  NodeCircleProgram: class {},
  EdgeArrowProgram: class {},
  EdgeRectangleProgram: class {},
}));

jest.mock("@sigma/edge-curve", () => ({
  __esModule: true,
  EdgeCurvedArrowProgram: class {},
  indexParallelEdgesIndex: () => {},
}));

jest.mock("@sigma/node-border", () => ({
  __esModule: true,
  createNodeBorderProgram: () => class {},
}));

jest.mock("sigma", () => ({
  __esModule: true,
  default: class MockSigma {
    constructor() {
      /* Sigma touches WebGL at import in real package; mocked for JSDOM. */
    }

    on() {
      return this;
    }

    kill() {}

    refresh() {}

    resize() {}

    getDimensions() {
      return { width: 800, height: 600 };
    }

    getBBox() {
      return { x: [0, 100] as [number, number], y: [0, 100] as [number, number] };
    }

    getCamera() {
      return {
        setState: () => {},
        getState: () => ({ ratio: 1, angle: 0, x: 0, y: 0 }),
        animate: () => {},
      };
    }

    getMouseCaptor() {
      return { on: () => {} };
    }

    getNodeDisplayData() {
      return { x: 400, y: 300, size: 10, color: "#000", label: "test" };
    }

    graphToViewport() {
      return { x: 400, y: 300 };
    }

    viewportToFramedGraph() {
      return { x: 0.5, y: 0.5 };
    }

    getStagePadding() {
      return 40;
    }

    setSetting() {}
  },
}));

import SigmaCanvas, { type SigmaViewportApi } from "@/components/workspace/SigmaCanvas";

describe("SigmaCanvas", () => {
  beforeAll(() => {
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  it("shows empty state when there are no classes", () => {
    render(
      <SigmaCanvas
        classes={[]}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
      />,
    );
    expect(screen.getByTestId("sigma-empty")).toBeInTheDocument();
    expect(screen.getByText(/No ontology data available/i)).toBeInTheDocument();
  });

  it("exposes focusNode in the viewport API", () => {
    let capturedApi: SigmaViewportApi | null = null;
    render(
      <SigmaCanvas
        classes={[
          {
            _key: "Person",
            label: "Person",
            uri: "http://example.org#Person",
            ontology_id: "test",
            status: "approved",
            confidence: 0.9,
            rdf_type: "owl:Class",
          },
        ]}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
        onViewportApi={(api) => {
          capturedApi = api;
        }}
      />,
    );
    expect(capturedApi).not.toBeNull();
    expect(capturedApi!.focusNode).toBeInstanceOf(Function);
    // focusNode should not throw even if the node doesn't exist in the mock
    expect(() => capturedApi!.focusNode("Person")).not.toThrow();
    expect(() => capturedApi!.focusNode("NonExistent")).not.toThrow();
  });

  it("accepts selectedNodeKey prop without crashing", () => {
    render(
      <SigmaCanvas
        classes={[
          {
            _key: "Person",
            label: "Person",
            uri: "http://example.org#Person",
            ontology_id: "test",
            status: "approved",
            confidence: 0.9,
            rdf_type: "owl:Class",
          },
        ]}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
        selectedNodeKey="Person"
      />,
    );
    // No crash means the prop is accepted and processed
    expect(true).toBe(true);
  });
});
