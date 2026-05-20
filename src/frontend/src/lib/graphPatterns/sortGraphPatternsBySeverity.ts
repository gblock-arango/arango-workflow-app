import type { GraphPattern, GraphPatternSeverity } from "@/types/graphPattern";

const SEVERITY_RANK: Record<GraphPatternSeverity, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

/** High severity first, then medium, then low. */
export function sortGraphPatternsBySeverity(patterns: GraphPattern[]): GraphPattern[] {
  return [...patterns].sort(
    (a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity],
  );
}
