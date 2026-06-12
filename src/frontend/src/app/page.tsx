"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import AppLink from "@/components/layout/AppLink";
import { AppHeaderBrand } from "@/components/layout/AppHeader";
import { withBasePath } from "@/lib/base-path";
import { useActivePipelineAgents } from "@/lib/useActivePipelineAgents";
import { rememberWorkflowLane } from "@/lib/workflow-nav";
import { scheduleAfterInitialPaint } from "@/lib/scheduleAfterInitialPaint";

interface LibraryStats {
  total_count: number;
}

const img = (path: string) => withBasePath(path);

export default function Home() {
  const [ontologyCount, setOntologyCount] = useState<number | null>(null);
  const [statsError, setStatsError] = useState(false);

  useEffect(() => {
    return scheduleAfterInitialPaint(() => {
      api
        .get<LibraryStats>(
          "/api/v1/ontology/library?limit=1&include_edge_counts=false",
        )
        .then((data) => {
          setOntologyCount(data.total_count);
        })
        .catch(() => {
          setStatsError(true);
        });
    }, 900);
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-b from-slate-100 via-gray-50 to-gray-50 text-gray-900">
      {/* Hero */}
      <header className="border-b border-gray-200/80 bg-white/90 backdrop-blur-sm">
        <div className="w-full px-6 py-8 flex flex-col gap-6 lg:flex-row lg:items-center lg:gap-8">
          <div className="flex-shrink-0 flex justify-center lg:justify-start">
            <Image
              src={img("/images/arangoai-mascot.png")}
              alt="ArangoAI mascot"
              width={140}
              height={140}
              className="h-28 w-auto sm:h-32 object-contain drop-shadow-md"
              priority
            />
          </div>

          <div className="flex-1 text-center lg:text-left min-w-0">
            <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-gray-900">
              Arango Graph-Accelerated Agents
            </h1>
            <p className="mt-3 text-base sm:text-lg text-gray-600 leading-relaxed">
              Agentic tools using RBAC-compliant graph knowledge and graph-aware
              reasoning directly from your tables.
            </p>
          </div>

          <div className="flex-shrink-0 flex justify-center lg:justify-end">
            <AppHeaderBrand />
          </div>
        </div>
      </header>

      <div className="w-full px-6 pt-6 pb-10 space-y-6">
        {/* Status / medallion row */}
        <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3 sm:gap-4">
          <StatCard title="GRAPHS">
            {statsError ? (
              <p className="text-sm text-gray-400">Unavailable</p>
            ) : ontologyCount === null ? (
              <p className="text-sm text-gray-400 animate-pulse">Loading…</p>
            ) : (
              <p className="text-2xl font-bold tabular-nums">{ontologyCount}</p>
            )}
            <p className="text-xs text-gray-500 mt-1">registered ontologies</p>
          </StatCard>

          <StatCard title="BRONZE" titleClassName="text-[#b87333]">
            <p className="text-2xl font-bold text-[#cd7f32] tabular-nums">—</p>
            <p className="text-xs text-gray-500 mt-1">raw ingest</p>
          </StatCard>

          <StatCard title="SILVER" titleClassName="text-[#8a9199]">
            <p className="text-2xl font-bold text-[#a8a9ad] tabular-nums">—</p>
            <p className="text-xs text-gray-500 mt-1">curated graph</p>
          </StatCard>

          <StatCard title="GOLD" titleClassName="text-[#c9a227]">
            <p className="text-2xl font-bold text-[#d4af37] tabular-nums">—</p>
            <p className="text-xs text-gray-500 mt-1">production ready</p>
          </StatCard>

          <StatCardLink href="/adaptive-cdc" title="ADAPTIVE CDC" titleClassName="text-indigo-600">
            <p className="text-2xl font-bold text-indigo-600 tabular-nums">—</p>
            <p className="text-xs text-gray-500 mt-1">stream sync</p>
          </StatCardLink>

          <AgentsCard />
        </section>

        {/* Workflows */}
        <section>
          <div className="flex items-center justify-between gap-4 mb-2">
            <h2 className="text-lg font-semibold text-gray-900">
              Workflows
            </h2>
            <NavButton href="/dashboard" variant="green">
              Dashboard Visualization
            </NavButton>
          </div>

          <div className="space-y-2">
            <WorkflowLane
              laneId="build-graph"
              title="Build Your Graph"
              badge="AutoGraph"
              badgeClassName="bg-indigo-100 text-indigo-800"
              actions={[
                {
                  label: "Add Tables",
                  href: "/add-tables",
                  description: "Browse UC tables and edit annotations",
                },
                {
                  label: "Upload Documents",
                  href: "/upload",
                  description: "Ingest PDF, DOCX, PPTX, Markdown, JSON, JSON-LD",
                },
                {
                  label: "Parse & Chunk",
                  href: "/embedding",
                  description: "Prepare staged documents — parse, chunk, and embed",
                },
                {
                  label: "Run Extraction",
                  href: "/pipeline",
                  description: "Start extraction on ready docs; monitor agent runs",
                },
                {
                  label: "View Ontologies",
                  href: "/library",
                  description: "Browse graph library",
                },
              ]}
            />

            <WorkflowLane
              laneId="auto-detect"
              title="Recognize Anomalies in Streams"
              badge="AutoDetect"
              badgeClassName="bg-emerald-100 text-emerald-800"
              actions={[
                {
                  label: "Identify Patterns",
                  href: "/graph-patterns",
                  description: "Graphlet swim lanes from KG and Gold CDC",
                },
                {
                  label: "Train and Infer",
                  href: "/pipeline",
                  description: "GraphML on live events",
                },
                {
                  label: "Integrate Alerts",
                  href: "/adaptive-cdc",
                  description: "Route to observability",
                },
              ]}
            />

            <WorkflowLane
              laneId="auto-enrich"
              title="Smarten Your Catalog"
              badge="AutoEnrich"
              badgeClassName="bg-amber-100 text-amber-900"
              actions={[
                {
                  label: "Annotate Tables",
                  href: "/library",
                  description: "Column & table tags",
                },
                {
                  label: "Link Glossaries",
                  href: "/ontology-quality",
                  description: "Unity Catalog terms",
                },
                {
                  label: "Publish Tags",
                  href: "/ontology-quality",
                  description: "Share enriched metadata",
                },
              ]}
            />
          </div>
        </section>
      </div>
    </main>
  );
}

function StatCard({
  title,
  titleClassName = "text-gray-500",
  children,
}: {
  title: string;
  titleClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm min-h-[100px] flex flex-col">
      <h2
        className={`text-xs font-bold uppercase tracking-wide mb-3 ${titleClassName}`}
      >
        {title}
      </h2>
      <div className="flex-1 flex flex-col justify-center">{children}</div>
    </div>
  );
}

function StatCardLink({
  href,
  title,
  titleClassName = "text-gray-500",
  children,
}: {
  href: string;
  title: string;
  titleClassName?: string;
  children: React.ReactNode;
}) {
  return (
    <AppLink
      href={href}
      className="bg-white rounded-xl border border-gray-200 p-4 shadow-sm min-h-[100px] flex flex-col hover:border-indigo-300 hover:shadow-md transition-all group"
    >
      <h2
        className={`text-xs font-bold uppercase tracking-wide mb-3 group-hover:text-indigo-700 ${titleClassName}`}
      >
        {title}
      </h2>
      <div className="flex-1 flex flex-col justify-center">{children}</div>
    </AppLink>
  );
}

function AgentsCard() {
  const { count, loading, error } = useActivePipelineAgents();

  return (
    <StatCardLink href="/pipeline" title="AGENTS" titleClassName="text-violet-700">
      {loading ? (
        <p className="text-sm text-gray-400 animate-pulse">Loading…</p>
      ) : error ? (
        <p className="text-sm text-gray-400">Unavailable</p>
      ) : (
        <p className="text-2xl font-bold text-violet-700 tabular-nums">{count ?? 0}</p>
      )}
      <p className="text-xs text-gray-500 mt-1">
        active {count === 1 ? "agent" : "agents"}
      </p>
    </StatCardLink>
  );
}

function NavButton({
  href,
  children,
  variant = "default",
}: {
  href: string;
  children: React.ReactNode;
  variant?: "default" | "green";
}) {
  const className =
    variant === "green"
      ? "inline-flex items-center justify-center rounded-xl px-6 py-3 text-sm font-semibold text-emerald-900 bg-emerald-100 border border-emerald-200 shadow-sm hover:bg-emerald-200 hover:border-emerald-300 transition-colors"
      : "inline-flex items-center justify-center rounded-xl px-6 py-3 text-sm font-semibold text-gray-800 bg-white border border-gray-200 shadow-sm hover:bg-gray-50 hover:border-gray-300 transition-colors";
  return (
    <AppLink href={href} className={className}>
      {children}
    </AppLink>
  );
}

function WorkflowLane({
  laneId,
  title,
  badge,
  badgeClassName,
  actions,
}: {
  laneId: string;
  title: string;
  badge: string;
  badgeClassName: string;
  actions: {
    label: string;
    href: string;
    description: string;
    disabled?: boolean;
  }[];
}) {
  return (
    <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-100 bg-gradient-to-r from-gray-50 to-white flex flex-wrap items-center gap-3">
        <span
          className={`text-xs font-semibold px-2.5 py-1 rounded-full shrink-0 ${badgeClassName}`}
        >
          {badge}
        </span>
        <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
      </div>
      <div className="p-5 grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
        {actions.map((action) => (
          <WorkflowAction key={action.label} laneId={laneId} {...action} />
        ))}
      </div>
    </div>
  );
}

function WorkflowAction({
  laneId,
  label,
  href,
  description,
  disabled,
}: {
  laneId: string;
  label: string;
  href: string;
  description: string;
  disabled?: boolean;
}) {
  const className =
    "flex flex-col w-full min-w-0 h-full rounded-xl border border-gray-200 bg-gray-50/80 px-4 py-3 text-left transition-all " +
    (disabled
      ? "opacity-60 cursor-not-allowed"
      : "hover:border-indigo-300 hover:bg-indigo-50/50 hover:shadow-sm");

  const inner = (
    <>
      <span className="font-semibold text-gray-900 text-sm">{label}</span>
      <span className="text-xs text-gray-500 mt-1">{description}</span>
    </>
  );

  if (disabled) {
    return (
      <span className={className} aria-disabled="true">
        {inner}
      </span>
    );
  }

  return (
    <AppLink
      href={href}
      className={className}
      onClick={() => rememberWorkflowLane(laneId)}
    >
      {inner}
    </AppLink>
  );
}
