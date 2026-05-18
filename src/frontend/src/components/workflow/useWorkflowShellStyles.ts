"use client";

import { useEffect } from "react";
import { withBasePath } from "@/lib/base-path";

const LINK_ID = "workflow-shell-stylesheet";

/** Load /workflow-shell.css from public/ — bypasses PostCSS/Tailwind native bindings. */
export function useWorkflowShellStyles(): void {
  useEffect(() => {
    if (document.getElementById(LINK_ID)) return;
    const link = document.createElement("link");
    link.id = LINK_ID;
    link.rel = "stylesheet";
    link.href = withBasePath("/workflow-shell.css");
    document.head.appendChild(link);
  }, []);
}
