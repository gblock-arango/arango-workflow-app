import type { ReactNode } from "react";

interface GraphPatternLaneSlotProps {
  children: ReactNode;
  /** Visually hidden label for screen readers (column identity). */
  label: string;
  className?: string;
}

/** Fixed grid cell — content is clipped to the column width. */
export function GraphPatternLaneSlot({
  children,
  label,
  className = "",
}: GraphPatternLaneSlotProps) {
  return (
    <div
      className={`min-w-0 overflow-hidden flex items-center ${className}`}
      aria-label={label}
    >
      {children}
    </div>
  );
}
