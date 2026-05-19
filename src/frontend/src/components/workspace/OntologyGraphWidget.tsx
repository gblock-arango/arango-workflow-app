"use client";

import type { ReactNode } from "react";
import { LENS_LABELS, type LensType } from "@/components/workspace/LensToolbar";
import type { GraphViewMode } from "@/types/workspace";

export interface OntologyGraphWidgetProps {
  widgetId?: string;
  ontologyName: string | null;
  ontologyId: string | null;
  activeLens: LensType;
  graphViewMode: GraphViewMode;
  pipelineRunId: string | null;
  children: ReactNode;
  footer?: ReactNode;
}

/** Chrome for the ontology graph canvas inside a workspace tab. */
export default function OntologyGraphWidget({
  widgetId = "ontology-graph",
  ontologyName,
  ontologyId,
  activeLens,
  graphViewMode,
  pipelineRunId,
  children,
  footer,
}: OntologyGraphWidgetProps) {
  return (
    <div className="h-full flex flex-col min-h-0" data-widget={widgetId}>
      <div className="flex items-center gap-2 px-3 py-1.5 border-b border-gray-200 bg-white flex-shrink-0">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-indigo-600">
          Graph
        </span>
        {pipelineRunId ? (
          <span className="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-800 font-medium">
            Pipeline
          </span>
        ) : ontologyId ? (
          <>
            <span className="text-xs text-gray-800 truncate max-w-[200px]">
              {ontologyName ?? ontologyId}
            </span>
            <span className="text-[10px] text-gray-500">
              {LENS_LABELS[activeLens]} · {graphViewMode === "box-arrow" ? "Box" : "Network"}
            </span>
          </>
        ) : (
          <span className="text-xs text-gray-500">No ontology selected</span>
        )}
      </div>
      <div className="flex-1 relative overflow-hidden min-h-0">{children}</div>
      {footer}
    </div>
  );
}
