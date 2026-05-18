"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  loadFeedbackLearningArtifacts,
  type FeedbackLearningArtifacts,
  type FeedbackLearningExample,
} from "@/lib/feedbackLearning";

interface Props {
  ontologyId?: string | null;
  ontologyName?: string | null;
  onClose: () => void;
}

const EMPTY_ARTIFACTS: FeedbackLearningArtifacts = {
  ontology_id: null,
  status: "not_available",
  auto_apply: false,
  summary: {
    total_examples: 0,
    regression_candidates: 0,
    by_action: {},
    by_issue_reason: {},
  },
  examples: [],
  regression_candidates: [],
  benchmark_fixture: {
    schema_version: "hitl-regression-v1",
    ontology_id: null,
    generated_from: "curation_decisions",
    documents: [],
    summary: {
      documents: 0,
      negative_examples: 0,
      positive_classes: 0,
      positive_relations: 0,
    },
  },
};

export default function FeedbackLearningOverlay({
  ontologyId,
  ontologyName,
  onClose,
}: Props) {
  const [data, setData] = useState<FeedbackLearningArtifacts>(EMPTY_ARTIFACTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const artifacts = await loadFeedbackLearningArtifacts({
        ontologyId,
        limit: 100,
      });
      setData(artifacts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load feedback artifacts");
    } finally {
      setLoading(false);
    }
  }, [ontologyId]);

  useEffect(() => {
    void load();
  }, [load]);

  const fixtureJson = useMemo(
    () => JSON.stringify(data.benchmark_fixture, null, 2),
    [data.benchmark_fixture],
  );

  const downloadFixture = useCallback(() => {
    const blob = new Blob([fixtureJson], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = ontologyId
      ? `hitl_regression_${ontologyId}.json`
      : "hitl_regression.json";
    anchor.click();
    URL.revokeObjectURL(url);
  }, [fixtureJson, ontologyId]);

  const scopeLabel = ontologyId
    ? ontologyName || ontologyId
    : "All ontologies";

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="relative bg-white rounded-2xl shadow-2xl w-[92vw] max-w-[1100px] max-h-[90vh] overflow-y-auto">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-gray-400 hover:text-gray-700 text-2xl leading-none"
          aria-label="Close"
        >
          x
        </button>

        <div className="px-8 py-6 border-b border-gray-100">
          <p className="text-xs font-semibold uppercase tracking-wide text-indigo-600">
            Gated learning artifacts
          </p>
          <h2 className="mt-1 text-2xl font-bold text-gray-950">
            Feedback Learning Review
          </h2>
          <p className="mt-2 text-sm text-gray-500">
            Scope: <span className="font-medium text-gray-700">{scopeLabel}</span>. These
            artifacts are review/export data only and do not change extraction behavior.
          </p>
        </div>

        <div className="px-8 py-6 space-y-6">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              {error}
            </div>
          )}

          {loading ? (
            <div className="flex justify-center py-16">
              <div className="h-8 w-8 border-4 border-indigo-200 border-t-indigo-600 rounded-full animate-spin" />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-1 md:grid-cols-5 gap-3">
                <SummaryCard label="Auto Apply" value={data.auto_apply ? "true" : "false"} tone="safe" />
                <SummaryCard label="Examples" value={data.summary.total_examples} />
                <SummaryCard label="Regressions" value={data.summary.regression_candidates} />
                <SummaryCard label="Fixture Docs" value={data.benchmark_fixture.summary.documents} />
                <SummaryCard label="Negative Examples" value={data.benchmark_fixture.summary.negative_examples} />
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <CountPanel title="By action" counts={data.summary.by_action} />
                <CountPanel title="By issue reason" counts={data.summary.by_issue_reason} />
              </div>

              <section className="rounded-xl border border-gray-200 bg-gray-50 p-4">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-gray-800">
                      Benchmark Fixture Export
                    </h3>
                    <p className="mt-1 text-xs text-gray-500">
                      Schema {data.benchmark_fixture.schema_version}; run with
                      {" "}
                      <code className="font-mono">--dataset hitl-regression</code>.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={downloadFixture}
                    className="rounded-lg bg-indigo-600 px-3 py-2 text-xs font-semibold text-white hover:bg-indigo-700"
                  >
                    Download JSON
                  </button>
                </div>
                <pre className="mt-3 max-h-52 overflow-auto rounded-lg bg-gray-950 p-3 text-xs text-gray-100">
                  {fixtureJson}
                </pre>
              </section>

              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <ExampleList
                  title="Prompt Guidance Examples"
                  examples={data.examples}
                  empty="No feedback examples available yet."
                />
                <ExampleList
                  title="Regression Candidates"
                  examples={data.regression_candidates}
                  empty="No regression candidates available yet."
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string | number;
  tone?: "safe";
}) {
  return (
    <div className={`rounded-xl border p-4 ${tone === "safe" ? "border-emerald-200 bg-emerald-50" : "border-gray-200 bg-white"}`}>
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">
        {label}
      </p>
      <p className={`mt-1 text-2xl font-bold ${tone === "safe" ? "text-emerald-700" : "text-gray-900"}`}>
        {value}
      </p>
    </div>
  );
}

function CountPanel({
  title,
  counts,
}: {
  title: string;
  counts: Record<string, number>;
}) {
  const entries = Object.entries(counts);
  return (
    <section className="rounded-xl border border-gray-200 bg-white p-4">
      <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-gray-400">No counts yet.</p>
      ) : (
        <div className="mt-3 flex flex-wrap gap-2">
          {entries.map(([key, count]) => (
            <span
              key={key}
              className="rounded-full bg-gray-100 px-3 py-1 text-xs font-medium text-gray-700"
            >
              {key.replace(/_/g, " ")}: {count}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

function ExampleList({
  title,
  examples,
  empty,
}: {
  title: string;
  examples: FeedbackLearningExample[];
  empty: string;
}) {
  return (
    <section className="rounded-xl border border-gray-200 bg-white">
      <div className="border-b border-gray-100 px-4 py-3">
        <h3 className="text-sm font-semibold text-gray-800">
          {title} ({examples.length})
        </h3>
      </div>
      {examples.length === 0 ? (
        <p className="px-4 py-6 text-sm text-gray-400">{empty}</p>
      ) : (
        <div className="max-h-80 overflow-auto divide-y divide-gray-100">
          {examples.slice(0, 20).map((example, idx) => (
            <article key={`${example.decision_key ?? "example"}-${idx}`} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-semibold text-gray-900">
                  {example.entity_key ?? example.decision_key ?? "Unknown entity"}
                </span>
                {example.action && (
                  <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-[11px] font-medium text-indigo-700">
                    {example.action}
                  </span>
                )}
                {example.entity_type && (
                  <span className="rounded-full bg-gray-100 px-2 py-0.5 text-[11px] text-gray-600">
                    {example.entity_type}
                  </span>
                )}
              </div>
              {example.issue_reasons.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {example.issue_reasons.map((reason) => (
                    <span key={reason} className="rounded bg-amber-50 px-2 py-0.5 text-[11px] text-amber-700">
                      {reason.replace(/_/g, " ")}
                    </span>
                  ))}
                </div>
              )}
              {example.prompt_guidance && (
                <p className="mt-2 text-sm text-gray-600">{example.prompt_guidance}</p>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
