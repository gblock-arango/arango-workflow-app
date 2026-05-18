import { test, expect } from "@playwright/test";

const MOCK_STAGING_GRAPH = {
  run_id: "run_timeline_001",
  classes: [
    {
      _key: "cls_t01",
      uri: "http://example.org/ontology#Vehicle",
      label: "Vehicle",
      description: "A transport mechanism.",
      rdf_type: "owl:Class",
      confidence: 0.85,
      status: "approved",
      ontology_id: "onto_timeline",
      created: "2026-03-01T10:00:00Z",
      expired: null,
    },
  ],
  properties: [],
  edges: [],
};

const MOCK_TIMELINE_EVENTS = {
  data: [
    {
      timestamp: "2026-03-01T10:00:00Z",
      event_type: "created",
      entity_key: "cls_t01",
      entity_label: "Vehicle",
      collection: "ontology_classes",
    },
    {
      timestamp: "2026-03-05T14:00:00Z",
      event_type: "edited",
      entity_key: "cls_t01",
      entity_label: "Vehicle",
      collection: "ontology_classes",
    },
    {
      timestamp: "2026-03-10T09:00:00Z",
      event_type: "approved",
      entity_key: "cls_t01",
      entity_label: "Vehicle",
      collection: "ontology_classes",
    },
  ],
};

const MOCK_SNAPSHOT = {
  ontology_id: "onto_timeline",
  timestamp: "2026-03-05T14:00:00Z",
  classes: [MOCK_STAGING_GRAPH.classes[0]],
  properties: [],
  edges: [],
};

test.describe("VCR Timeline", () => {
  test.beforeEach(async ({ page }) => {
    await page.route(
      "**/api/v1/ontology/staging/run_timeline_001",
      (route) =>
        route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(MOCK_STAGING_GRAPH),
        }),
    );

    await page.route("**/api/v1/ontology/*/timeline", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_TIMELINE_EVENTS),
      }),
    );

    await page.route("**/api/v1/ontology/*/snapshot*", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(MOCK_SNAPSHOT),
      }),
    );
  });

  test("opens VCR timeline on button click", async ({ page }) => {
    await page.goto("/curation/run_timeline_001");
    await expect(page.getByTestId("graph-canvas")).toBeVisible();

    await page.getByText("VCR Timeline").click();
    await expect(page.getByTestId("vcr-timeline")).toBeVisible();
  });

  test("timeline shows controls after loading", async ({ page }) => {
    await page.goto("/curation/run_timeline_001");
    await page.getByText("VCR Timeline").click();

    await expect(page.getByTestId("timeline-slider")).toBeVisible();
    await expect(page.getByTestId("timeline-play-pause")).toBeVisible();
    await expect(page.getByTestId("timeline-rewind")).toBeVisible();
    await expect(page.getByTestId("timeline-ff")).toBeVisible();
    await expect(page.getByTestId("timeline-speed")).toBeVisible();
  });

  test("slider changes current position", async ({ page }) => {
    await page.goto("/curation/run_timeline_001");
    await page.getByText("VCR Timeline").click();

    await expect(page.getByTestId("vcr-timeline")).toBeVisible();
    await expect(page.getByText("3 / 3")).toBeVisible();

    await page.getByTestId("timeline-slider").fill("0");
    await expect(page.getByText("1 / 3")).toBeVisible();
  });

  test("rewind button goes to previous event", async ({ page }) => {
    await page.goto("/curation/run_timeline_001");
    await page.getByText("VCR Timeline").click();

    await expect(page.getByTestId("vcr-timeline")).toBeVisible();
    await expect(page.getByText("3 / 3")).toBeVisible();

    await page.getByTestId("timeline-rewind").click();
    await expect(page.getByText("2 / 3")).toBeVisible();
  });

  test("speed button cycles through speeds", async ({ page }) => {
    await page.goto("/curation/run_timeline_001");
    await page.getByText("VCR Timeline").click();

    await expect(page.getByTestId("timeline-speed")).toBeVisible();
    await expect(page.getByTestId("timeline-speed")).toHaveText("1x");

    await page.getByTestId("timeline-speed").click();
    await expect(page.getByTestId("timeline-speed")).toHaveText("2x");
  });
});
