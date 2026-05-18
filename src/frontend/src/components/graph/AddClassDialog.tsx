"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

interface AddClassDialogProps {
  ontologyId: string;
  existingClasses: { _key: string; label: string }[];
  onCreated: () => void;
  onClose: () => void;
}

function labelToUri(label: string): string {
  return label
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-zA-Z0-9_.-]/g, "");
}

export default function AddClassDialog({
  ontologyId,
  existingClasses,
  onCreated,
  onClose,
}: AddClassDialogProps) {
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [uri, setUri] = useState("");
  const [uriManuallyEdited, setUriManuallyEdited] = useState(false);
  const [parentKey, setParentKey] = useState<string | null>(null);
  const [parentSearch, setParentSearch] = useState("");
  const [parentDropdownOpen, setParentDropdownOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const labelInputRef = useRef<HTMLInputElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    labelInputRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as HTMLElement)) {
        setParentDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const generatedUri = useMemo(() => labelToUri(label), [label]);
  const displayUri = uriManuallyEdited ? uri : generatedUri;

  const filteredClasses = useMemo(() => {
    if (!parentSearch.trim()) return existingClasses;
    const q = parentSearch.toLowerCase();
    return existingClasses.filter(
      (c) => c.label.toLowerCase().includes(q) || c._key.toLowerCase().includes(q),
    );
  }, [existingClasses, parentSearch]);

  const selectedParentLabel = useMemo(
    () => existingClasses.find((c) => c._key === parentKey)?.label ?? null,
    [existingClasses, parentKey],
  );

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmedLabel = label.trim();
      if (!trimmedLabel) return;

      setSubmitting(true);
      setError(null);

      try {
        await api.post(`/api/v1/ontology/${ontologyId}/classes`, {
          label: trimmedLabel,
          description: description.trim(),
          uri: displayUri || undefined,
        });

        if (parentKey) {
          await api.post(`/api/v1/ontology/${ontologyId}/edges`, {
            _from: `ontology_classes/${parentKey}`,
            _to: `ontology_classes/${trimmedLabel}`,
            edge_type: "subclass_of",
            label: "subclass of",
          });
        }

        onCreated();
        onClose();
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.body.message);
        } else {
          setError("An unexpected error occurred.");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [label, description, displayUri, parentKey, ontologyId, onCreated, onClose],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="add-class-dialog-overlay"
    >
      <div
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-md mx-4"
        role="dialog"
        aria-labelledby="add-class-title"
      >
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 id="add-class-title" className="text-lg font-semibold text-gray-900">
            Add Class
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Create a new ontology class
          </p>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Label */}
          <div>
            <label htmlFor="class-label" className="block text-sm font-medium text-gray-700 mb-1">
              Label <span className="text-red-500">*</span>
            </label>
            <input
              ref={labelInputRef}
              id="class-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Financial Transaction"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              required
              data-testid="class-label-input"
            />
          </div>

          {/* Description */}
          <div>
            <label htmlFor="class-desc" className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              id="class-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the class..."
              rows={3}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-y"
              data-testid="class-desc-input"
            />
          </div>

          {/* URI */}
          <div>
            <label htmlFor="class-uri" className="block text-sm font-medium text-gray-700 mb-1">
              URI
            </label>
            <input
              id="class-uri"
              type="text"
              value={displayUri}
              onChange={(e) => {
                setUri(e.target.value);
                setUriManuallyEdited(true);
              }}
              placeholder="Auto-generated from label"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              data-testid="class-uri-input"
            />
            {!uriManuallyEdited && label.trim() && (
              <p className="text-xs text-gray-400 mt-1">
                Auto-generated: <span className="font-mono">{generatedUri}</span>
              </p>
            )}
          </div>

          {/* Parent Class */}
          <div ref={dropdownRef}>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Parent Class
            </label>
            <div className="relative">
              <button
                type="button"
                onClick={() => setParentDropdownOpen((o) => !o)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm text-left flex items-center justify-between focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                data-testid="parent-class-trigger"
              >
                <span className={selectedParentLabel ? "text-gray-900" : "text-gray-400"}>
                  {selectedParentLabel ?? "None (root class)"}
                </span>
                <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              {parentDropdownOpen && (
                <div className="absolute z-10 mt-1 w-full bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-hidden">
                  <div className="p-2 border-b border-gray-100">
                    <input
                      type="text"
                      value={parentSearch}
                      onChange={(e) => setParentSearch(e.target.value)}
                      placeholder="Search classes..."
                      className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none"
                      autoFocus
                      data-testid="parent-class-search"
                    />
                  </div>
                  <div className="overflow-y-auto max-h-36">
                    <button
                      type="button"
                      onClick={() => {
                        setParentKey(null);
                        setParentDropdownOpen(false);
                        setParentSearch("");
                      }}
                      className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 ${
                        parentKey === null ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-600"
                      }`}
                    >
                      None (root class)
                    </button>
                    {filteredClasses.map((cls) => (
                      <button
                        key={cls._key}
                        type="button"
                        onClick={() => {
                          setParentKey(cls._key);
                          setParentDropdownOpen(false);
                          setParentSearch("");
                        }}
                        className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 ${
                          parentKey === cls._key ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-700"
                        }`}
                      >
                        {cls.label}
                        <span className="ml-1.5 text-xs text-gray-400 font-mono">{cls._key}</span>
                      </button>
                    ))}
                    {filteredClasses.length === 0 && (
                      <div className="px-3 py-2 text-sm text-gray-400">No matches</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Error */}
          {error && (
            <div
              className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700"
              data-testid="class-error"
            >
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-700 border border-gray-300 rounded-lg hover:bg-gray-50"
              disabled={submitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting || !label.trim()}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              data-testid="create-class-btn"
            >
              {submitting && (
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              Create
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
