import { test, expect } from "@playwright/test";

const MOCK_STAGING_GRAPH = {
  run_id: "run_e2e_001",
  classes: [
    {
      _key: "cls_001",
      uri: "http://example.org/ontology#Person",
      label: "Person",
      description: "A human being.",
      rdf_type: "owl:Class",
      confidence: 0.9,
      status: "pending",
      ontology_id: "onto_e2e",
      created: "2026-03-10T10:00:00Z",
      expired: null,
    },
    {
      _key: "cls_002",
      uri: "http://example.org/ontology#Organization",
      label: "Organization",
      description: "A structured group of people.",
      rdf_type: "owl:Class",
      confidence: 0.6,
      status: "pending",
      ontology_id: "onto_e2e",
      created: "2026-03-10T10:00:00Z",
      expired: null,
    },
  ],
  properties: [],
  edges: [
    {
      _key: "edge_001",
      _from: "ontology_classes/cls_001",
      _to: "ontology_classes/cls_002",
      type: "related_to",
      label: "works for",
    },
  ],
};

test.describe("Curation Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.route("**/api/v1/ontology/staging/run_e2e_001", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_STAGING_GRAPH),
      }),
    );

    await page.route("**/api/v1/curation/decide", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ status: "ok" }),
      }),
    );

    await page.route("**/api/v1/ontology/*/timeline", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ data: [] }),
      }),
    );
  });

  test("loads staging graph and displays nodes", async ({ page }) => {
    await page.goto("/curation/run_e2e_001");
    await expect(page.getByTestId("graph-canvas")).toBeVisible();
    await expect(page.getByTestId("graph-node-cls_001")).toBeVisible();
    await expect(page.getByTestId("graph-node-cls_002")).toBeVisible();
  });

  test("select node shows detail panel", async ({ page }) => {
    await page.goto("/curation/run_e2e_001");
    await expect(page.getByTestId("graph-canvas")).toBeVisible();

    await page.getByTestId("graph-node-cls_001").click();

    await expect(page.getByTestId("node-detail")).toBeVisible();
    await expect(page.getByText("Person")).toBeVisible();
    await expect(page.getByTestId("node-actions")).toBeVisible();
  });

  test("approve class via action button", async ({ page }) => {
    await page.goto("/curation/run_e2e_001");
    await expect(page.getByTestId("graph-canvas")).toBeVisible();

    await page.getByTestId("graph-node-cls_001").click();
    await expect(page.getByTestId("approve-btn")).toBeVisible();
    await page.getByTestId("approve-btn").click();

    await expect(page.getByTestId("node-status-badge")).toHaveText("Approved");
  });

  test("shows empty state message when selecting nothing", async ({
    page,
  }) => {
    await page.goto("/curation/run_e2e_001");
    await expect(page.getByTestId("graph-canvas")).toBeVisible();
    await expect(
      page.getByText("Select a node or edge to view details"),
    ).toBeVisible();
  });
});
