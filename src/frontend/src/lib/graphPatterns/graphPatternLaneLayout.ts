/**
 * Shared grid for GraphPattern swim lanes so every column aligns across rows.
 * Severity is leftmost; patterns sort high → medium → low.
 */
export const GRAPH_PATTERN_LANE_GRID_CLASS =
  "grid w-full grid-cols-[minmax(64px,80px)_minmax(120px,1fr)_minmax(120px,1.2fr)_minmax(140px,1.4fr)_72px_minmax(220px,2.5fr)_minmax(100px,132px)_36px] gap-x-3 items-center";

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
