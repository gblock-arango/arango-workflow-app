"use client";

import { useEffect, useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { StagingVsProductionDiff, DiffEntry } from "@/types/curation";

type DiffMode = "overlay" | "split";

interface DiffViewProps {
  runId: string;
  ontologyId: string;
  onClose?: () => void;
}

function changeIcon(type: "added" | "removed" | "changed"): string {
  if (type === "added") return "+";
  if (type === "removed") return "\u2212";
  return "\u0394";
}

function changeColor(type: "added" | "removed" | "changed"): string {
  if (type === "added") return "bg-green-50 border-green-200 text-green-800";
  if (type === "removed") return "bg-red-50 border-red-200 text-red-800";
  return "bg-yellow-50 border-yellow-200 text-yellow-800";
}

function changeBadge(type: "added" | "removed" | "changed"): string {
  if (type === "added") return "bg-green-100 text-green-700";
  if (type === "removed") return "bg-red-100 text-red-700";
  return "bg-yellow-100 text-yellow-700";
}

function DiffEntryRow({ entry }: { entry: DiffEntry }) {
  return (
    <div
      className={`flex items-center gap-3 px-3 py-2 rounded-lg border ${changeColor(entry.change_type)}`}
      data-testid={`diff-entry-${entry.entity_key}`}
    >
      <span className="text-sm font-mono font-bold w-5 text-center">
        {changeIcon(entry.change_type)}
      </span>
      <div className="flex-1 min-w-0">
        <span className="text-sm font-medium truncate block">{entry.label}</span>
        <span className="text-xs opacity-70">{entry.entity_type}</span>
      </div>
      <span
        className={`text-xs px-2 py-0.5 rounded-full font-medium ${changeBadge(entry.change_type)}`}
      >
        {entry.change_type === "added"
          ? "NEW"
          : entry.change_type === "removed"
            ? "REMOVED"
            : "CHANGED"}
      </span>
      {entry.fields_changed && entry.fields_changed.length > 0 && (
        <span className="text-xs text-gray-500">
          {entry.fields_changed.join(", ")}
        </span>
      )}
    </div>
  );
}

export default function DiffView({ runId, ontologyId, onClose }: DiffViewProps) {
  const [diff, setDiff] = useState<StagingVsProductionDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<DiffMode>("overlay");

  const fetchDiff = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<StagingVsProductionDiff>(
        `/api/v1/curation/diff/${runId}?ontology_id=${ontologyId}`,
      );
      setDiff(res);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.body.message : "Failed to load diff",
      );
    } finally {
      setLoading(false);
    }
  }, [runId, ontologyId]);

  useEffect(() => {
    fetchDiff();
  }, [fetchDiff]);

  const totalChanges =
    (diff?.added.length ?? 0) +
    (diff?.removed.length ?? 0) +
    (diff?.changed.length ?? 0);

  return (
    <div className="space-y-4" data-testid="diff-view">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-800">
          Staging vs Production
        </h3>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            <button
              onClick={() => setMode("overlay")}
              className={`text-xs px-3 py-1 ${mode === "overlay" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"}`}
              data-testid="diff-mode-overlay"
            >
              Overlay
            </button>
            <button
              onClick={() => setMode("split")}
              className={`text-xs px-3 py-1 border-l border-gray-200 ${mode === "split" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"}`}
              data-testid="diff-mode-split"
            >
              Split
            </button>
          </div>
          {onClose && (
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-600 text-lg leading-none"
              aria-label="Close diff"
            >
              &times;
            </button>
          )}
        </div>
      </div>

      {loading && (
        <div className="py-6 text-center text-sm text-gray-400 animate-pulse" data-testid="diff-loading">
          Computing differences...
        </div>
      )}

      {error && (
        <div className="py-3 px-3 text-sm text-red-600 bg-red-50 rounded-lg" data-testid="diff-error">
          {error}
        </div>
      )}

      {!loading && !error && diff && (
        <>
          {/* Summary */}
          <div className="flex gap-4 text-xs" data-testid="diff-summary">
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              {diff.added.length} added
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
              {diff.removed.length} removed
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-2 rounded-full bg-yellow-500" />
              {diff.changed.length} changed
            </span>
          </div>

          {totalChanges === 0 && (
            <div className="py-6 text-center text-sm text-gray-400">
              No differences found. Staging matches production.
            </div>
          )}

          {mode === "overlay" ? (
            <div className="space-y-1.5 max-h-[500px] overflow-y-auto">
              {[...diff.added, ...diff.changed, ...diff.removed].map(
                (entry) => (
                  <DiffEntryRow key={entry.entity_key} entry={entry} />
                ),
              )}
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <h4 className="text-xs font-medium text-gray-500 mb-2">
                  Staging (New / Changed)
                </h4>
                <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
                  {[...diff.added, ...diff.changed].map((entry) => (
                    <DiffEntryRow key={entry.entity_key} entry={entry} />
                  ))}
                </div>
              </div>
              <div>
                <h4 className="text-xs font-medium text-gray-500 mb-2">
                  Production (Removed)
                </h4>
                <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
                  {diff.removed.map((entry) => (
                    <DiffEntryRow key={entry.entity_key} entry={entry} />
                  ))}
                  {diff.removed.length === 0 && (
                    <p className="text-xs text-gray-400 py-4 text-center">
                      No entities removed.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
