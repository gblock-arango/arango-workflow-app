import { patternToDot } from "@/lib/graphPatterns/patternToDot";

describe("patternToDot", () => {
  it("quotes comma-containing margin so Graphviz parses node defaults", () => {
    const dot = patternToDot(
      [{ id: "n1", label: "N1", collection: "accounts" }],
      [],
    );
    expect(dot).toContain('margin="0.12,0.06"');
    expect(dot).not.toMatch(/margin=0\.12,0\.06/);
  });
});
