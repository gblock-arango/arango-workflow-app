"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type PaginatedResponse } from "@/lib/api-client";

interface OntologyEntry {
  _key: string;
  name?: string;
  label?: string;
}

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (ontologyId: string) => void;
}

export default function CreateOntologyDialog({ open, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tier, setTier] = useState<"local" | "domain">("local");
  const [selectedImports, setSelectedImports] = useState<string[]>([]);
  const [availableOntologies, setAvailableOntologies] = useState<OntologyEntry[]>([]);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setDescription("");
    setTier("local");
    setSelectedImports([]);
    setError(null);

    api
      .get<PaginatedResponse<OntologyEntry>>("/api/v1/ontology/library?limit=100")
      .then((res) => setAvailableOntologies(res.data ?? []))
      .catch(() => setAvailableOntologies([]));
  }, [open]);

  const handleCreate = useCallback(async () => {
    if (!name.trim()) {
      setError("Name is required");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const result = await api.post<{
        ontology_id: string;
        warnings: string[];
      }>("/api/v1/ontology/create", {
        name: name.trim(),
        description: description.trim(),
        tier,
        imports: selectedImports,
      });
      if (result.warnings?.length) {
        console.warn("Create ontology warnings:", result.warnings);
      }
      onCreated(result.ontology_id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create ontology");
    } finally {
      setCreating(false);
    }
  }, [name, description, tier, selectedImports, onCreated, onClose]);

  const toggleImport = useCallback((key: string) => {
    setSelectedImports((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  }, []);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl w-[520px] max-h-[90vh] overflow-y-auto">
        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">Create New Ontology</h2>
          <p className="text-sm text-gray-500 mt-1">
            Create an empty ontology and optionally import existing ontologies into it.
          </p>
        </div>

        <div className="px-6 py-5 space-y-5">
          <div>
            <label htmlFor="ont-name" className="block text-sm font-medium text-gray-700 mb-1">
              Name <span className="text-red-500">*</span>
            </label>
            <input
              id="ont-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Financial Services Domain"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
              autoFocus
            />
          </div>

          <div>
            <label htmlFor="ont-desc" className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <textarea
              id="ont-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Optional description of this ontology"
              rows={2}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 resize-none"
            />
          </div>

          <div>
            <label htmlFor="ont-tier" className="block text-sm font-medium text-gray-700 mb-1">
              Tier
            </label>
            <select
              id="ont-tier"
              value={tier}
              onChange={(e) => setTier(e.target.value as "local" | "domain")}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            >
              <option value="local">Local (organization-specific)</option>
              <option value="domain">Domain (shared standard)</option>
            </select>
          </div>

          {availableOntologies.length > 0 && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Import Ontologies
              </label>
              <p className="text-xs text-gray-500 mb-2">
                Select existing ontologies to import. Imported classes and properties will be
                available as foundations for this ontology.
              </p>
              <div className="border border-gray-200 rounded-lg max-h-[200px] overflow-y-auto divide-y divide-gray-100">
                {availableOntologies.map((ont) => {
                  const displayName = ont.name || ont.label || ont._key;
                  const checked = selectedImports.includes(ont._key);
                  return (
                    <label
                      key={ont._key}
                      className={`flex items-center gap-3 px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors ${
                        checked ? "bg-indigo-50" : ""
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleImport(ont._key)}
                        className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="text-sm text-gray-700 truncate">{displayName}</span>
                    </label>
                  );
                })}
              </div>
              {selectedImports.length > 0 && (
                <p className="text-xs text-indigo-600 mt-1.5">
                  {selectedImports.length} ontolog{selectedImports.length === 1 ? "y" : "ies"} selected
                </p>
              )}
            </div>
          )}

          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end gap-3">
          <button
            type="button"
            onClick={onClose}
            disabled={creating}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !name.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {creating ? "Creating…" : "Create Ontology"}
          </button>
        </div>
      </div>
    </div>
  );
}
