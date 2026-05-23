"use client";

import AppLink from "@/components/layout/AppLink";

export function AppHeaderNav() {
  return (
    <AppLink
      href="/"
      className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
    >
      Home
    </AppLink>
  );
}

interface AppHeaderProps {
  title: string;
  subtitle?: React.ReactNode;
  /** Toolbar controls shown before Home */
  actions?: React.ReactNode;
  /** Tabs or secondary row below the title (e.g. ontology-quality) */
  footer?: React.ReactNode;
  contentClassName?: string;
}

export default function AppHeader({
  title,
  subtitle,
  actions,
  footer,
  contentClassName = "max-w-[1600px]",
}: AppHeaderProps) {
  return (
    <header className="bg-white border-b border-gray-200">
      <div className={`${contentClassName} mx-auto px-6 ${footer ? "pt-4" : "py-4"}`}>
        <div className="flex items-center justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-xl font-bold tracking-tight truncate">{title}</h1>
            {subtitle ? (
              <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
            ) : null}
          </div>
          <div className="flex items-center gap-3 flex-shrink-0">
            {actions}
            <AppHeaderNav />
          </div>
        </div>
        {footer ? <div className="mt-3">{footer}</div> : null}
      </div>
    </header>
  );
}
