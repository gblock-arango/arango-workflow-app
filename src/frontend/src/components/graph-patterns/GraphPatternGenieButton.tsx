"use client";

interface GraphPatternGenieButtonProps {
  patternId: string;
  patternName: string;
  onClick: (patternId: string) => void;
}

/** Placeholder — will open Genie chat scoped to this GraphPattern in a later workflow. */
export default function GraphPatternGenieButton({
  patternId,
  patternName,
  onClick,
}: GraphPatternGenieButtonProps) {
  return (
    <button
      type="button"
      className="w-full rounded-lg border border-violet-200 bg-violet-50 px-2 py-2 text-[11px] font-semibold leading-tight text-violet-900 hover:bg-violet-100 transition-colors"
      title={`Chat with Genie about “${patternName}”`}
      aria-label={`Chat with Genie about ${patternName}`}
      data-pattern-id={patternId}
      onClick={() => onClick(patternId)}
    >
      Chat with Genie
    </button>
  );
}
