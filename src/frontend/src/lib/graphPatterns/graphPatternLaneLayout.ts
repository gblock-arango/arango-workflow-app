/**
 * Shared grid for GraphPattern swim lanes so every column aligns across rows.
 * Severity is leftmost; patterns sort high → medium → low.
 */
export const GRAPH_PATTERN_LANE_GRID_CLASS =
  "grid grid-cols-[80px_168px_152px_196px_72px_minmax(220px,1fr)_132px_36px] gap-x-3 items-center";

export const GRAPH_PATTERN_LANE_SLOT_LABELS = [
  "Severity",
  "Graph",
  "Classification",
  "Adaptive CDC",
  "Features",
  "Pattern",
  "Genie",
  "Actions",
] as const;
