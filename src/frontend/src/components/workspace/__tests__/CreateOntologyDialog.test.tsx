import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import CreateOntologyDialog from "../CreateOntologyDialog";

jest.mock("@/lib/api-client", () => ({
  api: {
    get: jest.fn().mockResolvedValue({
      data: [
        { _key: "ont1", name: "Ontology One" },
        { _key: "ont2", name: "Ontology Two" },
      ],
      cursor: null,
      has_more: false,
      total_count: 2,
    }),
    post: jest.fn().mockResolvedValue({
      ontology_id: "new_ont",
      name: "My Ontology",
      imports_created: [],
      warnings: [],
    }),
  },
}));

jest.mock("@/lib/auth", () => ({
  getToken: jest.fn().mockReturnValue(null),
}));

describe("CreateOntologyDialog", () => {
  const mockClose = jest.fn();
  const mockCreated = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders nothing when closed", () => {
    const { container } = render(
      <CreateOntologyDialog open={false} onClose={mockClose} onCreated={mockCreated} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the dialog when open", async () => {
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );
    expect(screen.getByText("Create New Ontology")).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Financial Services/)).toBeInTheDocument();
  });

  it("disables create button when name is empty", () => {
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );
    const btn = screen.getByRole("button", { name: /Create Ontology/i });
    expect(btn).toBeDisabled();
  });

  it("enables create button after entering a name", () => {
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );
    const input = screen.getByPlaceholderText(/Financial Services/);
    fireEvent.change(input, { target: { value: "My Ontology" } });
    const btn = screen.getByRole("button", { name: /Create Ontology/i });
    expect(btn).not.toBeDisabled();
  });

  it("calls API and onCreated on submit", async () => {
    const { api } = require("@/lib/api-client");
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );
    const input = screen.getByPlaceholderText(/Financial Services/);
    fireEvent.change(input, { target: { value: "My Ontology" } });
    fireEvent.click(screen.getByRole("button", { name: /Create Ontology/i }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith("/api/v1/ontology/create", expect.objectContaining({
        name: "My Ontology",
      }));
    });

    await waitFor(() => {
      expect(mockCreated).toHaveBeenCalledWith("new_ont");
    });
  });

  it("shows available ontologies as import checkboxes", async () => {
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Ontology One")).toBeInTheDocument();
      expect(screen.getByText("Ontology Two")).toBeInTheDocument();
    });
  });

  it("calls onClose when Cancel is clicked", () => {
    render(
      <CreateOntologyDialog open={true} onClose={mockClose} onCreated={mockCreated} />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Cancel/i }));
    expect(mockClose).toHaveBeenCalledTimes(1);
  });
});
