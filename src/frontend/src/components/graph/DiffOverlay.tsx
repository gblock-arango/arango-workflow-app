"use client";

import { useMemo } from "react";
import type { TemporalDiff, TemporalDiffEntry } from "@/types/timeline";

interface DiffOverlayProps {
  diff: TemporalDiff | null;
  activeNodeKeys: Set<string>;
}

export interface NodeDiffStyle {
  border: string;
  background: string;
  glow: string;
  badge: string;
  badgeText: string;
}

const ADDED_STYLE: NodeDiffStyle = {
  border: "border-green-500",
  background: "bg-green-50",
  glow: "shadow-[0_0_12px_rgba(34,197,94,0.4)]",
  badge: "bg-green-100 text-green-700",
  badgeText: "NEW",
};

const REMOVED_STYLE: NodeDiffStyle = {
  border: "border-red-500 border-dashed",
  background: "bg-red-50 opacity-60",
  glow: "shadow-[0_0_12px_rgba(239,68,68,0.4)]",
  badge: "bg-red-100 text-red-700",
  badgeText: "REMOVED",
};

const CHANGED_STYLE: NodeDiffStyle = {
  border: "border-yellow-500",
  background: "bg-yellow-50",
  glow: "shadow-[0_0_12px_rgba(234,179,8,0.4)] animate-pulse",
  badge: "bg-yellow-100 text-yellow-700",
  badgeText: "CHANGED",
};

export function getNodeDiffStyle(
  nodeKey: string,
  diffMap: Map<string, "added" | "removed" | "changed">,
): NodeDiffStyle | null {
  const changeType = diffMap.get(nodeKey);
  if (!changeType) return null;
  if (changeType === "added") return ADDED_STYLE;
  if (changeType === "removed") return REMOVED_STYLE;
  return CHANGED_STYLE;
}

export function useDiffMap(diff: TemporalDiff | null): Map<string, "added" | "removed" | "changed"> {
  return useMemo(() => {
    const map = new Map<string, "added" | "removed" | "changed">();
    if (!diff) return map;

    for (const entry of diff.added) {
      map.set(entry.entity_key, "added");
    }
    for (const entry of diff.removed) {
      map.set(entry.entity_key, "removed");
    }
    for (const entry of diff.changed) {
      map.set(entry.entity_key, "changed");
    }
    return map;
  }, [diff]);
}

export default function DiffOverlay({
  diff,
  activeNodeKeys,
}: DiffOverlayProps) {
  const diffMap = useDiffMap(diff);

  if (!diff) return null;

  const allEntries: (TemporalDiffEntry & {
    changeType: "added" | "removed" | "changed";
  })[] = [
    ...diff.added.map((e) => ({ ...e, changeType: "added" as const })),
    ...diff.removed.map((e) => ({ ...e, changeType: "removed" as const })),
    ...diff.changed.map((e) => ({ ...e, changeType: "changed" as const })),
  ].filter((e) => activeNodeKeys.has(e.entity_key));

  if (allEntries.length === 0) return null;

  return (
    <div
      className="absolute top-3 right-3 z-10 bg-white/90 backdrop-blur-sm border border-gray-200 rounded-lg p-3 shadow-sm max-w-[200px]"
      data-testid="diff-overlay"
    >
      <h4 className="text-xs font-semibold text-gray-600 mb-2 uppercase tracking-wide">
        Temporal Diff
      </h4>
      <div className="text-xs text-gray-500 mb-2">
        {diff.t1.slice(0, 10)} &rarr; {diff.t2.slice(0, 10)}
      </div>
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
          <span className="text-xs text-gray-600">
            {diff.added.length} added
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
          <span className="text-xs text-gray-600">
            {diff.removed.length} removed
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
          <span className="text-xs text-gray-600">
            {diff.changed.length} changed
          </span>
        </div>
      </div>
    </div>
  );
}
