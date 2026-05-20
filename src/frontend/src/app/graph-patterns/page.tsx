"use client";

import { useCallback, useMemo, useState } from "react";
import AppHeader from "@/components/layout/AppHeader";
import GraphPatternLaneHeader from "@/components/graph-patterns/GraphPatternLaneHeader";
import GraphPatternSwimLane from "@/components/graph-patterns/GraphPatternSwimLane";
import type { GraphPatternMenuAction } from "@/components/graph-patterns/GraphPatternActionsMenu";
import { DUMMY_GRAPH_PATTERNS } from "@/lib/graphPatterns/dummyFraudPatterns";
import { sortGraphPatternsBySeverity } from "@/lib/graphPatterns/sortGraphPatternsBySeverity";
import type { GraphPattern } from "@/types/graphPattern";

type Toast = { id: number; message: string; tone: "info" | "success" | "error" };

export default function GraphPatternsPage() {
  const [patterns, setPatterns] = useState<GraphPattern[]>(() =>
    sortGraphPatternsBySeverity(DUMMY_GRAPH_PATTERNS),
  );
  const [toasts, setToasts] = useState<Toast[]>([]);

  const sortedPatterns = useMemo(
    () => sortGraphPatternsBySeverity(patterns),
    [patterns],
  );

  const pushToast = useCallback((message: string, tone: Toast["tone"] = "info") => {
    const id = Date.now();
    setToasts((prev) => [...prev, { id, message, tone }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }, []);

  const handlePatternAction = useCallback(
    (patternId: string, action: GraphPatternMenuAction) => {
      const pattern = patterns.find((p) => p.id === patternId);
      if (!pattern) return;

      if (action === "save") {
        setPatterns((prev) =>
          prev.map((p) => (p.id === patternId ? { ...p, persisted: true } : p)),
        );
        pushToast(`Saved GraphPattern “${pattern.name}”.`, "success");
        return;
      }

      if (action === "delete") {
        setPatterns((prev) => prev.filter((p) => p.id !== patternId));
        pushToast(`Deleted GraphPattern “${pattern.name}”.`, "info");
        return;
      }

      if (action === "apply") {
        const job = pattern.adaptiveCdc.jobName ?? "adaptive_cdc_apply";
        pushToast(
          `Queued Databricks job “${job}” for pattern “${pattern.name}” (demo).`,
          "success",
        );
      }
    },
    [patterns, pushToast],
  );

  const handleChatWithGenie = useCallback(
    (patternId: string) => {
      const pattern = patterns.find((p) => p.id === patternId);
      if (!pattern) return;
      pushToast(
        `Genie chat for “${pattern.name}” will open here in a future workflow.`,
        "info",
      );
    },
    [patterns, pushToast],
  );

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title="Graph Patterns"
        subtitle="Observed graphlets from the knowledge graph and Medallion Gold CDC (nodes + edges)"
      />

      <div className="max-w-[1600px] mx-auto px-6 py-8">
        <p className="mb-6 text-sm text-gray-600 max-w-3xl">
          Each swim lane is a <strong className="font-medium text-gray-800">GraphPattern</strong>:
          a recurring subgraph witnessed in ArangoDB and/or Databricks Gold tables. Use the menu to
          save, delete, or apply a pattern to Adaptive CDC (spawns a Databricks job).
        </p>

        {patterns.length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 bg-white p-12 text-center text-gray-500">
            No GraphPatterns yet. Import the fraud cyber dataset and run pattern discovery, or
            restore the demo patterns.
          </div>
        ) : (
          <div aria-label="Graph pattern swim lanes">
            <GraphPatternLaneHeader />
            <ul className="mt-2 flex flex-col gap-3">
              {sortedPatterns.map((pattern) => (
                <li key={pattern.id}>
                  <GraphPatternSwimLane
                    pattern={pattern}
                    onAction={(action) => handlePatternAction(pattern.id, action)}
                    onChatWithGenie={handleChatWithGenie}
                  />
                </li>
              ))}
            </ul>
          </div>
        )}

        {patterns.length === 0 ? (
          <button
            type="button"
            className="mt-4 text-sm font-medium text-indigo-600 hover:text-indigo-800"
            onClick={() => setPatterns(sortGraphPatternsBySeverity(DUMMY_GRAPH_PATTERNS))}
          >
            Reload demo patterns
          </button>
        ) : null}
      </div>

      <div
        className="fixed bottom-6 right-6 z-30 flex flex-col gap-2 max-w-sm"
        aria-live="polite"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={`rounded-lg border px-4 py-3 text-sm shadow-lg ${
              toast.tone === "success"
                ? "border-emerald-200 bg-emerald-50 text-emerald-900"
                : toast.tone === "error"
                  ? "border-red-200 bg-red-50 text-red-900"
                  : "border-gray-200 bg-white text-gray-800"
            }`}
          >
            {toast.message}
          </div>
        ))}
      </div>
    </main>
  );
}
