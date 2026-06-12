"use client";

import type { ReactNode } from "react";

/** Horizontal shell shared with AppHeader — full viewport width with consistent padding. */
export const PAGE_SHELL_X = "w-full px-6";

interface PageContentProps {
  children: ReactNode;
  /** Vertical spacing / layout utilities (default includes top/bottom padding). */
  className?: string;
}

export default function PageContent({
  children,
  className = "py-8",
}: PageContentProps) {
  return <div className={`${PAGE_SHELL_X} ${className}`.trim()}>{children}</div>;
}
