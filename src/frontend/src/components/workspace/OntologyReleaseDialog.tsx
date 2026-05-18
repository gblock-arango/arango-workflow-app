"use client";

import { useState, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

export interface OntologyReleaseDialogProps {
  open: boolean;
  ontologyKey: string;
  /** Shown as context only (current release from registry, if any). */
  currentReleaseVersion?: string | null;
  onClose: () => void;
  /** Called after a successful release so the explorer can refetch. */
  onReleased?: (ontologyKey: string) => void;
}

/**
 * Record an ontology release (POST /api/v1/ontology/library/{id}/releases).
 */
export default function OntologyReleaseDialog({
  open,
  ontologyKey,
  currentReleaseVersion,
  onClose,
  onReleased,
}: OntologyReleaseDialogProps) {
  const [version, setVersion] = useState("");
  const [description, setDescription] = useState("");
  const [releaseNotes, setReleaseNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setVersion("");
      setDescription("");
      setReleaseNotes("");
      setError(null);
    }
  }, [open, ontologyKey]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const v = version.trim();
    if (!v) {
      setError("Release version is required");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await api.post(`/api/v1/ontology/library/${encodeURIComponent(ontologyKey)}/releases`, {
        version: v,
        description: description.trim(),
        release_notes: releaseNotes.trim(),
      });
      onReleased?.(ontologyKey);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error
            ? err.message
            : "Release failed",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/50"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-labelledby="ontology-release-title"
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-lg p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="ontology-release-title" className="text-lg font-semibold text-gray-900 mb-1">
          Release ontology
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Registry id: <code className="bg-gray-100 px-1 rounded">{ontologyKey}</code>
          {currentReleaseVersion ? (
            <>
              {" "}
              · Current release:{" "}
              <span className="font-medium text-gray-700">{currentReleaseVersion}</span>
            </>
          ) : null}
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="ont-release-version" className="block text-xs font-medium text-gray-600 mb-1">
              Release version <span className="text-red-500">*</span>
            </label>
            <input
              id="ont-release-version"
              type="text"
              value={version}
              onChange={(e) => setVersion(e.target.value)}
              placeholder="e.g. 1.0.0"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              autoComplete="off"
              disabled={submitting}
            />
          </div>
          <div>
            <label htmlFor="ont-release-desc" className="block text-xs font-medium text-gray-600 mb-1">
              Description
            </label>
            <textarea
              id="ont-release-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Short summary of this release"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-y min-h-[56px]"
              disabled={submitting}
            />
          </div>
          <div>
            <label htmlFor="ont-release-notes" className="block text-xs font-medium text-gray-600 mb-1">
              Release notes
            </label>
            <textarea
              id="ont-release-notes"
              value={releaseNotes}
              onChange={(e) => setReleaseNotes(e.target.value)}
              rows={5}
              placeholder="Changelog, migration notes, etc."
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-y min-h-[100px]"
              disabled={submitting}
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-3 py-1.5 text-sm bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-50"
              disabled={submitting}
            >
              {submitting ? "Releasing…" : "Submit release"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
