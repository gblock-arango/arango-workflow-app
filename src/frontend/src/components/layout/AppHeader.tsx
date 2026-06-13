"use client";

import { ConnectionStatusWidget } from "@/components/connection/ConnectionStatusWidget";
import AppHeaderLogo from "@/components/layout/AppHeaderLogo";
import LlmConnectivityBadge from "@/components/layout/LlmConnectivityBadge";
import WorkflowNavButtons from "@/components/layout/WorkflowNavButtons";
import { useArangoConnectionStatus } from "@/lib/useArangoConnectionStatus";
import type { LlmModelFocus } from "@/lib/llmSettings";

interface AppHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  /** Toolbar controls shown before logo / connection status (upper-right) */
  actions?: React.ReactNode;
  /** Shared cached LLM probe badge (Parse & Chunk, Pipeline, etc.) */
  showLlmConnectivity?: boolean;
  /** Highlight extraction vs embedding model in the LLM settings modal. */
  llmModelFocus?: LlmModelFocus;
  /** Tabs or secondary row below the title (e.g. ontology-quality) */
  footer?: React.ReactNode;
  contentClassName?: string;
}

/** Arango wordmark + live connection status — upper-right on app headers. */
export function AppHeaderBrand() {
  const { health, healthDetail, profileName, connectionMeta } =
    useArangoConnectionStatus();

  return (
    <div className="flex flex-col items-end gap-1.5 shrink-0">
      <AppHeaderLogo />
      <ConnectionStatusWidget
        health={health}
        healthDetail={healthDetail}
        profileName={profileName}
        connectionMeta={connectionMeta}
        linkToConnection
        align="right"
      />
    </div>
  );
}

export default function AppHeader({
  title,
  subtitle,
  actions,
  showLlmConnectivity = false,
  llmModelFocus,
  footer,
  contentClassName = "w-full",
}: AppHeaderProps) {
  return (
    <header className="bg-white border-b border-gray-200">
      <div className={`${contentClassName} mx-auto px-6 ${footer ? "pt-4 pb-3" : "py-4"}`}>
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <h1 className="text-xl font-bold tracking-tight truncate">{title}</h1>
            {subtitle ? (
              <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
            ) : null}
            <WorkflowNavButtons className="mt-3" />
          </div>

          <div className="flex flex-col items-end gap-3 flex-shrink-0">
            {actions || showLlmConnectivity ? (
              <div className="flex items-center gap-3">
                {actions}
                {showLlmConnectivity ? <LlmConnectivityBadge modelFocus={llmModelFocus} /> : null}
              </div>
            ) : null}
            <AppHeaderBrand />
          </div>
        </div>
        {footer ? <div className="mt-3">{footer}</div> : null}
      </div>
    </header>
  );
}
