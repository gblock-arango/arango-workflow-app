import type { GraphPatternFeatures } from "@/types/graphPattern";

interface FeatureChipProps {
  icon: string;
  label: string;
  active?: boolean;
  warn?: boolean;
  compact?: boolean;
}

function FeatureChip({
  icon,
  label,
  active = true,
  warn = false,
  compact = false,
}: FeatureChipProps) {
  const tone = warn
    ? "border-amber-300 bg-amber-50 text-amber-900"
    : active
      ? "border-gray-200 bg-gray-50 text-gray-700"
      : "border-gray-200 bg-white text-gray-400";

  return (
    <span
      className={`inline-flex shrink-0 items-center gap-0.5 rounded border font-medium whitespace-nowrap ${
        compact ? "px-1.5 py-0.5 text-[10px]" : "px-2 py-1 text-[11px]"
      } ${tone} ${!active && !warn ? "opacity-50" : ""}`}
      title={label}
    >
      <span aria-hidden>{icon}</span>
      <span className="truncate">{label}</span>
    </span>
  );
}

interface FeatureIconProps {
  icon: string;
  label: string;
  active?: boolean;
  warn?: boolean;
}

function FeatureIcon({ icon, label, active = true, warn = false }: FeatureIconProps) {
  const tone = warn
    ? "border-amber-300 bg-amber-50 text-amber-900"
    : active
      ? "border-gray-200 bg-gray-50 text-gray-700"
      : "border-gray-200 bg-white text-gray-400 opacity-50";

  return (
    <span
      className={`flex h-7 w-full items-center justify-center rounded border text-sm ${tone}`}
      title={label}
      aria-label={label}
    >
      <span aria-hidden>{icon}</span>
    </span>
  );
}

function formatLastSeen(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

interface GraphPatternFeaturesProps {
  features: GraphPatternFeatures;
  variant?: "full" | "lane";
}

/** Feature chips for a GraphPattern; `lane` is a 2×2 icon grid (max two per row). */
export default function GraphPatternFeatures({
  features,
  variant = "full",
}: GraphPatternFeaturesProps) {
  if (variant === "lane") {
    return (
      <div className="grid w-full grid-cols-2 gap-1">
        <FeatureIcon icon="🔁" label={`Observed ${features.timesObserved} times`} />
        <FeatureIcon
          icon="🔗"
          label="Missing link observed"
          active={features.missingLinkObserved}
          warn={features.missingLinkObserved}
        />
        <FeatureIcon
          icon="🧬"
          label="Graph embedding in vector store"
          active={features.embeddingInVectorStore}
        />
        <FeatureIcon icon="🥇" label="Witnessed in Gold CDC" active={features.goldTableCdcWitnessed} />
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-1.5 min-w-0">
      <FeatureChip icon="🔁" label={`Observed ×${features.timesObserved}`} />
      <FeatureChip
        icon="🔗"
        label="Missing link"
        active={features.missingLinkObserved}
        warn={features.missingLinkObserved}
      />
      <FeatureChip
        icon="🧬"
        label="Graph embedding"
        active={features.embeddingInVectorStore}
      />
      <FeatureChip icon="🥇" label="Gold CDC" active={features.goldTableCdcWitnessed} />
      <FeatureChip
        icon="◈"
        label="Knowledge graph"
        active={features.knowledgeGraphWitnessed}
      />
      <FeatureChip icon="🕐" label={`Last seen ${formatLastSeen(features.lastSeen)}`} />
    </div>
  );
}
