import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import EditableLabel from "@/components/graph/EditableLabel";

describe("EditableLabel", () => {
  const onSave = jest.fn();

  beforeEach(() => {
    jest.clearAllMocks();
    onSave.mockResolvedValue(undefined);
  });

  function renderLabel(value = "Person") {
    return render(<EditableLabel value={value} onSave={onSave} />);
  }

  it("renders the label text", () => {
    renderLabel();
    expect(screen.getByTestId("editable-label")).toHaveTextContent("Person");
  });

  it("shows edit icon on hover (always present, visibility via CSS)", () => {
    renderLabel();
    const label = screen.getByTestId("editable-label");
    const svg = label.querySelector("svg");
    expect(svg).toBeInTheDocument();
  });

  it("enters edit mode on double-click", () => {
    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));
    expect(screen.getByTestId("editable-label-input")).toBeInTheDocument();
    expect(screen.getByTestId("editable-label-input")).toHaveValue("Person");
  });

  it("saves on Enter key", async () => {
    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));

    const input = screen.getByTestId("editable-label-input");
    fireEvent.change(input, { target: { value: "Human" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(onSave).toHaveBeenCalledWith("Human");
    });
  });

  it("cancels on Escape key", () => {
    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));

    const input = screen.getByTestId("editable-label-input");
    fireEvent.change(input, { target: { value: "Something" } });
    fireEvent.keyDown(input, { key: "Escape" });

    expect(screen.getByTestId("editable-label")).toHaveTextContent("Person");
  });

  it("does not save when value is unchanged", async () => {
    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));

    const input = screen.getByTestId("editable-label-input");
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("editable-label")).toBeInTheDocument();
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("does not save when value is empty", async () => {
    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));

    const input = screen.getByTestId("editable-label-input");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("editable-label")).toBeInTheDocument();
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it("shows error message on save failure", async () => {
    onSave.mockRejectedValueOnce(new Error("Network error"));

    renderLabel();
    fireEvent.doubleClick(screen.getByTestId("editable-label"));

    const input = screen.getByTestId("editable-label-input");
    fireEvent.change(input, { target: { value: "NewName" } });
    fireEvent.keyDown(input, { key: "Enter" });

    await waitFor(() => {
      expect(screen.getByTestId("editable-label-error")).toHaveTextContent(
        "Network error",
      );
    });
  });
});
