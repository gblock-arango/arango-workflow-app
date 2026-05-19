"use client";

import type { ReactNode } from "react";
import DockPanel, { DOCK_RAIL_WIDTH } from "./DockPanel";

export interface WorkspaceDockConfig {
  title: string;
  collapsed: boolean;
  onCollapsedChange: (collapsed: boolean) => void;
  width: number;
  onWidthChange: (width: number) => void;
  showRailWhenCollapsed?: boolean;
  minWidth?: number;
  maxWidth?: number;
  content: ReactNode;
}

export interface WorkspaceShellProps {
  leftDock: WorkspaceDockConfig;
  rightDock: WorkspaceDockConfig;
  /** Center tabbed widget area. */
  children: ReactNode;
}

/** Left inset for floating overlays (asset info panel) given dock state. */
export function workspaceLeftInset(leftDock: Pick<WorkspaceDockConfig, "collapsed" | "width">): number {
  return (leftDock.collapsed ? DOCK_RAIL_WIDTH : leftDock.width) + 4;
}

export default function WorkspaceShell({ leftDock, rightDock, children }: WorkspaceShellProps) {
  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      <DockPanel
        side="left"
        title={leftDock.title}
        collapsed={leftDock.collapsed}
        onCollapsedChange={leftDock.onCollapsedChange}
        width={leftDock.width}
        onWidthChange={leftDock.onWidthChange}
        minWidth={leftDock.minWidth}
        maxWidth={leftDock.maxWidth}
        showRailWhenCollapsed={leftDock.showRailWhenCollapsed}
      >
        {leftDock.content}
      </DockPanel>

      <div className="flex-1 flex flex-col min-w-0 min-h-0 p-0">{children}</div>

      <DockPanel
        side="right"
        title={rightDock.title}
        collapsed={rightDock.collapsed}
        onCollapsedChange={rightDock.onCollapsedChange}
        width={rightDock.width}
        onWidthChange={rightDock.onWidthChange}
        minWidth={rightDock.minWidth}
        maxWidth={rightDock.maxWidth}
        showRailWhenCollapsed={rightDock.showRailWhenCollapsed}
      >
        {rightDock.content}
      </DockPanel>
    </div>
  );
}
