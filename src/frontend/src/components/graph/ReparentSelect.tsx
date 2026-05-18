"use client";

import { useState, useCallback, useMemo, useRef, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

interface ReparentSelectProps {
  ontologyId: string;
  classKey: string;
  currentParentKey?: string;
  availableClasses: { _key: string; label: string }[];
  onReparented: () => void;
}

export default function ReparentSelect({
  ontologyId,
  classKey,
  currentParentKey,
  availableClasses,
  onReparented,
}: ReparentSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as HTMLElement)) {
        setOpen(false);
        setSearch("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectableClasses = useMemo(() => {
    const filtered = availableClasses.filter((c) => c._key !== classKey);
    if (!search.trim()) return filtered;
    const q = search.toLowerCase();
    return filtered.filter(
      (c) => c.label.toLowerCase().includes(q) || c._key.toLowerCase().includes(q),
    );
  }, [availableClasses, classKey, search]);

  const currentParentLabel = useMemo(
    () => availableClasses.find((c) => c._key === currentParentKey)?.label ?? null,
    [availableClasses, currentParentKey],
  );

  const handleSelect = useCallback(
    async (newParentKey: string | null) => {
      if (newParentKey === currentParentKey) {
        setOpen(false);
        setSearch("");
        return;
      }

      setSubmitting(true);
      setError(null);

      try {
        await api.post(`/api/v1/ontology/${ontologyId}/edges`, {
          _from: `ontology_classes/${classKey}`,
          _to: newParentKey ? `ontology_classes/${newParentKey}` : undefined,
          edge_type: "subclass_of",
          label: "subclass of",
        });

        setOpen(false);
        setSearch("");
        onReparented();
      } catch (err) {
        if (err instanceof ApiError) {
          setError(err.body.message);
        } else {
          setError("Failed to change parent.");
        }
      } finally {
        setSubmitting(false);
      }
    },
    [ontologyId, classKey, currentParentKey, onReparented],
  );

  return (
    <div ref={containerRef} className="relative" data-testid="reparent-select">
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-gray-600">Parent:</span>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          disabled={submitting}
          className="text-xs px-2.5 py-1 border border-gray-300 rounded-md hover:bg-gray-50 text-gray-700 flex items-center gap-1.5 disabled:opacity-50"
          data-testid="reparent-trigger"
        >
          {submitting ? (
            <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          ) : (
            <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
            </svg>
          )}
          <span>{currentParentLabel ?? "None (root)"}</span>
          <svg className="w-3 h-3 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>

      {error && (
        <p className="text-xs text-red-600 mt-1" data-testid="reparent-error">{error}</p>
      )}

      {open && (
        <div className="absolute z-20 mt-1 left-0 w-64 bg-white border border-gray-200 rounded-lg shadow-lg max-h-56 overflow-hidden">
          <div className="p-2 border-b border-gray-100">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search classes..."
              className="w-full px-2 py-1.5 border border-gray-200 rounded text-sm focus:ring-1 focus:ring-blue-500 focus:border-blue-500 outline-none"
              autoFocus
              data-testid="reparent-search"
            />
          </div>
          <div className="overflow-y-auto max-h-44">
            <button
              type="button"
              onClick={() => handleSelect(null)}
              disabled={submitting}
              className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50 ${
                !currentParentKey ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-600"
              }`}
            >
              None (root class)
            </button>
            {selectableClasses.map((cls) => (
              <button
                key={cls._key}
                type="button"
                onClick={() => handleSelect(cls._key)}
                disabled={submitting}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 disabled:opacity-50 ${
                  currentParentKey === cls._key ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-700"
                }`}
              >
                {cls.label}
                <span className="ml-1.5 text-xs text-gray-400 font-mono">{cls._key}</span>
              </button>
            ))}
            {selectableClasses.length === 0 && (
              <div className="px-3 py-2 text-sm text-gray-400">No matching classes</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
