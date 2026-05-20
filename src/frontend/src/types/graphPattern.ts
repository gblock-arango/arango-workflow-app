/** Severity for a discovered graphlet / GraphPattern threat classification. */
export type GraphPatternSeverity = "low" | "medium" | "high";

export type AdaptiveCdcOnlineStatus = "online" | "offline" | "degraded" | "syncing";

export interface GraphPatternNode {
  id: string;
  label: string;
  /** Medallion / Arango vertex collection (accounts, transactions, …). */
  collection: string;
}

export interface GraphPatternEdge {
  from: string;
  to: string;
  predicate: string;
}

export interface GraphPatternFeatures {
  timesObserved: number;
  missingLinkObserved: boolean;
  embeddingInVectorStore: boolean;
  goldTableCdcWitnessed: boolean;
  knowledgeGraphWitnessed: boolean;
  lastSeen: string;
}

export interface GraphPatternAdaptiveCdc {
  online: boolean;
  status: AdaptiveCdcOnlineStatus;
  jobName?: string;
  lastRun?: string;
}

export interface GraphPattern {
  id: string;
  name: string;
  description: string;
  threatType: string;
  severity: GraphPatternSeverity;
  adaptiveCdc: GraphPatternAdaptiveCdc;
  features: GraphPatternFeatures;
  nodes: GraphPatternNode[];
  edges: GraphPatternEdge[];
  persisted: boolean;
}
