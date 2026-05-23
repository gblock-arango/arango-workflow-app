"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api-client";
import AppHeader from "@/components/layout/AppHeader";
import {
  entityKey,
  loadUcEntitySelections,
  saveUcEntitySelections,
  type UcEntitySelection,
} from "@/lib/ucEntitySelections";

interface UcTableRow {
  table_id?: string;
  full_name: string;
  catalog: string;
  schema: string;
  name: string;
  table_type?: string;
  comment?: string;
}

interface UcColumnRow {
  name: string;
  type_text: string;
  type_name?: string | null;
  nullable?: boolean;
  comment: string;
  position?: number;
}

interface TableDetail {
  full_name: string;
  table_comment: string;
  table_type?: string;
  owner?: string;
  columns: UcColumnRow[];
}

export default function AddTablesPage() {
  const [tables, setTables] = useState<UcTableRow[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [listError, setListError] = useState("");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<UcTableRow | null>(null);
  const [detail, setDetail] = useState<TableDetail | null>(null);
  const [draftTableComment, setDraftTableComment] = useState("");
  const [draftColumns, setDraftColumns] = useState<UcColumnRow[]>([]);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");
  const [savedSelections, setSavedSelections] = useState<UcEntitySelection[]>([]);
  const [selectionKeys, setSelectionKeys] = useState<Set<string>>(new Set());
  const [selectionsDirty, setSelectionsDirty] = useState(false);
  const [savingSelections, setSavingSelections] = useState(false);
  const [selectionSaveMessage, setSelectionSaveMessage] = useState("");

  const loadTables = useCallback(async (q: string) => {
    setListLoading(true);
    setListError("");
    try {
      const params = new URLSearchParams();
      if (q.trim()) params.set("search", q.trim());
      const path = `/api/v1/uc/tables${params.toString() ? `?${params}` : ""}`;
      const res = await api.get<{ tables: UcTableRow[] }>(path);
      setTables(res.tables ?? []);
    } catch (err) {
      setTables([]);
      setListError(err instanceof Error ? err.message : String(err));
    } finally {
      setListLoading(false);
    }
  }, []);

  const refreshSavedSelections = useCallback(async () => {
    const entities = await loadUcEntitySelections();
    setSavedSelections(entities);
    setSelectionKeys(new Set(entities.map((e) => entityKey(e.table_full_name, e.column_name))));
    setSelectionsDirty(false);
  }, []);

  useEffect(() => {
    void refreshSavedSelections();
  }, [refreshSavedSelections]);

  useEffect(() => {
    const id = window.setTimeout(() => void loadTables(search), 300);
    return () => window.clearTimeout(id);
  }, [search, loadTables]);

  const loadDetail = useCallback(async (fullName: string) => {
    setDetailLoading(true);
    setDetailError("");
    setSaveMessage("");
    try {
      const data = await api.get<TableDetail>(
        `/api/v1/uc/tables/${encodeURIComponent(fullName)}`,
      );
      setDetail(data);
      setDraftTableComment(data.table_comment ?? "");
      setDraftColumns(
        (data.columns ?? []).map((c) => ({
          ...c,
          comment: c.comment ?? "",
        })),
      );
    } catch (err) {
      setDetail(null);
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const selectTable = (row: UcTableRow) => {
    setSelected(row);
    void loadDetail(row.full_name);
  };

  const resetDraft = () => {
    if (!detail) return;
    setDraftTableComment(detail.table_comment ?? "");
    setDraftColumns(
      detail.columns.map((c) => ({
        ...c,
        comment: c.comment ?? "",
      })),
    );
    setSaveMessage("");
  };

  const saveAnnotations = async () => {
    if (!selected) return;
    setSaving(true);
    setSaveMessage("");
    try {
      await api.put(
        `/api/v1/uc/tables/${encodeURIComponent(selected.full_name)}/annotations`,
        {
          table_comment: draftTableComment,
          columns: draftColumns.map((c) => ({
            name: c.name,
            comment: c.comment,
          })),
        },
      );
      setSaveMessage("Annotations saved to Unity Catalog.");
      await loadDetail(selected.full_name);
      void loadTables(search);
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const buildSelectionRow = (col: UcColumnRow): UcEntitySelection | null => {
    if (!selected) return null;
    return {
      table_full_name: selected.full_name,
      column_name: col.name,
      catalog: selected.catalog,
      schema: selected.schema,
      table_name: selected.name,
      type_text: col.type_text || col.type_name || "",
      comment: col.comment,
    };
  };

  const toggleColumnSelection = (col: UcColumnRow) => {
    if (!selected) return;
    const key = entityKey(selected.full_name, col.name);
    setSelectionKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
    setSelectionsDirty(true);
  };

  const selectAllColumns = () => {
    if (!selected) return;
    setSelectionKeys((prev) => {
      const next = new Set(prev);
      for (const col of draftColumns) {
        next.add(entityKey(selected.full_name, col.name));
      }
      return next;
    });
    setSelectionsDirty(true);
  };

  const clearTableColumnSelections = () => {
    if (!selected) return;
    setSelectionKeys((prev) => {
      const next = new Set(prev);
      for (const col of draftColumns) {
        next.delete(entityKey(selected.full_name, col.name));
      }
      return next;
    });
    setSelectionsDirty(true);
  };

  const persistSelections = async () => {
    setSavingSelections(true);
    setSelectionSaveMessage("");
    try {
      const byKey = new Map<string, UcEntitySelection>();
      for (const ent of savedSelections) {
        byKey.set(entityKey(ent.table_full_name, ent.column_name), ent);
      }
      if (selected) {
        for (const col of draftColumns) {
          const key = entityKey(selected.full_name, col.name);
          if (selectionKeys.has(key)) {
            const row = buildSelectionRow(col);
            if (row) byKey.set(key, row);
          } else {
            byKey.delete(key);
          }
        }
      }
      const merged = Array.from(byKey.values());
      await saveUcEntitySelections(merged);
      setSavedSelections(merged);
      setSelectionsDirty(false);
      setSelectionSaveMessage(
        `Saved ${merged.length} column${merged.length === 1 ? "" : "s"} to UC volume (settings/uc_entity_selections.json).`,
      );
    } catch (err) {
      setSelectionSaveMessage(
        err instanceof Error ? err.message : "Failed to save column selections.",
      );
    } finally {
      setSavingSelections(false);
    }
  };

  const currentTableSelectedCount = useMemo(() => {
    if (!selected) return 0;
    return draftColumns.filter((c) =>
      selectionKeys.has(entityKey(selected.full_name, c.name)),
    ).length;
  }, [selected, draftColumns, selectionKeys]);

  const filteredCount = useMemo(() => tables.length, [tables]);

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <AppHeader
        title="Add Tables"
        subtitle="Browse Unity Catalog tables, edit annotations, and select columns for extraction context."
        contentClassName="max-w-5xl"
      />

      <div className="max-w-5xl mx-auto px-6 py-8 space-y-6">
        <div className="rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-3 text-sm text-indigo-900 space-y-2">
          {savedSelections.length > 0 ? (
            <p>
              <strong>{savedSelections.length}</strong> UC column
              {savedSelections.length === 1 ? "" : "s"} saved for extraction — stored in{" "}
              <span className="font-mono text-xs">settings/uc_entity_selections.json</span> on
              the UC volume and injected into extraction prompts.
            </p>
          ) : (
            <p>No column selections saved yet. Select a table, check columns under Keep, then save.</p>
          )}
          <p className="text-xs text-indigo-800">
            You can return anytime: open a table, uncheck columns you no longer want, and click{" "}
            <strong>Save selection for extraction</strong> again to update the JSON file.
          </p>
          <button
            type="button"
            onClick={() => void refreshSavedSelections()}
            className="text-xs font-medium text-indigo-700 hover:text-indigo-900 underline"
          >
            Reload saved selections from UC volume
          </button>
        </div>
        {selectionSaveMessage && (
          <p
            className={`text-sm ${
              selectionSaveMessage.startsWith("Saved")
                ? "text-emerald-700"
                : "text-red-600"
            }`}
          >
            {selectionSaveMessage}
          </p>
        )}

        <section className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-100">
            <h2 className="text-sm font-semibold text-gray-800">Unity Catalog tables</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Search by catalog, schema, or table name
            </p>
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="e.g. workspace.default or financial"
              className="mt-3 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="max-h-72 overflow-y-auto divide-y divide-gray-100">
            {listLoading ? (
              <p className="px-5 py-6 text-sm text-gray-400 animate-pulse">Loading tables…</p>
            ) : listError ? (
              <p className="px-5 py-6 text-sm text-red-600">{listError}</p>
            ) : filteredCount === 0 ? (
              <p className="px-5 py-6 text-sm text-gray-400">No tables match your search.</p>
            ) : (
              tables.map((t) => (
                <button
                  key={t.full_name}
                  type="button"
                  onClick={() => selectTable(t)}
                  className={`w-full text-left px-5 py-3 hover:bg-gray-50 transition-colors ${
                    selected?.full_name === t.full_name
                      ? "bg-indigo-50 border-l-4 border-indigo-500"
                      : ""
                  }`}
                >
                  <p className="font-mono text-sm text-gray-900 truncate">{t.full_name}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {t.table_type ?? "TABLE"}
                    {t.comment ? ` · ${t.comment.slice(0, 80)}` : ""}
                  </p>
                </button>
              ))
            )}
          </div>
          {!listLoading && !listError && (
            <p className="px-5 py-2 text-xs text-gray-400 border-t border-gray-100">
              {filteredCount} table{filteredCount === 1 ? "" : "s"}
            </p>
          )}
        </section>

        <section className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          {!selected ? (
            <p className="text-sm text-gray-400">Select a table above to view and edit annotations.</p>
          ) : detailLoading ? (
            <p className="text-sm text-gray-400 animate-pulse">Loading table metadata…</p>
          ) : detailError ? (
            <p className="text-sm text-red-600">{detailError}</p>
          ) : detail ? (
            <div className="space-y-5">
              <div>
                <h2 className="text-sm font-semibold text-gray-800 font-mono">{selected.full_name}</h2>
                {detail.owner && (
                  <p className="text-xs text-gray-500 mt-0.5">Owner: {detail.owner}</p>
                )}
              </div>

              <div>
                <label
                  htmlFor="table-annotation"
                  className="block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1"
                >
                  Table annotation
                </label>
                <textarea
                  id="table-annotation"
                  rows={3}
                  value={draftTableComment}
                  onChange={(e) => setDraftTableComment(e.target.value)}
                  placeholder="UC table comment / description"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                />
              </div>

              <div>
                <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                    Columns
                  </h3>
                  <div className="flex items-center gap-2 text-xs">
                    <button
                      type="button"
                      onClick={selectAllColumns}
                      className="text-indigo-600 hover:text-indigo-800 font-medium"
                    >
                      Select all
                    </button>
                    <span className="text-gray-300">|</span>
                    <button
                      type="button"
                      onClick={clearTableColumnSelections}
                      className="text-gray-600 hover:text-gray-800"
                    >
                      Clear table
                    </button>
                    <span className="text-gray-400">
                      ({currentTableSelectedCount}/{draftColumns.length} selected)
                    </span>
                  </div>
                </div>
                <div className="overflow-x-auto border border-gray-200 rounded-lg">
                  <table className="min-w-full text-sm">
                    <thead className="bg-gray-50 text-left text-xs text-gray-500 uppercase">
                      <tr>
                        <th className="px-3 py-2 font-semibold w-10">Keep</th>
                        <th className="px-3 py-2 font-semibold">Column</th>
                        <th className="px-3 py-2 font-semibold">Data type</th>
                        <th className="px-3 py-2 font-semibold">Annotation</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {draftColumns.map((col, idx) => {
                        const key = entityKey(selected.full_name, col.name);
                        const checked = selectionKeys.has(key);
                        return (
                          <tr
                            key={col.name}
                            className={checked ? "bg-indigo-50/60" : undefined}
                          >
                            <td className="px-3 py-2 text-center">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleColumnSelection(col)}
                                aria-label={`Select ${col.name} for extraction`}
                              />
                            </td>
                            <td className="px-3 py-2 font-mono text-gray-900 whitespace-nowrap">
                              {col.name}
                              {col.nullable === false && (
                                <span className="ml-1 text-red-500" title="NOT NULL">
                                  *
                                </span>
                              )}
                            </td>
                            <td className="px-3 py-2 text-gray-600 whitespace-nowrap">
                              {col.type_text || col.type_name || "—"}
                            </td>
                            <td className="px-3 py-2 min-w-[16rem]">
                              <input
                                type="text"
                                value={col.comment}
                                onChange={(e) => {
                                  const next = [...draftColumns];
                                  next[idx] = { ...col, comment: e.target.value };
                                  setDraftColumns(next);
                                }}
                                className="w-full rounded border border-gray-200 px-2 py-1 text-sm focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500"
                                placeholder="Column comment"
                              />
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void persistSelections()}
                    disabled={savingSelections}
                    className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 font-medium"
                  >
                    {savingSelections
                      ? "Saving selection…"
                      : selectionsDirty
                        ? "Save selection for extraction"
                        : "Re-save selection to UC volume"}
                  </button>
                  {selectionsDirty && (
                    <button
                      type="button"
                      onClick={() => void refreshSavedSelections()}
                      className="text-xs text-gray-600 hover:text-gray-800"
                    >
                      Discard unsaved changes
                    </button>
                  )}
                </div>
              </div>

              {saveMessage && (
                <p
                  className={`text-sm ${
                    saveMessage.startsWith("Annotations saved")
                      ? "text-emerald-700"
                      : "text-red-600"
                  }`}
                >
                  {saveMessage}
                </p>
              )}

              <div className="flex items-center gap-3 pt-1">
                <button
                  type="button"
                  onClick={resetDraft}
                  disabled={saving}
                  className="text-sm px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => void saveAnnotations()}
                  disabled={saving}
                  className="text-sm px-4 py-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 font-medium"
                >
                  {saving ? "Saving…" : "Save annotations to UC"}
                </button>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </main>
  );
}
