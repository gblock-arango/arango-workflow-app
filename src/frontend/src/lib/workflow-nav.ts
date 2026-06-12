"use client";

import { useMemo } from "react";
import { usePathname } from "next/navigation";

export const WORKFLOW_LANE_STORAGE_KEY = "aoe_workflow_lane";

export interface WorkflowStep {
  href: string;
  label: string;
}

export interface WorkflowLane {
  id: string;
  title: string;
  steps: WorkflowStep[];
}

/** Swimlane order from the home page workflow sections. */
export const WORKFLOW_LANES: WorkflowLane[] = [
  {
    id: "build-graph",
    title: "Build Your Graph",
    steps: [
      { href: "/connection", label: "Connection" },
      { href: "/add-tables", label: "Add Tables" },
      { href: "/upload", label: "Upload Documents" },
      { href: "/embedding", label: "Parse & Chunk" },
      { href: "/pipeline", label: "Run Extraction" },
      { href: "/library", label: "View Ontologies" },
    ],
  },
  {
    id: "auto-detect",
    title: "Recognize Anomalies in Streams",
    steps: [
      { href: "/graph-patterns", label: "Identify Patterns" },
      { href: "/pipeline", label: "Train and Infer" },
      { href: "/adaptive-cdc", label: "Integrate Alerts" },
    ],
  },
  {
    id: "auto-enrich",
    title: "Smarten Your Catalog",
    steps: [
      { href: "/library", label: "Annotate Tables" },
      { href: "/ontology-quality", label: "Link Glossaries" },
    ],
  },
];

export function rememberWorkflowLane(laneId: string): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(WORKFLOW_LANE_STORAGE_KEY, laneId);
  } catch {
    /* private mode */
  }
}

function getStoredLaneId(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return sessionStorage.getItem(WORKFLOW_LANE_STORAGE_KEY);
  } catch {
    return null;
  }
}

function normalizeAppPath(pathname: string): string {
  return pathname.replace(/\/$/, "") || "/";
}

function stepMatches(pathname: string, href: string): boolean {
  const norm = normalizeAppPath(pathname);
  const step = href.replace(/\/$/, "") || "/";
  if (step === "/") return norm === "/";
  return norm === step || norm.startsWith(`${step}/`);
}

function findLaneForPath(
  pathname: string,
  preferredLaneId: string | null,
): WorkflowLane | null {
  const matching = WORKFLOW_LANES.filter((lane) =>
    lane.steps.some((step) => stepMatches(pathname, step.href)),
  );
  if (matching.length === 0) return null;
  if (preferredLaneId) {
    const preferred = matching.find((lane) => lane.id === preferredLaneId);
    if (preferred) return preferred;
  }
  return matching[0];
}

export interface WorkflowNavState {
  lane: WorkflowLane | null;
  stepIndex: number;
  prev: WorkflowStep | null;
  next: WorkflowStep | null;
  isHome: boolean;
}

export function useWorkflowNav(): WorkflowNavState {
  const pathname = usePathname();

  return useMemo(() => {
    const isHome = normalizeAppPath(pathname) === "/";

    if (isHome) {
      const lane =
        WORKFLOW_LANES.find((item) => item.id === getStoredLaneId()) ??
        WORKFLOW_LANES[0];
      return {
        lane,
        stepIndex: -1,
        prev: null,
        next: lane.steps[0] ?? null,
        isHome: true,
      };
    }

    const lane = findLaneForPath(pathname, getStoredLaneId());
    if (!lane) {
      return { lane: null, stepIndex: -1, prev: null, next: null, isHome: false };
    }

    const stepIndex = lane.steps.findIndex((step) =>
      stepMatches(pathname, step.href),
    );
    if (stepIndex < 0) {
      return { lane, stepIndex: -1, prev: null, next: null, isHome: false };
    }

    return {
      lane,
      stepIndex,
      prev: stepIndex > 0 ? lane.steps[stepIndex - 1] : null,
      next:
        stepIndex < lane.steps.length - 1 ? lane.steps[stepIndex + 1] : null,
      isHome: false,
    };
  }, [pathname]);
}
