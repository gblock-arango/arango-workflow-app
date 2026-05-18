import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReparentSelect from "@/components/graph/ReparentSelect";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: { post: jest.fn() },
  ApiError: class ApiError extends Error {
    status: number;
    body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

const mockClasses = [
  { _key: "cls_001", label: "Person" },
  { _key: "cls_002", label: "Organization" },
  { _key: "cls_003", label: "Employee" },
];

describe("ReparentSelect", () => {
  const onReparented = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (api.post as jest.Mock).mockResolvedValue({});
  });

  function renderComponent(currentParentKey?: string) {
    return render(
      <ReparentSelect
        ontologyId="onto_abc"
        classKey="cls_003"
        currentParentKey={currentParentKey}
        availableClasses={mockClasses}
        onReparented={onReparented}
      />,
    );
  }

  it("renders with current parent label", () => {
    renderComponent("cls_001");
    expect(screen.getByTestId("reparent-trigger")).toHaveTextContent("Person");
  });

  it("renders with 'None (root)' when no parent", () => {
    renderComponent();
    expect(screen.getByTestId("reparent-trigger")).toHaveTextContent("None (root)");
  });

  it("opens dropdown on click", () => {
    renderComponent();
    fireEvent.click(screen.getByTestId("reparent-trigger"));
    expect(screen.getByTestId("reparent-search")).toBeInTheDocument();
  });

  it("excludes own class from dropdown", () => {
    renderComponent();
    fireEvent.click(screen.getByTestId("reparent-trigger"));
    expect(screen.queryByText("Employee")).not.toBeInTheDocument();
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("calls API on selecting a new parent", async () => {
    renderComponent();
    fireEvent.click(screen.getByTestId("reparent-trigger"));
    fireEvent.click(screen.getByText("Organization"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_abc/edges",
        expect.objectContaining({
          edge_type: "subclass_of",
          _from: "ontology_classes/cls_003",
          _to: "ontology_classes/cls_002",
        }),
      );
    });
    expect(onReparented).toHaveBeenCalled();
  });

  it("filters classes by search term", () => {
    renderComponent();
    fireEvent.click(screen.getByTestId("reparent-trigger"));
    fireEvent.change(screen.getByTestId("reparent-search"), {
      target: { value: "org" },
    });
    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(screen.queryByText("Person")).not.toBeInTheDocument();
  });

  it("shows error on API failure", async () => {
    const { ApiError } = jest.requireMock("@/lib/api-client");
    (api.post as jest.Mock).mockRejectedValueOnce(
      new ApiError(500, { code: "INTERNAL", message: "Server error" }),
    );

    renderComponent();
    fireEvent.click(screen.getByTestId("reparent-trigger"));
    fireEvent.click(screen.getByText("Person"));

    await waitFor(() => {
      expect(screen.getByTestId("reparent-error")).toHaveTextContent("Server error");
    });
  });
});
