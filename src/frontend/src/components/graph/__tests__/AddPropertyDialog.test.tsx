import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import AddPropertyDialog from "@/components/graph/AddPropertyDialog";
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

describe("AddPropertyDialog", () => {
  const onCreated = jest.fn();
  const onClose = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    (api.post as jest.Mock).mockResolvedValue({});
  });

  function renderDialog() {
    return render(
      <AddPropertyDialog
        ontologyId="onto_abc"
        domainClassKey="cls_001"
        domainClassLabel="Person"
        onCreated={onCreated}
        onClose={onClose}
      />,
    );
  }

  it("renders the dialog with domain class info", () => {
    renderDialog();
    expect(screen.getByRole("heading", { name: "Add Property" })).toBeInTheDocument();
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(screen.getByTestId("property-label-input")).toBeInTheDocument();
  });

  it("shows property type radio buttons", () => {
    renderDialog();
    expect(screen.getByLabelText("Datatype Property")).toBeChecked();
    expect(screen.getByLabelText("Object Property")).not.toBeChecked();
  });

  it("submits datatype property creation", async () => {
    renderDialog();
    fireEvent.change(screen.getByTestId("property-label-input"), {
      target: { value: "age" },
    });
    fireEvent.change(screen.getByTestId("property-range-select"), {
      target: { value: "xsd:integer" },
    });
    fireEvent.click(screen.getByTestId("add-property-btn"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_abc/properties",
        expect.objectContaining({
          label: "age",
          domain_class: "cls_001",
          range_type: "xsd:integer",
          property_type: "owl:DatatypeProperty",
        }),
      );
    });
    expect(onCreated).toHaveBeenCalled();
  });

  it("submits object property creation", async () => {
    renderDialog();
    fireEvent.click(screen.getByLabelText("Object Property"));
    fireEvent.change(screen.getByTestId("property-label-input"), {
      target: { value: "hasOwner" },
    });
    fireEvent.click(screen.getByTestId("add-property-btn"));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/ontology/onto_abc/properties",
        expect.objectContaining({
          property_type: "owl:ObjectProperty",
        }),
      );
    });
  });

  it("supports custom range type input", () => {
    renderDialog();
    fireEvent.click(screen.getByText("Use custom range type..."));
    expect(screen.getByTestId("property-range-custom")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Use standard range type..."));
    expect(screen.getByTestId("property-range-select")).toBeInTheDocument();
  });

  it("displays error on API failure", async () => {
    const { ApiError } = jest.requireMock("@/lib/api-client");
    (api.post as jest.Mock).mockRejectedValueOnce(
      new ApiError(400, { code: "INVALID", message: "Invalid property name" }),
    );

    renderDialog();
    fireEvent.change(screen.getByTestId("property-label-input"), {
      target: { value: "bad-prop" },
    });
    fireEvent.click(screen.getByTestId("add-property-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("property-error")).toHaveTextContent(
        "Invalid property name",
      );
    });
  });

  it("disables submit when label is empty", () => {
    renderDialog();
    expect(screen.getByTestId("add-property-btn")).toBeDisabled();
  });

  it("closes on overlay click", () => {
    renderDialog();
    fireEvent.click(screen.getByTestId("add-property-dialog-overlay"));
    expect(onClose).toHaveBeenCalled();
  });
});
