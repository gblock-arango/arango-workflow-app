import type {
  AdaptiveCdcOnlineStatus,
  GraphPatternSeverity,
} from "@/types/graphPattern";

const SEVERITY_STYLES: Record<GraphPatternSeverity, string> = {
  low: "bg-gray-200 text-gray-800 border-gray-300",
  medium: "bg-yellow-100 text-yellow-900 border-yellow-300",
  high: "bg-red-100 text-red-900 border-red-300",
};

export function SeverityBadge({ severity }: { severity: GraphPatternSeverity }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wide ${SEVERITY_STYLES[severity]}`}
    >
      {severity}
    </span>
  );
}

function cdcLabel(status: AdaptiveCdcOnlineStatus, online: boolean): string {
  if (online && status === "online") return "Adaptive CDC online";
  if (status === "syncing") return "Adaptive CDC syncing";
  if (status === "degraded") return "Adaptive CDC degraded";
  return "Adaptive CDC offline";
}

function cdcStyle(status: AdaptiveCdcOnlineStatus, online: boolean): string {
  if (online && status === "online") {
    return "bg-emerald-100 text-emerald-900 border-emerald-300";
  }
  if (status === "syncing") {
    return "bg-sky-100 text-sky-900 border-sky-300";
  }
  if (status === "degraded") {
    return "bg-amber-100 text-amber-900 border-amber-300";
  }
  return "bg-gray-100 text-gray-600 border-gray-300";
}

export function AdaptiveCdcBadge({
  online,
  status,
}: {
  online: boolean;
  status: AdaptiveCdcOnlineStatus;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${cdcStyle(status, online)}`}
      title={cdcLabel(status, online)}
    >
      {online && status === "online" ? (
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden />
      ) : null}
      {cdcLabel(status, online)}
    </span>
  );
}
