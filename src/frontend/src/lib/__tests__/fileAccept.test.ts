import { isOntologyImportFilename } from "@/lib/fileAccept";

describe("isOntologyImportFilename", () => {
  it.each([
    "fraud_cyber_ontology_arango_annotated.jsonld",
    "bundle.json-ld",
    "graph.json",
    "schema.ttl",
    "onto.owl",
  ])("returns true for %s", (name) => {
    expect(isOntologyImportFilename(name)).toBe(true);
  });

  it.each(["report.pdf", "notes.md", "data.csv"])("returns false for %s", (name) => {
    expect(isOntologyImportFilename(name)).toBe(false);
  });
});
