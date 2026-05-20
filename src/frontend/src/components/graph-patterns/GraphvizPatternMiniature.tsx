"use client";

import { useEffect, useRef, useState } from "react";
import type { GraphPatternEdge, GraphPatternNode } from "@/types/graphPattern";
import { patternToDot } from "@/lib/graphPatterns/patternToDot";

interface GraphvizPatternMiniatureProps {
  nodes: GraphPatternNode[];
  edges: GraphPatternEdge[];
  className?: string;
}

/** Renders a small Graphviz SVG preview (WASM) for one GraphPattern graphlet. */
export default function GraphvizPatternMiniature({
  nodes,
  edges,
  className = "",
}: GraphvizPatternMiniatureProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const host = hostRef.current;
    if (!host || nodes.length === 0) return;

    let cancelled = false;
    setError(null);
    host.replaceChildren();

    (async () => {
      try {
        const { instance } = await import("@viz-js/viz");
        const viz = await instance();
        const dot = patternToDot(nodes, edges);
        const svg = viz.renderSVGElement(dot);
        if (cancelled || !hostRef.current) return;
        svg.setAttribute("width", "100%");
        svg.setAttribute("height", "100%");
        svg.style.maxWidth = "100%";
        svg.style.maxHeight = "100%";
        hostRef.current.appendChild(svg);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Graphviz render failed");
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [nodes, edges]);

  return (
    <div
      className={`relative flex items-center justify-center rounded-lg border border-gray-700 bg-black overflow-hidden ${className}`}
      data-testid="graph-pattern-miniature"
    >
      <div ref={hostRef} className="w-full h-full min-h-[88px] p-1 [&_svg]:block" />
      {error && (
        <p className="absolute inset-0 flex items-center justify-center text-[10px] text-red-400 px-2 text-center">
          {error}
        </p>
      )}
    </div>
  );
}
