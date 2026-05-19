/** Stable widget ids for workspace tabs and dock panels. */
export const WIDGET_IDS = {
  assetsDock: "assets-dock",
  genieChatDock: "genie-chat-dock",
  ontologyGraph: "ontology-graph",
} as const;

export type WidgetTabId = (typeof WIDGET_IDS)["ontologyGraph"];
