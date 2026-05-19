"use client";

import { useCallback, useRef, type ReactNode } from "react";

export const DOCK_RAIL_WIDTH = 36;

const DEFAULT_MIN = 220;
const DEFAULT_MAX = 520;

export interface DockPanelProps {
  side: "left" | "right";
  title: string;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  width: number;
  onWidthChange: (width: number) => void;
  minWidth?: number;
  maxWidth?: number;
  /** When collapsed, show a narrow rail with expand control (typical for left assets). */
  showRailWhenCollapsed?: boolean;
  children: ReactNode;
}

export default function DockPanel({
  side,
  title,
  collapsed,
  onCollapsedChange,
  width,
  onWidthChange,
  minWidth = DEFAULT_MIN,
  maxWidth = DEFAULT_MAX,
  showRailWhenCollapsed = false,
  children,
}: DockPanelProps) {
  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(width);

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      resizingRef.current = true;
      startXRef.current = e.clientX;
      startWidthRef.current = width;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      function onMouseMove(ev: MouseEvent) {
        if (!resizingRef.current) return;
        const delta =
          side === "left" ? ev.clientX - startXRef.current : startXRef.current - ev.clientX;
        const next = Math.min(maxWidth, Math.max(minWidth, startWidthRef.current + delta));
        onWidthChange(next);
      }

      function onMouseUp() {
        resizingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      }

      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [maxWidth, minWidth, onWidthChange, side, width],
  );

  if (collapsed && showRailWhenCollapsed) {
    return (
      <aside
        style={{ width: DOCK_RAIL_WIDTH }}
        className="flex-shrink-0 border-gray-200 bg-white flex flex-col items-center py-2 gap-2 border-r"
        data-dock={side}
        data-collapsed="true"
      >
        <button
          type="button"
          onClick={() => onCollapsedChange(false)}
          className="p-1.5 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors"
          title={`Show ${title}`}
          aria-label={`Show ${title}`}
        >
          <ChevronIcon side={side} expand />
        </button>
        <span
          className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 [writing-mode:vertical-rl] rotate-180 select-none"
          aria-hidden
        >
          {title}
        </span>
      </aside>
    );
  }

  if (collapsed) {
    return (
      <aside
        style={{ width: DOCK_RAIL_WIDTH }}
        className={`flex-shrink-0 border-gray-200 bg-white flex flex-col items-center py-2 ${
          side === "left" ? "border-r" : "border-l"
        }`}
        data-dock={side}
        data-collapsed="true"
      >
        <button
          type="button"
          onClick={() => onCollapsedChange(false)}
          className="p-1.5 rounded-md text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-colors"
          title={`Show ${title}`}
          aria-label={`Show ${title}`}
        >
          <ChevronIcon side={side} expand />
        </button>
      </aside>
    );
  }

  const resizeHandle = (
    <div
      className="w-1 cursor-col-resize hover:bg-indigo-400 active:bg-indigo-500 transition-colors flex-shrink-0"
      onMouseDown={handleResizeStart}
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${title}`}
    />
  );

  return (
    <>
      {side === "right" && resizeHandle}
      <aside
        style={{ width }}
        className={`flex-shrink-0 overflow-hidden flex flex-col bg-white ${
          side === "left" ? "border-r border-gray-200" : "border-l border-gray-200"
        }`}
        data-dock={side}
        data-collapsed="false"
      >
        <div className="flex items-center justify-between px-2 py-1.5 border-b border-gray-200 flex-shrink-0 bg-white">
          <span className="text-xs font-semibold text-gray-700 truncate">{title}</span>
          <button
            type="button"
            onClick={() => onCollapsedChange(true)}
            className="p-1 rounded text-gray-500 hover:text-gray-800 hover:bg-gray-100"
            title={`Hide ${title}`}
            aria-label={`Hide ${title}`}
          >
            <ChevronIcon side={side} expand={false} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
      </aside>
      {side === "left" && resizeHandle}
    </>
  );
}

function ChevronIcon({ side, expand }: { side: "left" | "right"; expand: boolean }) {
  const pointsLeft =
    (side === "left" && expand) || (side === "right" && !expand);
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth={2}
        d={pointsLeft ? "M15 19l-7-7 7-7" : "M9 5l7 7-7 7"}
      />
    </svg>
  );
}
