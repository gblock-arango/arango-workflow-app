import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import BatchActions from "@/components/curation/BatchActions";

function mockFetchSuccess() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ status: "ok" }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("BatchActions", () => {
  it("does not render when no items are selected", () => {
    mockFetchSuccess();
    const { container } = render(
      <BatchActions
        selectedKeys={[]}
        entityType="class"
        runId="run_abc"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders with correct count when items are selected", () => {
    mockFetchSuccess();
    render(
      <BatchActions
        selectedKeys={["cls_001", "cls_002", "cls_003"]}
        entityType="class"
        runId="run_abc"
      />,
    );

    expect(screen.getByTestId("batch-count")).toHaveTextContent("3");
    expect(screen.getByText(/items selected/)).toBeInTheDocument();
  });

  it("calls onBatchDecision on Approve All", async () => {
    mockFetchSuccess();
    const onBatch = jest.fn();
    render(
      <BatchActions
        selectedKeys={["cls_001", "cls_002"]}
        entityType="class"
        runId="run_abc"
        onBatchDecision={onBatch}
      />,
    );

    fireEvent.click(screen.getByTestId("batch-approve-btn"));
    expect(onBatch).toHaveBeenCalledWith(
      ["cls_001", "cls_002"],
      "approve",
    );

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1);
    });
  });

  it("calls onBatchDecision on Reject All", async () => {
    mockFetchSuccess();
    const onBatch = jest.fn();
    render(
      <BatchActions
        selectedKeys={["cls_001"]}
        entityType="class"
        runId="run_abc"
        onBatchDecision={onBatch}
      />,
    );

    fireEvent.click(screen.getByTestId("batch-reject-btn"));
    expect(onBatch).toHaveBeenCalledWith(["cls_001"], "reject");
  });

  it("calls onClearSelection when Clear is clicked", () => {
    mockFetchSuccess();
    const onClear = jest.fn();
    render(
      <BatchActions
        selectedKeys={["cls_001"]}
        entityType="class"
        runId="run_abc"
        onClearSelection={onClear}
      />,
    );

    fireEvent.click(screen.getByTestId("batch-clear-btn"));
    expect(onClear).toHaveBeenCalled();
  });

  it("shows singular item text for single selection", () => {
    mockFetchSuccess();
    render(
      <BatchActions
        selectedKeys={["cls_001"]}
        entityType="class"
        runId="run_abc"
      />,
    );

    expect(screen.getByText(/item selected/)).toBeInTheDocument();
  });
});
