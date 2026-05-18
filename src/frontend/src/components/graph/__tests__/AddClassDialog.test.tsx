import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AddClassDialog from "@/components/graph/AddClassDialog";
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
];

describe("AddClassDialog", () => {
  const onCreated = jest.fn();
  const onClose = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (api.post as jest.Mock).mockResolvedValue({});
  });

  function renderDialog() {
    return render(
      <AddClassDialog
        ontologyId="onto_abc"
        existingClasses={mockClasses}
        onCreated={onCreated}
        onClose={onClose}
      />,
    );
  }

  it("renders the dialog with all fields", () => {
    renderDialog();
    expect(screen.getByText("Add Class")).toBeInTheDocument();
    expect(screen.getByTestId("class-label-input")).toBeInTheDocument();
    expect(screen.getByTestId("class-desc-input")).toBeInTheDocument();
    expect(screen.getByTestId("class-uri-input")).toBeInTheDocument();
    expect(screen.getByTestId("parent-class-trigger")).toBeInTheDocument();
  });

  it("auto-generates URI from label", () => {
    renderDialog();
    fireEvent.change(screen.getByTestId("class-label-input"), {
      target: { value: "Financial Transaction" },
    });
    expect(screen.getByText(/Financial_Transaction/)).toBeInTheDocument();
  });

  it("disables create button when label is empty", () => {
    renderDialog();
    expect(screen.getByTestId("create-class-btn")).toBeDisabled();
  });

  it("submits class creation on form submit", async () => {
    renderDialog();
    fireEvent.change(screen.getByTestId("class-label-input"), {
      target: { value: "Animal" },
    });
    fireEvent.click(screen.getByTestId("create-class-btn"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_abc/classes",
        expect.objectContaining({ label: "Animal" }),
      );
    });
    expect(onCreated).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("creates subclass edge when parent is selected", async () => {
    renderDialog();
    fireEvent.change(screen.getByTestId("class-label-input"), {
      target: { value: "Employee" },
    });

    fireEvent.click(screen.getByTestId("parent-class-trigger"));
    fireEvent.click(screen.getByText("Person"));

    fireEvent.click(screen.getByTestId("create-class-btn"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledTimes(2);
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_abc/edges",
        expect.objectContaining({ edge_type: "subclass_of" }),
      );
    });
  });

  it("displays error on API failure", async () => {
    const { ApiError } = jest.requireMock("@/lib/api-client");
    (api.post as jest.Mock).mockRejectedValueOnce(
      new ApiError(400, { code: "DUPLICATE", message: "Class already exists" }),
    );

    renderDialog();
    fireEvent.change(screen.getByTestId("class-label-input"), {
      target: { value: "Person" },
    });
    fireEvent.click(screen.getByTestId("create-class-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("class-error")).toHaveTextContent(
        "Class already exists",
      );
    });
  });

  it("closes when Cancel is clicked", () => {
    renderDialog();
    fireEvent.click(screen.getByText("Cancel"));
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when overlay is clicked", () => {
    renderDialog();
    fireEvent.click(screen.getByTestId("add-class-dialog-overlay"));
    expect(onClose).toHaveBeenCalled();
  });

  it("filters parent classes by search term", () => {
    renderDialog();
    fireEvent.click(screen.getByTestId("parent-class-trigger"));
    fireEvent.change(screen.getByTestId("parent-class-search"), {
      target: { value: "org" },
    });
    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(screen.queryByText("Person")).not.toBeInTheDocument();
  });
});
