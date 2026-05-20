"use client";

import type { GraphPattern } from "@/types/graphPattern";
import GraphvizPatternMiniature from "@/components/graph-patterns/GraphvizPatternMiniature";
import { AdaptiveCdcBadge, SeverityBadge } from "@/components/graph-patterns/GraphPatternBadges";
import GraphPatternFeatures from "@/components/graph-patterns/GraphPatternFeatures";
import GraphPatternDiscussion from "@/components/graph-patterns/GraphPatternDiscussion";
import GraphPatternGenieButton from "@/components/graph-patterns/GraphPatternGenieButton";
import GraphPatternActionsMenu, {
  type GraphPatternMenuAction,
} from "@/components/graph-patterns/GraphPatternActionsMenu";
import { GraphPatternLaneSlot } from "@/components/graph-patterns/GraphPatternLaneSlot";
import { GRAPH_PATTERN_LANE_GRID_CLASS } from "@/lib/graphPatterns/graphPatternLaneLayout";

interface GraphPatternSwimLaneProps {
  pattern: GraphPattern;
  onAction: (action: GraphPatternMenuAction) => void;
  onChatWithGenie: (patternId: string) => void;
}

export default function GraphPatternSwimLane({
  pattern,
  onAction,
  onChatWithGenie,
}: GraphPatternSwimLaneProps) {
  return (
    <article
      className={`${GRAPH_PATTERN_LANE_GRID_CLASS} items-start rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm`}
      data-pattern-id={pattern.id}
    >
      <GraphPatternLaneSlot label="Severity" className="self-center">
        <SeverityBadge severity={pattern.severity} />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Graph" className="self-center">
        <GraphvizPatternMiniature
          nodes={pattern.nodes}
          edges={pattern.edges}
          className="h-[72px] w-full max-w-[168px]"
        />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Classification" className="self-center">
        <p className="truncate text-sm font-semibold text-gray-900" title={pattern.threatType}>
          {pattern.threatType}
        </p>
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Adaptive CDC" className="self-center">
        <AdaptiveCdcBadge
          online={pattern.adaptiveCdc.online}
          status={pattern.adaptiveCdc.status}
        />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Features" className="self-center items-stretch py-0.5">
        <GraphPatternFeatures features={pattern.features} variant="lane" />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Pattern" className="items-start">
        <GraphPatternDiscussion pattern={pattern} />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Genie" className="self-center">
        <GraphPatternGenieButton
          patternId={pattern.id}
          patternName={pattern.name}
          onClick={onChatWithGenie}
        />
      </GraphPatternLaneSlot>

      <GraphPatternLaneSlot label="Actions" className="self-center justify-end">
        <GraphPatternActionsMenu persisted={pattern.persisted} onAction={onAction} />
      </GraphPatternLaneSlot>
    </article>
  );
}
