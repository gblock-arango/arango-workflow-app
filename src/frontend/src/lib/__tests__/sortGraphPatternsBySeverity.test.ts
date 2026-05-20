import { DUMMY_GRAPH_PATTERNS } from "@/lib/graphPatterns/dummyFraudPatterns";
import { sortGraphPatternsBySeverity } from "@/lib/graphPatterns/sortGraphPatternsBySeverity";

describe("sortGraphPatternsBySeverity", () => {
  it("orders high before medium before low", () => {
    const shuffled = [
      DUMMY_GRAPH_PATTERNS[2],
      DUMMY_GRAPH_PATTERNS[0],
      DUMMY_GRAPH_PATTERNS[1],
    ];
    const sorted = sortGraphPatternsBySeverity(shuffled);
    expect(sorted.map((p) => p.severity)).toEqual(["high", "medium", "low"]);
  });
});
