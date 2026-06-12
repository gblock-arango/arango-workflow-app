"use client";

import AppLink from "@/components/layout/AppLink";
import { useWorkflowNav } from "@/lib/workflow-nav";

const baseBtn =
  "inline-flex items-center rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors";

function NavButton({
  href,
  disabled,
  children,
  title,
}: {
  href?: string;
  disabled?: boolean;
  children: React.ReactNode;
  title?: string;
}) {
  const className = disabled
    ? `${baseBtn} border border-gray-100 bg-gray-50 text-gray-400 cursor-not-allowed`
    : `${baseBtn} border border-gray-200 bg-white text-gray-800 shadow-sm hover:bg-gray-50 hover:border-gray-300`;

  if (disabled || !href) {
    return (
      <span className={className} aria-disabled="true" title={title}>
        {children}
      </span>
    );
  }

  return (
    <AppLink href={href} className={className} title={title}>
      {children}
    </AppLink>
  );
}

export default function WorkflowNavButtons({ className = "" }: { className?: string }) {
  const { prev, next, isHome, lane } = useWorkflowNav();

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <NavButton href="/" disabled={isHome} title="Return to home">
        Home
      </NavButton>
      <NavButton
        href={prev?.href}
        disabled={!prev}
        title={prev ? `Previous: ${prev.label}` : undefined}
      >
        Back
      </NavButton>
      <NavButton
        href={next?.href}
        disabled={!next}
        title={
          next
            ? `Next: ${next.label}${lane ? ` (${lane.title})` : ""}`
            : undefined
        }
      >
        Next
      </NavButton>
    </div>
  );
}
