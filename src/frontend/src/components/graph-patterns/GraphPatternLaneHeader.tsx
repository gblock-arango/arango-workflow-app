import {
  GRAPH_PATTERN_LANE_GRID_CLASS,
  GRAPH_PATTERN_LANE_SLOT_LABELS,
} from "@/lib/graphPatterns/graphPatternLaneLayout";

/** Column headers aligned to the same grid slots as swim lanes. */
export default function GraphPatternLaneHeader() {
  return (
    <div
      className={`${GRAPH_PATTERN_LANE_GRID_CLASS} px-4 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400`}
      aria-hidden
    >
      {GRAPH_PATTERN_LANE_SLOT_LABELS.map((label) => (
        <span key={label} className="truncate">
          {label}
        </span>
      ))}
    </div>
  );
}
