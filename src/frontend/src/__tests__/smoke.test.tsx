import { render, screen, waitFor } from "@testing-library/react";
import Home from "@/app/page";

const mockFetch = jest.fn();

beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
  sessionStorage.clear();
});

function stubHealthy() {
  mockFetch.mockImplementation((url: string) => {
    if (typeof url === "string" && url.endsWith("/ready")) {
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({
            status: "ready",
            database: "Arango 3.12.4",
            gateway: "Gateway reachable",
          }),
      });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({ data: [], total_count: 3, has_more: false, cursor: null }),
      headers: new Headers({ "content-type": "application/json" }),
    });
  });
}

describe("Home page", () => {
  it("renders the application heading", () => {
    stubHealthy();
    render(<Home />);
    expect(
      screen.getByRole("heading", { name: /Arango Graph-Accelerated Agents/i }),
    ).toBeInTheDocument();
  });

  it("renders the tagline", () => {
    stubHealthy();
    render(<Home />);
    expect(
      screen.getByText(/RBAC-compliant graph knowledge/i),
    ).toBeInTheDocument();
  });

  it("displays ontology count from library endpoint", async () => {
    stubHealthy();
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("3")).toBeInTheDocument();
    });
  });

  it("calls library endpoint on mount", async () => {
    stubHealthy();
    render(<Home />);
    await waitFor(() => {
      const libraryCalls = mockFetch.mock.calls.filter(
        ([url]: [string]) =>
          typeof url === "string" && url.includes("/api/v1/ontology/library"),
      );
      expect(libraryCalls.length).toBeGreaterThanOrEqual(1);
    });
  });
});
