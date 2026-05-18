"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

interface AddPropertyDialogProps {
  ontologyId: string;
  domainClassKey: string;
  domainClassLabel: string;
  onCreated: () => void;
  onClose: () => void;
}

type PropertyKind = "datatype" | "object";

const RANGE_TYPE_OPTIONS = [
  { value: "xsd:string", label: "String (xsd:string)" },
  { value: "xsd:integer", label: "Integer (xsd:integer)" },
  { value: "xsd:boolean", label: "Boolean (xsd:boolean)" },
  { value: "xsd:decimal", label: "Decimal (xsd:decimal)" },
  { value: "xsd:dateTime", label: "DateTime (xsd:dateTime)" },
  { value: "xsd:anyURI", label: "URI (xsd:anyURI)" },
] as const;

export default function AddPropertyDialog({
  ontologyId,
  domainClassKey,
  domainClassLabel,
  onCreated,
  onClose,
}: AddPropertyDialogProps) {
  const [label, setLabel] = useState("");
  const [description, setDescription] = useState("");
  const [rangeType, setRangeType] = useState("xsd:string");
  const [customRange, setCustomRange] = useState("");
  const [useCustomRange, setUseCustomRange] = useState(false);
  const [propertyKind, setPropertyKind] = useState<PropertyKind>("datatype");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const labelInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    labelInputRef.current?.focus();
  }, []);

  const effectiveRange = useCustomRange ? customRange.trim() : rangeType;

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const trimmedLabel = label.trim();
      if (!trimmedLabel) return;

      setSubmitting(true);
      setError(null);

      try {
        await api.post(`/api/v1/ontology/${ontologyId}/properties`, {
          label: trimmedLabel,
          description: description.trim(),
          domain_class: domainClassKey,
          range_type: effectiveRange,
          property_type: propertyKind === "object" ? "owl:ObjectProperty" : "owl:DatatypeProperty",
        });

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
    [label, description, effectiveRange, propertyKind, domainClassKey, ontologyId, onCreated, onClose],
  );

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      data-testid="add-property-dialog-overlay"
    >
      <div
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-md mx-4"
        role="dialog"
        aria-labelledby="add-property-title"
      >
        <div className="px-6 py-4 border-b border-gray-100">
          <h2 id="add-property-title" className="text-lg font-semibold text-gray-900">
            Add Property
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Add a property to <span className="font-medium text-gray-700">{domainClassLabel}</span>
          </p>
        </div>

        <form onSubmit={handleSubmit} className="px-6 py-4 space-y-4">
          {/* Property Type */}
          <div>
            <span className="block text-sm font-medium text-gray-700 mb-2">Property Type</span>
            <div className="flex gap-4">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="property-kind"
                  value="datatype"
                  checked={propertyKind === "datatype"}
                  onChange={() => setPropertyKind("datatype")}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">Datatype Property</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="property-kind"
                  value="object"
                  checked={propertyKind === "object"}
                  onChange={() => setPropertyKind("object")}
                  className="text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-700">Object Property</span>
              </label>
            </div>
          </div>

          {/* Label */}
          <div>
            <label htmlFor="prop-label" className="block text-sm font-medium text-gray-700 mb-1">
              Label <span className="text-red-500">*</span>
            </label>
            <input
              ref={labelInputRef}
              id="prop-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={propertyKind === "object" ? "e.g. hasOwner" : "e.g. accountBalance"}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
              required
              data-testid="property-label-input"
            />
          </div>

          {/* Description */}
          <div>
            <label htmlFor="prop-desc" className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              id="prop-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe the property..."
              rows={2}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-y"
              data-testid="property-desc-input"
            />
          </div>

          {/* Range Type */}
          <div>
            <label htmlFor="prop-range" className="block text-sm font-medium text-gray-700 mb-1">
              Range Type
            </label>
            {!useCustomRange ? (
              <div className="space-y-2">
                <select
                  id="prop-range"
                  value={rangeType}
                  onChange={(e) => setRangeType(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none bg-white"
                  data-testid="property-range-select"
                >
                  {RANGE_TYPE_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={() => setUseCustomRange(true)}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  Use custom range type...
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <input
                  type="text"
                  value={customRange}
                  onChange={(e) => setCustomRange(e.target.value)}
                  placeholder="e.g. ex:Person or xsd:date"
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                  autoFocus
                  data-testid="property-range-custom"
                />
                <button
                  type="button"
                  onClick={() => {
                    setUseCustomRange(false);
                    setCustomRange("");
                  }}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  Use standard range type...
                </button>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div
              className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700"
              data-testid="property-error"
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
              disabled={submitting || !label.trim() || (useCustomRange && !customRange.trim())}
              className="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
              data-testid="add-property-btn"
            >
              {submitting && (
                <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              )}
              Add Property
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
