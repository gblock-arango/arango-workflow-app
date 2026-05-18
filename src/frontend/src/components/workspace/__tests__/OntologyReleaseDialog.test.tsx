import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import OntologyReleaseDialog from "../OntologyReleaseDialog";

const post = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    post: (...args: unknown[]) => post(...args),
  },
  ApiError: class ApiError extends Error {
    body: { message: string };
    status: number;
    constructor(status: number, body: { message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

describe("OntologyReleaseDialog", () => {
  beforeEach(() => {
    post.mockReset();
    post.mockResolvedValue({ release: {} });
  });

  it("submits version, description, and release notes via POST", async () => {
    const onClose = jest.fn();
    const onReleased = jest.fn();
    render(
      <OntologyReleaseDialog
        open
        ontologyKey="onto_1"
        currentReleaseVersion="0.9.0"
        onClose={onClose}
        onReleased={onReleased}
      />,
    );

    expect(screen.getByText("0.9.0")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText(/Release version/i), {
      target: { value: " 1.0.0 " },
    });
    fireEvent.change(screen.getByLabelText(/^Description$/i), {
      target: { value: " GA " },
    });
    fireEvent.change(screen.getByLabelText(/Release notes/i), {
      target: { value: " First stable " },
    });
    fireEvent.click(screen.getByRole("button", { name: /Submit release/i }));

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/api/v1/ontology/library/onto_1/releases", {
        version: "1.0.0",
        description: "GA",
        release_notes: "First stable",
      });
    });
    expect(onReleased).toHaveBeenCalledWith("onto_1");
    expect(onClose).toHaveBeenCalled();
  });

  it("blocks empty version", async () => {
    render(
      <OntologyReleaseDialog
        open
        ontologyKey="x"
        onClose={() => {}}
        onReleased={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Submit release/i }));

    await waitFor(() => {
      expect(screen.getByText("Release version is required")).toBeInTheDocument();
    });
    expect(post).not.toHaveBeenCalled();
  });

  it("Cancel closes without POST", () => {
    const onClose = jest.fn();
    render(<OntologyReleaseDialog open ontologyKey="o1" onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalled();
    expect(post).not.toHaveBeenCalled();
  });
});
