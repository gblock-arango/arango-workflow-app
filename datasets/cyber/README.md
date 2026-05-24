# Synthetic Fraud/Cyber Graph Dataset

Small graph fixture for testing graph databases, JSON-LD ingestion, ArangoDB import flows, GraphRAG demos, GraphSAGE/heterogeneous graphlet experiments, and fraud/cyber event-recognition queries.

## Contents

| File | Purpose |
|---|---|
| `fraud_cyber_ontology_annotated.jsonld` | JSON-LD ontology (seeded to `builtin/ontologies/cyber/`). |
| `fraud_cyber_dataset.json` | Combined graph JSON / instance data (seeded to `builtin/instance_data/cyber/`). |
| `combined_graph.json` | Single JSON file with all collections and metadata. |
| `accounts.json/csv` | 30 account vertices. |
| `transactions.json/csv` | 100 transaction vertices. |
| `devices.json/csv` | 10 device vertices. |
| `ips.json/csv` | 20 IP address vertices. |
| `attack_patterns.json/csv` | 5 attack/fraud pattern vertices. |
| `fraud_signals.json/csv` | 19 generated alert/signal vertices. |
| `edges.json/csv` | 371 graph edges using Arango-style `_from` / `_to`. |

## Graph model

Vertex collections:

- `accounts`
- `transactions`
- `devices`
- `ips`
- `attack_patterns`
- `fraud_signals`

Edge predicates:

- `initiated`: account -> transaction
- `usedDevice`: transaction -> device
- `originatedFrom`: transaction -> IP address
- `matchesPattern`: transaction -> attack pattern
- `triggeredSignal`: transaction -> fraud signal
- `hasUsedDevice`: account -> device
- `hasUsedIP`: account -> IP address

## Example ArangoDB imports

```bash
arangoimport --collection accounts --type json --file accounts.json --create-collection true
arangoimport --collection transactions --type json --file transactions.json --create-collection true
arangoimport --collection devices --type json --file devices.json --create-collection true
arangoimport --collection ips --type json --file ips.json --create-collection true
arangoimport --collection attack_patterns --type json --file attack_patterns.json --create-collection true
arangoimport --collection fraud_signals --type json --file fraud_signals.json --create-collection true
arangoimport --collection edges --type json --file edges.json --create-collection true --create-collection-type edge
```

## Example AQL queries

High-risk transactions with matched patterns:

```aql
FOR t IN transactions
  FILTER t.isFraud == true
  FOR v, e, p IN 1..1 OUTBOUND t edges
    FILTER e.predicate == "matchesPattern"
    RETURN { transaction: t.transactionId, amount: t.amount, pattern: v.name, confidence: e.confidence }
```

Accounts sharing high-risk IP infrastructure:

```aql
FOR ip IN ips
  FILTER ip.threatScore > 0.65
  LET accountsUsingIp = (
    FOR v, e IN 1..1 INBOUND ip edges
      FILTER e.predicate IN ["hasUsedIP", "originatedFrom"]
      RETURN DISTINCT v._id
  )
  FILTER LENGTH(accountsUsingIp) >= 3
  RETURN { ip: ip.ipAddress, threatScore: ip.threatScore, accounts: accountsUsingIp }
```

Graphlet around one suspicious transaction:

```aql
FOR t IN transactions
  FILTER t.isFraud == true
  LIMIT 1
  FOR v, e, p IN 1..2 ANY t edges
    RETURN p
```

## Notes

This dataset is synthetic and uses documentation-reserved IP space (`203.0.113.0/24`). It is suitable for demos and local testing, not for model evaluation claims.


## Natural-language annotations

Every vertex and edge document includes an `annotation` property. This field is intended for GraphRAG grounding, analyst-facing explanations, semantic search, and quick inspection in ArangoDB.

Examples:

```aql
FOR t IN transactions
  FILTER t.isFraud == true
  RETURN { transaction: t._key, annotation: t.annotation }
```

```aql
FOR e IN edges
  FILTER e.predicate == "matchesPattern"
  RETURN { edge: e._key, from: e._from, to: e._to, annotation: e.annotation }
```
