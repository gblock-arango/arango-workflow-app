# Embeddings on Databricks (Autograph)

Autograph calls embeddings via workspace OAuth and the OpenAI-compatible API at `{workspace}/serving-endpoints`.

## What to use (2025+)

Databricks **no longer recommends** installing GTE/BGE from Marketplace. Those listings pointed at UC catalogs and GPU notebooks; that path is deprecated.

**Use instead:**

1. **Foundation Model API serving endpoints** (pay-per-token, instantly available under **Serving**), e.g. `databricks-bge-large-en`, `databricks-gte-large-en`.
2. Under the hood, models live in Unity Catalog as **`system.ai`** in your metastore. You do **not** call `system.ai.models.<name>` directly for Autograph — you call the **serving endpoint name** (same as the FM API endpoint id).

Autograph default:

```yaml
AUTOGRAPH_EMBEDDING_MODEL_NAME: "databricks-bge-large-en"
AUTOGRAPH_EMBEDDING_DIMENSION: "1024"
```

| Config / legacy alias | Serving endpoint | Dimensions |
|-----------------------|------------------|------------|
| `databricks-bge-large-en` (default) | same | 1024 |
| `bge_large_en_v1_5`, `baai/bge-large-en-v1.5` | → `databricks-bge-large-en` | 1024 |
| `databricks-gte-large-en` | same | 1024 |
| `gte_large_en_v1_5` | → `databricks-gte-large-en` | 1024 |

Docs: [supported foundation models](https://docs.databricks.com/en/machine-learning/foundation-model-apis/supported-models).

## Example

```python
from openai import OpenAI

client = OpenAI(
    api_key="<workspace-token>",
    base_url="https://<workspace-host>/serving-endpoints",
)
client.embeddings.create(input=["hello"], model="databricks-bge-large-en")
```

## App permissions

`app.yaml` declares `autograph-embedding-serving` with `CAN_QUERY` on the endpoint name. Grant on deploy via bundle resources + `scripts/grant_autograph_serving_permissions.py`.

```bash
databricks serving-endpoints get databricks-bge-large-en -o json
```

Then `/api/v1/system/llm-status?force=true` after redeploy.

## What not to use

- **Marketplace** GTE/BGE install notebooks and `{model}_marketplace` GPU endpoints — deprecated for this model family.
- **UC model paths** such as `system.ai.<model>` or old `databricks_bge_v1_5_models.models.*` as the `model` argument — Autograph needs the **serving endpoint name** only.

## BGE base / small

Foundation Model APIs expose **large** English BGE/GTE only. Smaller variants are not on the default pay-per-token endpoints; if your workspace exposes another serving endpoint for them, set `AUTOGRAPH_EMBEDDING_MODEL_NAME` to that exact name and match `AUTOGRAPH_EMBEDDING_DIMENSION`.

Changing model or dimension requires re-embedding all chunks and rebuilding the Faiss vector index.
