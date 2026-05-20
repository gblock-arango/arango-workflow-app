import type { GraphPatternEdge, GraphPatternNode } from "@/types/graphPattern";

const COLLECTION_FILL: Record<string, string> = {
  accounts: "#3b82f6",
  transactions: "#8b5cf6",
  devices: "#06b6d4",
  ips: "#f59e0b",
  attack_patterns: "#ef4444",
  fraud_signals: "#22c55e",
};

const COLLECTION_SHAPE: Record<string, string> = {
  accounts: "box",
  transactions: "ellipse",
  devices: "box",
  ips: "diamond",
  attack_patterns: "hexagon",
  fraud_signals: "triangle",
};

function escapeDotLabel(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

/** Build a Graphviz DOT digraph for a miniature pattern preview. */
export function patternToDot(
  nodes: GraphPatternNode[],
  edges: GraphPatternEdge[],
): string {
  const lines: string[] = [
    "digraph GraphPattern {",
    '  graph [bgcolor="transparent" rankdir=LR splines=true nodesep=0.35 ranksep=0.45 pad=0.15];',
    '  node [fontname="Helvetica" fontsize=8 style="filled,bold" fontcolor=white margin="0.12,0.06"];',
    '  edge [fontname="Helvetica" fontsize=6 color="#94a3b8" arrowsize=0.6];',
  ];

  for (const node of nodes) {
    const fill = COLLECTION_FILL[node.collection] ?? "#64748b";
    const shape = COLLECTION_SHAPE[node.collection] ?? "ellipse";
    lines.push(
      `  "${escapeDotLabel(node.id)}" [label="${escapeDotLabel(node.label)}" shape=${shape} fillcolor="${fill}" color="#cbd5e1"];`,
    );
  }

  for (const edge of edges) {
    lines.push(
      `  "${escapeDotLabel(edge.from)}" -> "${escapeDotLabel(edge.to)}" [label="${escapeDotLabel(edge.predicate)}"];`,
    );
  }

  lines.push("}");
  return lines.join("\n");
}
