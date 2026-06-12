"use client";

import AppLink from "@/components/layout/AppLink";
import type { ArangoConnectionState } from "@/lib/useArangoConnectionStatus";

export function ConnectionStatusWidget({
  health,
  healthDetail,
  profileName,
  connectionMeta = "",
  linkToConnection = false,
  align = "right",
}: {
  health: ArangoConnectionState;
  healthDetail: string;
  profileName: string;
  connectionMeta?: string;
  linkToConnection?: boolean;
  align?: "left" | "right" | "center";
}) {
  const alignClass =
    align === "left"
      ? "text-left"
      : align === "center"
        ? "text-center"
        : "text-right lg:text-right";

  const dotClass =
    health === "loading"
      ? "bg-yellow-400 animate-pulse"
      : health === "connected"
        ? "bg-emerald-500"
        : health === "unset"
          ? "bg-yellow-400"
          : "bg-red-500";

  const primaryText = (() => {
    if (health === "loading") return "Checking…";
    if (health === "connected") return profileName || healthDetail || "Connected";
    if (health === "unset") return "Click to Connect";
    return "Connection Failed";
  })();

  const primaryClass = (() => {
    if (health === "connected") {
      return "text-sm font-medium text-emerald-600";
    }
    if (health === "unset") {
      return "text-sm font-medium italic text-yellow-600";
    }
    if (health === "failed") {
      return "text-sm font-medium italic text-red-600";
    }
    return "text-sm font-medium text-gray-600";
  })();

  const secondary = (() => {
    if (health === "connected") {
      if (connectionMeta) return connectionMeta;
      if (healthDetail && healthDetail !== profileName) return healthDetail;
      return "";
    }
    if (health === "failed" && profileName) return profileName;
    return "";
  })();

  const content = (
    <div className={`${alignClass} min-w-0`}>
      <div
        className={`flex items-center gap-2 ${
          align === "right"
            ? "justify-center lg:justify-end"
            : align === "center"
              ? "justify-center"
              : "justify-start"
        }`}
      >
        <span className={`inline-block h-2 w-2 rounded-full shrink-0 ${dotClass}`} />
        <span className={primaryClass}>{primaryText}</span>
      </div>
      {secondary ? (
        <p
          className={`mt-1 text-xs max-w-[280px] truncate ${
            health === "failed" ? "text-gray-500" : "text-gray-500"
          }`}
        >
          {secondary}
        </p>
      ) : null}
    </div>
  );

  if (linkToConnection && health !== "loading") {
    return (
      <AppLink
        href="/connection"
        className="block hover:opacity-90 transition-opacity"
        title="Configure Arango connection"
      >
        {content}
      </AppLink>
    );
  }

  return content;
}
