import type { OntologyEdge } from "@/types/curation";
import {
  buildSyntheticRdfsRangeClassEdges,
  documentKey,
  getEdgeType,
  RDFS_RANGE_CLASS_LABEL_FALLBACK,
} from "./graphCanvasEdges";

describe("graphCanvasEdges", () => {
  describe("getEdgeType", () => {
    it("prefers edge_type when present on API payload", () => {
      const edge = {
        _key: "e1",
        _from: "ontology_object_properties/p1",
        _to: "ontology_classes/B",
        type: "related_to",
        label: "",
      } as OntologyEdge;
      Object.assign(edge, { edge_type: "rdfs_range_class" });
      expect(getEdgeType(edge)).toBe("rdfs_range_class");
    });
  });

  describe("documentKey", () => {
    it("returns collection key segment", () => {
      expect(documentKey("ontology_classes/Customer")).toBe("Customer");
    });
  });

  describe("buildSyntheticRdfsRangeClassEdges", () => {
    const classKeys = new Set(["Person", "Account"]);

    it("WhenY_DomainAndRangeResolved_ShouldEmitLabeledClassToClassEdge", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/holds",
          _to: "ontology_classes/Person",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/holds",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "holds",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(edges, classKeys);
      expect(syn).toEqual([
        {
          edgeKey: "r1",
          sourceClassKey: "Person",
          targetClassKey: "Account",
          label: "holds",
        },
      ]);
    });

    it("WhenY_NoMatchingRdfsDomain_ShouldEmitNothing", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "r1",
          _from: "ontology_object_properties/orphan",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "x",
        },
      ];
      expect(buildSyntheticRdfsRangeClassEdges(edges, classKeys)).toEqual([]);
    });

    it("WhenY_EmptyPropertyLabel_ShouldUseOwlObjectPropertyFallback", () => {
      const edges: OntologyEdge[] = [
        {
          _key: "d1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Person",
          type: "rdfs_domain",
          label: "",
        },
        {
          _key: "r1",
          _from: "ontology_object_properties/p",
          _to: "ontology_classes/Account",
          type: "rdfs_range_class",
          label: "",
        },
      ];
      const syn = buildSyntheticRdfsRangeClassEdges(edges, classKeys);
      expect(syn[0]?.label).toBe(RDFS_RANGE_CLASS_LABEL_FALLBACK);
    });
  });
});
