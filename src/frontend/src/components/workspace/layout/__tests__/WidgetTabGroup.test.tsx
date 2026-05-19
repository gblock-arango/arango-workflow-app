import { render, screen } from "@testing-library/react";
import WidgetTabGroup from "../WidgetTabGroup";

describe("WidgetTabGroup", () => {
  it("renders tabs and switches active panel", async () => {
    render(
      <WidgetTabGroup
        tabs={[
          { id: "graph", label: "Ontology Graph", content: <div>Graph body</div> },
          { id: "other", label: "Other", content: <div>Other body</div> },
        ]}
        defaultTabId="graph"
      />,
    );

    expect(screen.getByRole("tab", { name: /Ontology Graph/i })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Graph body")).toBeInTheDocument();

    await screen.getByRole("tab", { name: "Other" }).click();
    expect(screen.getByText("Other body")).toBeInTheDocument();
  });
});
