# SenseIn Schema Registry

Decentralized schema registry backed by **LadybugDB** (embedded property graph) + **FastAPI**.  
No Docker. No server. Just `pip install` and run.

## Install

```bash
pip install -r requirements.txt
# or manually:
pip install ladybug fastapi uvicorn rdflib httpx
```

## Run

```bash
uvicorn schema_registry:app --reload
```

First startup fetches and loads schema.org (~10 s). Persists to `./registry.lbug`.  
API docs: **http://localhost:8000/docs**

---

## Why LadybugDB instead of OxiGraph?

| | OxiGraph (old) | LadybugDB (new) |
|---|---|---|
| Model | RDF quads | Property Graph |
| Query | SPARQL | Cypher |
| Install | `pip install pyoxigraph` | `pip install ladybug` |
| Embedded | ✅ | ✅ |
| SPARQL | ✅ native | ❌ |
| RDF ingest | Native Turtle/JSON-LD | rdflib parse → Cypher insert |
| Analytics | Limited | Columnar, vectorized |
| Graph algorithms | ❌ | ✅ (PageRank, shortest path, etc.) |

All features are preserved. RDF ingestion still works — rdflib parses Turtle/JSON-LD, then the
triples are written into LadybugDB as `(SchemaNode)-[:TRIPLE]->(SchemaNode)` relationships.

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Node + triple counts |
| GET | `/schema/classes` | List all classes |
| GET | `/schema/class/{id}` | Get class (all versions) |
| POST | `/schema/class` | Create a class |
| GET | `/schema/property/{id}` | Get a property |
| POST | `/schema/property` | Create a property |
| POST | `/schema/rule` | Create a rule |
| POST | `/ingest` | Ingest RDF (Turtle or JSON-LD) |
| POST | `/schema/update/{id}` | Bump version (append-only) |
| GET | `/provenance/{id}` | PROV-O history |
| GET | `/schema/relations/{uri}` | All triples for a node |
| GET | `/distance/{id1}/{id2}` | Distance stub |

---

## Data Model

Triples are stored as:
```
(:SchemaNode)-[:TRIPLE {predicate: "rdfs:subClassOf"}]->(:SchemaNode)
(:SchemaNode)-[:TRIPLE_LIT {predicate: "rdfs:label"}]->(:Literal {value: "Person"})
```

Versions are **append-only** — bumping creates a new URI and links via `[:PRIOR_VERSION]`.  
Provenance uses `[:PROV_ACTIVITY {activity, agent, started_at}]` edges.

### Class fields
- `uri` — versioned URI: `registry.sensein.io/obj/{id}/v/{semver}`
- `object_id` — short id, e.g. "Person"
- `name`, `definition`, `version`, `created_at`
- Relations: `rdfs:subClassOf`, `reg:mixin`, `skos:broader`, `skos:related`

### Property fields
- Same core fields + domain class link (`rdfs:domain`)
- Constraints encoded in `definition`: dataType, units, min, max, pattern, multivalued, required

### Rule fields
- `rule_spec` stored as `definition` (Python expression or callable reference)
- `reg:appliesTo` edges to target object URIs

---

## Ingest example

```bash
curl -X POST http://localhost:8000/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "rdf_content": "@prefix ex: <https://example.org/> .\nex:Plant a <http://www.w3.org/2002/07/owl#Class> ;\n  <http://www.w3.org/2000/01/rdf-schema#label> \"Plant\" .",
    "mime_type": "text/turtle",
    "source_label": "bbqs-v1",
    "prov_agent": "researcher@sensein.io"
  }'
```

---

## Next steps
- BBQS schema ingestion (second RDF source)
- Users / Org / Roles node tables
- VOL sets (vocabulary/ontology/lookup)
- Transform objects
- Distance function (scientists to spec semantic + structural metric)
- LadybugDB Explorer UI for graph visualization
