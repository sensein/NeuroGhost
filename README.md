<h1 align='center'>NeuroGhost</p>

<h3 align='center'>A shared vocabulary for neuroscience data</h3>

<p align='center'><img width="500" height="500" alt="image" src="https://github.com/user-attachments/assets/e70a2916-acea-44bf-9f23-537f290d6f92" /></p>

---

**NeuroGhost** is a public catalog of neuroscience vocabularies. Labs publish their [LinkML](https://linkml.io/) schema; the registry compares it to every other schema and surfaces which terms mean the same thing across projects.

**Distance score** — 0.0 = identical, 1.0 = unrelated. Computed via the Proteus pipeline: name similarity, token Jaccard, alias overlap, definition embeddings, IRI anchor, and unit dimensional veto. Adjustable live on the Concepts page.

---

## By the Numbers

| Stat | Value |
|------|-------|
| Schemas registered | **7** — aind · bids · nwb · bbqs · dandi · openminds · personinfo |
| Classes catalogued | **671** across all schemas |
| Properties indexed | **~3,800** content-addressed nodes |
| Alignment edges | **56** across 28 classes · mean distance **0.17** |
| Alignment methods | IRI anchor 77% · semantic-name 14% · composite 9% |
| Confidence floor | **0.45** — pairs below this threshold are dropped |
| `skos:exactMatch` threshold | **0.95** — IRI anchor + unit compatibility required |

---

## Roadmap

**MVP (Sep 29):** BBQS and DANDI aligned, transform API live, users can sign up. Full public launch with BrainKB on Oct 23.

| # | Date | Milestone | Owners | Issue |
|---|------|-----------|--------|-------|
| M1 | Aug 28 | Foundation — modules, meta-model v1, BICAN ingested, cloud deploy | @neurovium · @puja-trivedi · @djarecka · @Sulstice | [#56](https://github.com/sensein/NeuroGhost/issues/56) |
| M2 | Sep 11 | Alignment consolidated, DANDI ingested, schema strategy | @neurovium · @djarecka · @Sulstice | [#57](https://github.com/sensein/NeuroGhost/issues/57) |
| M3 | Sep 29 | **MVP soft launch** — users can sign up | @Sulstice + team | [#58](https://github.com/sensein/NeuroGhost/issues/58) |
| M4 | Oct 23 | Full public launch with BrainKB | @Sulstice + team | [#59](https://github.com/sensein/NeuroGhost/issues/59) |

---

## Website

**[sensein.group/NeuroGhost](https://sensein.group/NeuroGhost/)** — nine tabs, all client-side, no framework:

| Tab | What it does |
|-----|--------------|
| **Meta-model** | Interactive class diagram of the 14 registry types (`RegistryEntity`, `RegistryClass`, `Mapping`, `ProvenanceEntry`, …) with `is_a` and named-relationship edges. Fuzzy search over class names, tags, definitions, and slot names — matches highlight on the canvas and open the side panel. |
| **Concepts** | Browse all 677 registered classes with a source filter, a name/definition search, and a per-class detail panel showing IRI, definition, properties, and alignments. Four **live weight sliders** — `iri` / `name` / `desc` / `slot` — re-rank each class's alignments by a composite similarity you tune on the fly. |
| **Diff** | Pick two schemas from the pickers and see matched pairs, only-in-A, and only-in-B. Matching passes: exact name → alignment edge A→B → alignment edge B→A. Every matched pair carries a **slot-level delta** — shared / added / removed — expandable to the actual property names. |
| **Graph Schema** | Force-directed content graph — every registered class as a node (colored by source), every alignment edge as a link (colored by method, width scaled by `1 − distance`). Scope toggle (Aligned / All 677), method chips with inline **descriptions of each alignment method**, per-schema on/off, drag / zoom / pan, and a side detail panel per node. |
| **Transform** | Pick a source class in one schema and a target class in another; get a **field-mapping table** with `auto` / `heuristic` / `unmapped` status per property, a coverage bar, and a class-level alignment badge showing the pipeline method and distance when one applies. |
| **Query** | Cross-registry free-text search over class names, property names, definitions, and IRIs. Kind chips (Classes / Properties / IRIs) with live counts, source facets, and a right-hand detail panel per hit. IRI hits aggregate every class under the same anchor. |
| **Provenance** | Timeline of every registry version — 18 entries to date — with a W3C-PROV record per bump (`activity`, `attributed_to`, `generated_at`, `derived_from`, `issue`, `archive`) and green/red class-count deltas against the previous version. |
| **Compose** | **Build your own LinkML schema** by picking classes from the registry. Every picked class expands into a chip row of its own properties — toggle each slot on/off (with All / None quick-buttons per class) to control exactly what ends up in the export. Emits a valid LinkML YAML with `class_uri`, `slot_uri`, `range`, `unit.ucum_code`, and deduplicated slots that only get top-level definitions when at least one picked class still keeps them. One-click **Copy YAML** or **Download .yml**. |
| **Ingest** (Register) | Submit a new schema via file drop, file browse, or paste. Parses the YAML client-side, previews it, and opens a pre-filled GitHub issue that triggers the CI pipeline to validate, ingest, align, and archive it. |

---

## Adding a schema

1. Write a LinkML `.yml` file (copy `registry_schemas/bbqs.yml` as a template).
2. Go to the **Ingest** tab of the [website](https://sensein.group/NeuroGhost/), drop the file, browse to it, or paste the YAML directly, then click **Open ingestion issue**.
3. A GitHub Action validates, ingests, aligns, and archives it within minutes.

No installation, no pull request, no reviewers required.

---

## Running locally

```bash
git clone https://github.com/sensein/NeuroGhost.git
cd NeuroGhost
pip install -r requirements.txt
```

```bash
python neuro_ghost/pipeline.py --fresh                              # full rebuild
python neuro_ghost/pipeline.py --fresh --skip-converters            # local schemas only
python neuro_ghost/pipeline.py --skip-converters --schemas registry_schemas/bbqs.yml  # one schema
```

Options: `--fresh` (wipe DB), `--skip-converters` (skip BIDS/NWB/DANDI/openMINDS/AIND fetch), `--schemas FILE`, `--bump major|minor|patch`, `--agent TEXT`.

Open `index.html` in a browser when done.

To inspect a single schema without running the full pipeline:

```bash
python neuro_ghost/ingest_linkml.py --file registry_schemas/bbqs.yml --dry-run --verbose
```

`--dry-run` parses and reports counts without writing to the DB; `--verbose` additionally prints every `RegistryClass`/`RegistryProperty`/`RegistryValueSet`/`ProvenanceEntry` that would be created, in full.

---

## Stack

- **[LadybugDB](https://ladybugdb.com/)** — embedded graph DB, no server
- **[LinkML](https://linkml.io/)** — schema format
- **[sentence-transformers](https://sbert.net/)** — `all-MiniLM-L6-v2` for semantic distance
- **Static HTML + GitHub Pages** — one-file frontend, no framework
- **GitHub Actions** — CI/CD on every schema submission

---

## Satellite Modules

NeuroGhost core is extended by independently maintained satellite modules.
Each module lives in its own repository and contributes back via pull
requests; every PR from a satellite module requires one approval from the
designated NeuroGhost approver before merging.
See [docs/GOVERNANCE.md](docs/GOVERNANCE.md) for the full spec.

### Module sync status

> **Proteus**: commits ahead of the version pinned into `neuro_ghost/align.py` (see `.proteus-pin`).
> **search_hybrid**: commits behind `sensein/NeuroGhost` main.
> Updated automatically by CI on every push to main.

<!-- MODULE_SYNC_START -->
| Module | Maintainer | Repository | Behind main | Compare |
|--------|-----------|------------|-------------|---------|
| Proteus | @neurovium (Nema) | [neurovium/Proteus](https://github.com/neurovium/Proteus) | ⚠ pin unset | [compare ↗](https://github.com/neurovium/Proteus/commits/main) |
| Dorada | @djarecka | [djarecka/NeuroGhost](https://github.com/djarecka/NeuroGhost) | 147 commits | [compare ↗](https://github.com/sensein/NeuroGhost/compare/main...djarecka:NeuroGhost:main) |
<!-- MODULE_SYNC_END -->

---

## Contributing

- Register a schema via the [Register tab](https://sensein.group/NeuroGhost/).
- [Open an issue](https://github.com/sensein/NeuroGhost/issues/new) to report bugs or suggest features.
- PRs welcome, especially around the distance function.

**License:** CC0-1.0 — public domain.
