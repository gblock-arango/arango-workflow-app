import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import AssetExplorer from "../AssetExplorer";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
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

describe("AssetExplorer document context menu", () => {
  beforeEach(() => {
    get.mockReset();
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/documents") {
        return Promise.resolve({
          data: [
            {
              _key: "doc_1",
              filename: "aoe-test.pdf",
              status: "failed",
              chunk_count: 0,
            },
          ],
          cursor: null,
          has_more: false,
          total_count: 1,
        });
      }
      if (path === "/api/v1/ontology/library") {
        return Promise.resolve({
          data: [],
          cursor: null,
          has_more: false,
          total_count: 0,
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it("emits document context menu data when right-clicking a document row", async () => {
    const onContextMenu = jest.fn();

    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={onContextMenu}
      />,
    );

    const documentRow = await screen.findByText("aoe-test.pdf");
    fireEvent.contextMenu(documentRow);

    await waitFor(() => {
      expect(onContextMenu).toHaveBeenCalled();
    });
    expect(onContextMenu.mock.calls[0][1]).toBe("document");
    expect(onContextMenu.mock.calls[0][2]).toMatchObject({
      _key: "doc_1",
      filename: "aoe-test.pdf",
      status: "failed",
    });
  });
});
