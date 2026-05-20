"use client";

import { useEffect, useRef, useState } from "react";

export type GraphPatternMenuAction = "save" | "delete" | "apply";

interface GraphPatternActionsMenuProps {
  persisted: boolean;
  onAction: (action: GraphPatternMenuAction) => void;
}

export default function GraphPatternActionsMenu({
  persisted,
  onAction,
}: GraphPatternActionsMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  const choose = (action: GraphPatternMenuAction) => {
    setOpen(false);
    onAction(action);
  };

  return (
    <div ref={rootRef} className="relative flex-shrink-0">
      <button
        type="button"
        className="flex h-9 w-9 flex-col items-center justify-center gap-0.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 hover:text-gray-800"
        aria-label="GraphPattern actions"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="h-1 w-1 rounded-full bg-current" />
        <span className="h-1 w-1 rounded-full bg-current" />
        <span className="h-1 w-1 rounded-full bg-current" />
      </button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-20 mt-1 w-44 rounded-lg border border-gray-200 bg-white py-1 shadow-lg"
        >
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-sm text-gray-800 hover:bg-gray-50"
            onClick={() => choose("save")}
          >
            {persisted ? "Update saved pattern" : "Save pattern"}
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-sm text-gray-800 hover:bg-gray-50"
            onClick={() => choose("apply")}
          >
            Apply to Adaptive CDC
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-sm text-red-700 hover:bg-red-50"
            onClick={() => choose("delete")}
          >
            Delete pattern
          </button>
        </div>
      ) : null}
    </div>
  );
}
