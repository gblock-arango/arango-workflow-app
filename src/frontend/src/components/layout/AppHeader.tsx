"use client";

import { ConnectionStatusWidget } from "@/components/connection/ConnectionStatusWidget";
import AppHeaderLogo from "@/components/layout/AppHeaderLogo";
import LlmConnectivityBadge from "@/components/layout/LlmConnectivityBadge";
import WorkflowNavButtons from "@/components/layout/WorkflowNavButtons";
import { useArangoConnectionStatus } from "@/lib/useArangoConnectionStatus";

interface AppHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  /** Toolbar controls shown on the title row (right side) */
  actions?: React.ReactNode;
  /** Shared cached LLM probe badge (Parse & Chunk, Pipeline, etc.) */
  showLlmConnectivity?: boolean;
  /** Tabs or secondary row below the title (e.g. ontology-quality) */
  footer?: React.ReactNode;
  contentClassName?: string;
}

/** Logo + live Arango connection status (used on custom headers such as ontology edit). */
export function AppHeaderBrand() {
  const { health, healthDetail, profileName, connectionMeta } =
    useArangoConnectionStatus();

  return (
    <div className="flex flex-col items-start gap-1.5 shrink-0">
      <AppHeaderLogo />
      <ConnectionStatusWidget
        health={health}
        healthDetail={healthDetail}
        profileName={profileName}
        connectionMeta={connectionMeta}
        linkToConnection
        align="left"
      />
    </div>
  );
}

export default function AppHeader({
  title,
  subtitle,
  actions,
  showLlmConnectivity = false,
  footer,
  contentClassName = "max-w-[1600px]",
}: AppHeaderProps) {
  return (
    <header className="bg-white border-b border-gray-200">
      <div className={`${contentClassName} mx-auto px-6 ${footer ? "pt-4 pb-3" : "py-4"}`}>
        <div className="flex items-start gap-4">
          <AppHeaderBrand />

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <h1 className="text-xl font-bold tracking-tight truncate">{title}</h1>
                {subtitle ? (
                  <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
                ) : null}
                <WorkflowNavButtons className="mt-3" />
              </div>
              <div className="flex items-center gap-3 flex-shrink-0">
                {actions}
                {showLlmConnectivity ? <LlmConnectivityBadge /> : null}
              </div>
            </div>
            {footer ? <div className="mt-3">{footer}</div> : null}
          </div>
        </div>
      </div>
    </header>
  );
}
