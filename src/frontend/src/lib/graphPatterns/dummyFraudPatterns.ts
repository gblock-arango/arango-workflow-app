import type { GraphPattern } from "@/types/graphPattern";

/**
 * Three illustrative GraphPatterns grounded in
 * `datasets/fraud_cyber_graph_dataset_with_annotations`.
 */
export const DUMMY_GRAPH_PATTERNS: GraphPattern[] = [
  {
    id: "gp_account_takeover_t004",
    name: "Account takeover — new device + hostile IP",
    description:
      "Graphlet around transaction T004 ($8,091 POS electronics): account A029 initiated payment from new device D009 via hostile IP003 (threat score 0.9). Matches synthetic-identity attack pattern and triggered fraud signal S001 with high risk score 0.99. Witnessed in Gold CDC and knowledge graph; embedding stored for similarity search.",
    threatType: "Account Takeover",
    severity: "high",
    adaptiveCdc: {
      online: true,
      status: "online",
      jobName: "fraud_cyber_gold_cdc",
      lastRun: "2026-05-18T14:22:00Z",
    },
    features: {
      timesObserved: 47,
      missingLinkObserved: false,
      embeddingInVectorStore: true,
      goldTableCdcWitnessed: true,
      knowledgeGraphWitnessed: true,
      lastSeen: "2026-05-18T11:04:00Z",
    },
    persisted: true,
    nodes: [
      { id: "accounts/A029", label: "A029", collection: "accounts" },
      { id: "transactions/T004", label: "T004", collection: "transactions" },
      { id: "devices/D009", label: "D009", collection: "devices" },
      { id: "ips/IP003", label: "IP003", collection: "ips" },
      { id: "attack_patterns/synthetic-identity", label: "synthetic-id", collection: "attack_patterns" },
      { id: "fraud_signals/S001", label: "S001", collection: "fraud_signals" },
    ],
    edges: [
      { from: "accounts/A029", to: "transactions/T004", predicate: "initiated" },
      { from: "transactions/T004", to: "devices/D009", predicate: "usedDevice" },
      { from: "transactions/T004", to: "ips/IP003", predicate: "originatedFrom" },
      { from: "transactions/T004", to: "attack_patterns/synthetic-identity", predicate: "matchesPattern" },
      { from: "transactions/T004", to: "fraud_signals/S001", predicate: "triggeredSignal" },
    ],
  },
  {
    id: "gp_mule_ring_t005",
    name: "Mule ring — shared IP fan-in",
    description:
      "Transaction T005 ($5,894 POS travel) from A029 shares IP003 with mule account A006 via hasUsedIP, matching mule-ring attack pattern on device D010. Gold CDC captured edges E015–E018; one expected fan-in link is missing from the live graph snapshot. Re-observed 23 times in the last 7 days.",
    threatType: "Money Mule Ring",
    severity: "medium",
    adaptiveCdc: {
      online: true,
      status: "syncing",
      jobName: "fraud_cyber_gold_cdc",
      lastRun: "2026-05-18T14:05:00Z",
    },
    features: {
      timesObserved: 23,
      missingLinkObserved: true,
      embeddingInVectorStore: true,
      goldTableCdcWitnessed: true,
      knowledgeGraphWitnessed: true,
      lastSeen: "2026-05-18T10:41:00Z",
    },
    persisted: false,
    nodes: [
      { id: "accounts/A029", label: "A029", collection: "accounts" },
      { id: "transactions/T005", label: "T005", collection: "transactions" },
      { id: "devices/D010", label: "D010", collection: "devices" },
      { id: "ips/IP003", label: "IP003", collection: "ips" },
      { id: "attack_patterns/mule-ring", label: "mule-ring", collection: "attack_patterns" },
      { id: "accounts/A006", label: "A006", collection: "accounts" },
    ],
    edges: [
      { from: "accounts/A029", to: "transactions/T005", predicate: "initiated" },
      { from: "transactions/T005", to: "devices/D010", predicate: "usedDevice" },
      { from: "transactions/T005", to: "ips/IP003", predicate: "originatedFrom" },
      { from: "transactions/T005", to: "attack_patterns/mule-ring", predicate: "matchesPattern" },
      { from: "accounts/A006", to: "ips/IP003", predicate: "hasUsedIP" },
    ],
  },
  {
    id: "gp_card_testing_probe",
    name: "Card testing — low-value probe chain",
    description:
      "Probe chain on account A013: rapid low-value authorizations T002 and T003 through device D005 before escalation. T003 matches card-testing pattern and triggered signal S012. Gold CDC shows the transactions; knowledge-graph promotion is incomplete and vector embedding is absent for the pattern hop.",
    threatType: "Card Testing",
    severity: "low",
    adaptiveCdc: {
      online: false,
      status: "offline",
      jobName: "fraud_cyber_gold_cdc",
    },
    features: {
      timesObserved: 9,
      missingLinkObserved: true,
      embeddingInVectorStore: false,
      goldTableCdcWitnessed: true,
      knowledgeGraphWitnessed: false,
      lastSeen: "2026-05-17T22:15:00Z",
    },
    persisted: false,
    nodes: [
      { id: "accounts/A013", label: "A013", collection: "accounts" },
      { id: "transactions/T002", label: "T002", collection: "transactions" },
      { id: "transactions/T003", label: "T003", collection: "transactions" },
      { id: "devices/D005", label: "D005", collection: "devices" },
      { id: "attack_patterns/card-testing", label: "card-test", collection: "attack_patterns" },
      { id: "fraud_signals/S012", label: "S012", collection: "fraud_signals" },
    ],
    edges: [
      { from: "accounts/A013", to: "transactions/T002", predicate: "initiated" },
      { from: "accounts/A013", to: "transactions/T003", predicate: "initiated" },
      { from: "transactions/T002", to: "devices/D005", predicate: "usedDevice" },
      { from: "transactions/T003", to: "attack_patterns/card-testing", predicate: "matchesPattern" },
      { from: "transactions/T003", to: "fraud_signals/S012", predicate: "triggeredSignal" },
    ],
  },
];
