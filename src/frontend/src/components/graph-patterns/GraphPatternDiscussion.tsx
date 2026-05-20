import type { GraphPattern } from "@/types/graphPattern";

function formatLastSeen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

interface GraphPatternDiscussionProps {
  pattern: GraphPattern;
}

/** Pattern name, narrative, and graphlet metadata for the swim-lane discussion slot. */
export default function GraphPatternDiscussion({ pattern }: GraphPatternDiscussionProps) {
  const collections = [...new Set(pattern.nodes.map((n) => n.collection))].join(", ");
  const predicates = [...new Set(pattern.edges.map((e) => e.predicate))].join(", ");

  return (
    <div className="min-w-0 py-0.5">
      <p className="text-sm font-semibold text-gray-900 leading-snug" title={pattern.name}>
        {pattern.name}
      </p>
      <p
        className="mt-1 text-xs text-gray-600 leading-relaxed line-clamp-3"
        title={pattern.description}
      >
        {pattern.description}
      </p>
      <p className="mt-1.5 text-[10px] text-gray-400 leading-snug">
        <span className="font-medium text-gray-500">{pattern.threatType}</span>
        {" · "}
        {pattern.nodes.length} nodes, {pattern.edges.length} edges
        {" · "}
        collections: {collections}
      </p>
      <p className="mt-0.5 text-[10px] text-gray-400 truncate" title={predicates}>
        Predicates: {predicates}
        {" · "}
        Last seen {formatLastSeen(pattern.features.lastSeen)}
        {pattern.persisted ? " · Saved" : ""}
      </p>
    </div>
  );
}
