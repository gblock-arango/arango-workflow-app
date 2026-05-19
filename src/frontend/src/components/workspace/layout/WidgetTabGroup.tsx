"use client";

import { useState, type ReactNode } from "react";

export interface WidgetTab {
  id: string;
  label: string;
  /** Optional short badge (e.g. ontology name). */
  badge?: string;
  content: ReactNode;
}

export interface WidgetTabGroupProps {
  tabs: WidgetTab[];
  defaultTabId?: string;
  className?: string;
}

export default function WidgetTabGroup({ tabs, defaultTabId, className = "" }: WidgetTabGroupProps) {
  const [activeId, setActiveId] = useState(defaultTabId ?? tabs[0]?.id ?? "");

  if (tabs.length === 0) {
    return (
      <div className={`flex flex-col flex-1 min-h-0 bg-white ${className}`}>
        <p className="text-sm text-gray-500 m-auto">No widgets</p>
      </div>
    );
  }

  const active = tabs.find((t) => t.id === activeId) ?? tabs[0];

  return (
    <div
      className={`flex flex-col flex-1 min-h-0 min-w-0 bg-white border border-gray-200 rounded-lg overflow-hidden m-1 ${className}`}
      data-widget-tab-group
    >
      <div
        className="flex items-end gap-0 border-b border-gray-200 bg-gray-50 flex-shrink-0 px-1 pt-1"
        role="tablist"
      >
        {tabs.map((tab) => {
          const isActive = tab.id === active.id;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveId(tab.id)}
              className={`px-3 py-2 text-xs font-medium rounded-t-md border border-b-0 transition-colors ${
                isActive
                  ? "bg-white text-indigo-700 border-gray-200"
                  : "bg-transparent text-gray-500 border-transparent hover:text-gray-700"
              }`}
              data-widget-tab={tab.id}
            >
              <span>{tab.label}</span>
              {tab.badge && (
                <span className="ml-2 text-[10px] font-normal text-gray-500 truncate max-w-[140px] inline-block align-bottom">
                  {tab.badge}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <div className="flex-1 min-h-0 overflow-hidden bg-white" role="tabpanel" data-widget-panel={active.id}>
        {active.content}
      </div>
    </div>
  );
}
