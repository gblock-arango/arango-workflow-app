"use client";

import { useState, useCallback } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { OntologyClass, PromotionResult } from "@/types/curation";

interface PromotePanelProps {
  runId: string;
  classes: OntologyClass[];
  onPromoted?: (result: PromotionResult) => void;
}

export default function PromotePanel({
  runId,
  classes,
  onPromoted,
}: PromotePanelProps) {
  const [confirming, setConfirming] = useState(false);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PromotionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const approved = classes.filter((c) => c.status === "approved").length;
  const rejected = classes.filter((c) => c.status === "rejected").length;
  const pending = classes.filter((c) => c.status === "pending").length;

  const handlePromote = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.post<PromotionResult>(
        `/api/v1/curation/promote/${runId}`,
      );
      setResult(res);
      onPromoted?.(res);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Promotion failed. Please try again.",
      );
    } finally {
      setLoading(false);
      setConfirming(false);
    }
  }, [runId, onPromoted]);

  return (
    <div className="space-y-4" data-testid="promote-panel">
      <h3 className="text-sm font-semibold text-gray-800">
        Promote to Production
      </h3>

      {/* Summary */}
      <div className="grid grid-cols-3 gap-3" data-testid="promote-summary">
        <div className="bg-green-50 rounded-lg p-3 text-center border border-green-100">
          <div className="text-2xl font-bold text-green-700">{approved}</div>
          <div className="text-xs text-green-600">Approved</div>
        </div>
        <div className="bg-red-50 rounded-lg p-3 text-center border border-red-100">
          <div className="text-2xl font-bold text-red-700">{rejected}</div>
          <div className="text-xs text-red-600">Rejected</div>
        </div>
        <div className="bg-gray-50 rounded-lg p-3 text-center border border-gray-100">
          <div className="text-2xl font-bold text-gray-700">{pending}</div>
          <div className="text-xs text-gray-500">Pending</div>
        </div>
      </div>

      {pending > 0 && (
        <p className="text-xs text-yellow-700 bg-yellow-50 px-3 py-2 rounded-lg border border-yellow-100">
          {pending} item{pending !== 1 ? "s" : ""} still pending review.
          Only approved items will be promoted.
        </p>
      )}

      {/* Actions */}
      {!result && (
        <>
          {!confirming ? (
            <button
              onClick={() => setConfirming(true)}
              disabled={approved === 0}
              className="w-full text-sm px-4 py-2.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium"
              data-testid="promote-btn"
            >
              Promote {approved} Approved Item{approved !== 1 ? "s" : ""} to
              Production
            </button>
          ) : (
            <div className="space-y-2">
              <p className="text-sm text-gray-700 bg-yellow-50 border border-yellow-200 rounded-lg px-3 py-2">
                This will promote <strong>{approved}</strong> approved
                entities to the production ontology. This action creates new
                temporal versions and cannot be easily undone.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={handlePromote}
                  disabled={loading}
                  className="flex-1 text-sm px-4 py-2 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50 transition-colors font-medium"
                  data-testid="confirm-promote-btn"
                >
                  {loading ? "Promoting..." : "Confirm Promotion"}
                </button>
                <button
                  onClick={() => setConfirming(false)}
                  disabled={loading}
                  className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  data-testid="cancel-promote-btn"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Result */}
      {result && (
        <div
          className="bg-green-50 border border-green-200 rounded-lg p-4 space-y-2"
          data-testid="promote-result"
        >
          <h4 className="text-sm font-semibold text-green-800">
            Promotion Complete
          </h4>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-lg font-bold text-green-700">
                {result.promoted_classes}
              </div>
              <div className="text-green-600">Classes</div>
            </div>
            <div>
              <div className="text-lg font-bold text-green-700">
                {result.promoted_properties}
              </div>
              <div className="text-green-600">Properties</div>
            </div>
            <div>
              <div className="text-lg font-bold text-green-700">
                {result.promoted_edges}
              </div>
              <div className="text-green-600">Edges</div>
            </div>
          </div>
          {result.errors.length > 0 && (
            <div className="mt-2">
              <p className="text-xs text-red-600 font-medium mb-1">
                {result.errors.length} error{result.errors.length !== 1 ? "s" : ""}:
              </p>
              <ul className="text-xs text-red-600 list-disc pl-4 space-y-0.5">
                {result.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {error && (
        <p className="text-xs text-red-600 bg-red-50 px-3 py-2 rounded-lg" data-testid="promote-error">
          {error}
        </p>
      )}
    </div>
  );
}
