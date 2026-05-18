"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type PaginatedResponse } from "@/lib/api-client";

interface ImportEntry {
  edge_key: string;
  target_id: string;
  target_name: string;
  target_uri?: string;
  import_iri?: string;
  created: number;
}

interface OntologyEntry {
  _key: string;
  name?: string;
  label?: string;
}

interface Props {
  ontologyId: string;
  ontologyName: string;
  onClose: () => void;
  onChanged: () => void;
}

export default function ManageImportsOverlay({
  ontologyId,
  ontologyName,
  onClose,
  onChanged,
}: Props) {
  const [imports, setImports] = useState<ImportEntry[]>([]);
  const [available, setAvailable] = useState<OntologyEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAddPicker, setShowAddPicker] = useState(false);

  const fetchImports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<{ imports: ImportEntry[] }>(
        `/api/v1/ontology/${encodeURIComponent(ontologyId)}/imports`,
      );
      setImports(res.imports);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load imports");
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    void fetchImports();
    api
      .get<PaginatedResponse<OntologyEntry>>("/api/v1/ontology/library?limit=100")
      .then((res) => setAvailable(res.data ?? []))
      .catch(() => {});
  }, [fetchImports]);

  const addImport = useCallback(
    async (targetKey: string) => {
      setAdding(true);
      setError(null);
      try {
        await api.post(`/api/v1/ontology/${encodeURIComponent(ontologyId)}/imports`, {
          target_ontology_id: targetKey,
        });
        await fetchImports();
        onChanged();
        setShowAddPicker(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to add import");
      } finally {
        setAdding(false);
      }
    },
    [ontologyId, fetchImports, onChanged],
  );

  const removeImport = useCallback(
    async (targetId: string) => {
      setRemoving(targetId);
      setError(null);
      try {
        await api.del(
          `/api/v1/ontology/${encodeURIComponent(ontologyId)}/imports/${encodeURIComponent(targetId)}`,
        );
        await fetchImports();
        onChanged();
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to remove import");
      } finally {
        setRemoving(null);
      }
    },
    [ontologyId, fetchImports, onChanged],
  );

  const importedIds = new Set(imports.map((i) => i.target_id));
  const addableOntologies = available.filter(
    (o) => o._key !== ontologyId && !importedIds.has(o._key),
  );

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative bg-white rounded-2xl shadow-2xl w-[560px] max-h-[80vh] overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close"
        >
          ×
        </button>

        <div className="px-6 py-5 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-900">
            Manage Imports
          </h2>
          <p className="text-sm text-gray-500 mt-1">
            <span className="font-medium text-gray-700">{ontologyName}</span> — add or remove
            ontology imports.
          </p>
        </div>

        <div className="px-6 py-5 space-y-4">
          {error && (
            <div className="bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-8">
              <div className="h-8 w-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
            </div>
          ) : (
            <>
              <div>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-sm font-semibold text-gray-700">
                    Current Imports ({imports.length})
                  </h3>
                  {addableOntologies.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setShowAddPicker(!showAddPicker)}
                      className="text-xs font-medium text-indigo-600 hover:text-indigo-800"
                    >
                      {showAddPicker ? "Cancel" : "+ Add Import"}
                    </button>
                  )}
                </div>

                {imports.length === 0 ? (
                  <div className="text-sm text-gray-400 bg-gray-50 rounded-lg px-4 py-6 text-center">
                    No ontologies imported yet.
                  </div>
                ) : (
                  <div className="border border-gray-200 rounded-lg divide-y divide-gray-100">
                    {imports.map((imp) => (
                      <div
                        key={imp.edge_key}
                        className="flex items-center justify-between px-4 py-3"
                      >
                        <div className="min-w-0 flex-1">
                          <p className="text-sm font-medium text-gray-800 truncate">
                            {imp.target_name}
                          </p>
                          {imp.target_uri && (
                            <p className="text-xs text-gray-400 truncate">{imp.target_uri}</p>
                          )}
                        </div>
                        <button
                          type="button"
                          onClick={() => removeImport(imp.target_id)}
                          disabled={removing === imp.target_id}
                          className="ml-3 text-xs font-medium text-red-500 hover:text-red-700 disabled:opacity-50 flex-shrink-0"
                        >
                          {removing === imp.target_id ? "Removing…" : "Remove"}
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {showAddPicker && (
                <div>
                  <h3 className="text-sm font-semibold text-gray-700 mb-2">
                    Available Ontologies
                  </h3>
                  <div className="border border-gray-200 rounded-lg max-h-[200px] overflow-y-auto divide-y divide-gray-100">
                    {addableOntologies.map((ont) => {
                      const displayName = ont.name || ont.label || ont._key;
                      return (
                        <div
                          key={ont._key}
                          className="flex items-center justify-between px-4 py-2.5 hover:bg-gray-50"
                        >
                          <span className="text-sm text-gray-700 truncate">{displayName}</span>
                          <button
                            type="button"
                            onClick={() => addImport(ont._key)}
                            disabled={adding}
                            className="ml-3 text-xs font-medium text-indigo-600 hover:text-indigo-800 disabled:opacity-50 flex-shrink-0"
                          >
                            {adding ? "Adding…" : "Import"}
                          </button>
                        </div>
                      );
                    })}
                    {addableOntologies.length === 0 && (
                      <p className="text-sm text-gray-400 px-4 py-3 text-center">
                        All ontologies are already imported.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-gray-100 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-lg hover:bg-gray-50"
          >
            Done
          </button>
        </div>
      </div>
    </div>
  );
}
