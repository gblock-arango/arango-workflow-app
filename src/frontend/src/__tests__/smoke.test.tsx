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
            connection: {
              ui_variant: "connected",
              ui_message: "Local Minikube",
              active_profile_display_name: "Local Minikube",
            },
            probe: {
              status: "ok",
              details: {
                response_preview:
                  '{"license":"community","server":"arango","version":"3.12.4"}',
              },
            },
            registry: {
              status: "ok",
              cluster_name: "local-minikube-dev",
            },
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

  it("shows profile name when backend is healthy", async () => {
    stubHealthy();
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("Local Minikube")).toBeInTheDocument();
      expect(screen.getByText(/Arango 3\.12\.4 · local-minikube-dev/)).toBeInTheDocument();
    });
  });

  it("renders Connection link beside status widget", () => {
    stubHealthy();
    render(<Home />);
    expect(screen.getByRole("link", { name: "Connection" })).toHaveAttribute(
      "href",
      "/connection",
    );
  });

  it("shows Click to Connect when no profile is saved", async () => {
    mockFetch.mockImplementation((url: string) => {
      if (typeof url === "string" && url.endsWith("/ready")) {
        return Promise.resolve({
          ok: true,
          status: 200,
          json: () =>
            Promise.resolve({
              status: "not_ready",
              connection: {
                ui_variant: "unset",
                ui_message: "Click to Connect",
              },
            }),
        });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: () =>
          Promise.resolve({ data: [], total_count: 0, has_more: false, cursor: null }),
        headers: new Headers({ "content-type": "application/json" }),
      });
    });
    render(<Home />);
    await waitFor(() => {
      expect(screen.getByText("Click to Connect")).toBeInTheDocument();
    });
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
