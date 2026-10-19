<h1 align='center'>NeuroGhost</h1>

<h3 align='center'>A shared vocabulary for neuroscience data</h3>

<p align='center'><img width="500" height="500" alt="image" src="https://github.com/user-attachments/assets/e70a2916-acea-44bf-9f23-537f290d6f92" /></p>

---

**NeuroGhost** is an open registry of neuroscience data schemas. It brings the classes and properties of many schemas together in one place, shows where they share definitions, and records reviewed **mappings** between terms that mean the same (or related) things across projects.

Registered today: **AIND, BIDS, NWB, DANDI** (asset + dandiset), **openMINDS, BBQS, BICAN** (anatomical structures), **personinfo** and a slice of **schema.org** — see the **Sources** tab on the [website](https://sensein.group/NeuroGhost/).

> **Status: 0.1.0, alpha.** The registry, its identifiers and its workflows still change as the project grows.

---

## Browse — [sensein.group/NeuroGhost](https://sensein.group/NeuroGhost/)

- **Concepts** — every class and property, filterable by schema. For a property: each class that uses it, with the **rules** in effect there (range, required, pattern, unit; class-specific ones highlighted). For any entity: its stable **id**, its content **hash**, its **mappings** (status, method, who proposed and reviewed them) and what is **mapped from** other schemas — click either end to jump to it.
- **Diff** — compare two schemas class by class. **Query** — free-text search. **Graph Schema** — classes and how they connect.
- **Transform** — map one class's fields onto another's. **Compose** — pick classes and properties to export your own LinkML schema.
- **Sources** — the registered schemas, grouped into bundles (e.g. `dandi` = asset + dandiset). **Meta-model** — the registry's own data model.

---

## Add a schema

**From the website** — the **Ingest** tab: drop a **LinkML** (`.yml`) or **JSON Schema** (`.json`) file, add the optional metadata (bundle, homepage, publisher, …) and click **Open ingestion issue**. A GitHub Action validates it, checks the registry still builds, and opens a **pull request**; once a maintainer merges it, the registry rebuilds with the new schema.

**With an AI assistant** (Claude Code, in a clone of this repo) — ask, e.g., *"add my lab's schema"*. The [`ingest-schema`](.claude/skills/ingest-schema/SKILL.md) skill:
- takes LinkML, JSON Schema, Pydantic models, or a looser description (spreadsheet, data dictionary) that it drafts into LinkML with you;
- runs the same checks as the workflow, and **previews** what the schema adds — what's already in the registry (and will be shared), what shares a name but differs, what's new, what lacks descriptions;
- handles schemas that **import** others (it pins them with an `imports_source` annotation — see BICAN's in `registry_schemas/`) and the **bundle** they belong to;
- opens the PR for you, after asking. Use it for large schemas, which the website can't send.

---

## Map terms across schemas

Mappings live in [`mappings/`](mappings/README.md) as **mapping sets** — an SSSOM-style table (`<set>.sssom.tsv`, which GitHub shows as a table) plus its metadata (`<set>.sssom.yml`). Each row is one mapping, e.g. `dandiset:Dandiset  skos:closeMatch  schema.org:Dataset`, with a status: `PROPOSED`, `ACCEPTED`, `REJECTED` (kept as "not a match") or `SUPERSEDED`.

- **Free model, in CI** — Actions → **Propose Mappings** → pick a subject and an object schema (either can be *all*) and properties, classes or *all*. It opens a PR where every row is `PROPOSED`, scored by a local embedding model.
- **Your own model** — the [`propose-mappings`](.claude/skills/propose-mappings/SKILL.md) skill: your model judges candidates, **you approve each row**, and it opens a PR containing only what you approved, under your GitHub login. Its **review mode** does the same for an existing file, e.g. a *Propose Mappings* PR.
- **By hand** — write or edit a mapping set and open a PR; the *Mapping Check* validates it (to check it locally first, see [CONTRIBUTING.md](CONTRIBUTING.md)).

To **review** proposed mappings, set a row's `review_status` to `ACCEPTED` / `REJECTED` and `reviewer_id` to your GitHub login. The **Mapping Check** on the PR verifies the file, that every reference exists, and that each new review was made by an author of the PR. Merging rebuilds the registry, and the mappings appear on the website.

---

## Upstream updates

External schemas (BIDS, NWB, AIND, openMINDS, BBQS) are **not** updated automatically. Actions → **Fetch External Schemas** downloads the latest versions and opens a PR with the changed schema files, for review ([#118](https://github.com/sensein/NeuroGhost/issues/118) tracks whether to schedule it).

---

## Use it from tools

- **Data** — the whole registry is open JSON: [`data/registry.json`](data/registry.json) (classes, properties with their per-class rules, mappings, sources, bundles), with every past version in `data/versions/` and a changelog in `data/provenance.json`.
- **MCP server** — lets an AI assistant (Claude, Cursor, …) search classes, read alignments, diff schemas and translate records; run it from a clone of the repo (see [CONTRIBUTING.md](CONTRIBUTING.md#mcp-server)).

---

## How it works

- **One schema file per source** in [`registry_schemas/`](registry_schemas/), optionally with a `<name>_source.yaml` of metadata (bundle, homepage, version, …). JSON Schema is converted to LinkML; property names stay as the source wrote them.
- **Identity by content.** Every class and property gets a content **hash** (from its name, description and the hashes of what it references) and a stable **id** (a UUID kept across rebuilds). Identical content from two schemas is **one** entity, attested by both; changed content is a new entity. A property that means different things in different classes stays separate even when the name is shared.
- **Rules** (range, required, pattern, min/max, unit) are separate from identity, and scoped to a class where classes constrain a shared property differently.
- **Rebuild after merge.** Every merge that touches schemas, mappings or code triggers a rebuild that regenerates `data/` and publishes the website. Nothing downloads external schemas on its own.

More detail: [`docs/ingestion.md`](docs/ingestion.md), [`docs/model.md`](docs/model.md), [`mappings/README.md`](mappings/README.md).

---

## Contributing

**We're looking for suggestions and feedback.** NeuroGhost is early, and the most useful contributions right now are ideas: schemas you'd like to see, terms that should (or shouldn't) be matched, things on the website that are confusing or missing, workflows that don't fit how you work. [Open an issue](https://github.com/sensein/NeuroGhost/issues/new) — or start a discussion in one — with anything, however small.

Ways to contribute:

- **Add a schema** — your lab's, or one you use: see [Add a schema](#add-a-schema).
- **Propose or review mappings** — which terms mean the same thing across schemas: see [Map terms across schemas](#map-terms-across-schemas).
- **Review upstream updates** — check a *Fetch External Schemas* PR: see [Upstream updates](#upstream-updates).
- **Improve the code or the website** — see **[CONTRIBUTING.md](CONTRIBUTING.md)** for setting up, rebuilding the registry locally, tests, and notes on the meta-model and the website.

How changes land:

- **Everything goes through a pull request** to `main` and is reviewed before it's merged — schemas, mappings and code alike, including upstream updates and AI-proposed mappings (a person approves each mapping; `mapping_tool` records the model).
- **`data/` is generated, never edited by hand** — the rebuild after each merge writes it, so PRs carry only schema, mapping or code changes.
- **Mapping reviews are made in your own name** — the *Mapping Check* rejects an accept/reject whose `reviewer_id` isn't an author of the PR.
- **Meta-model changes need extra care** — `meta_model.yaml` defines identity and hashing for the whole registry; explain the change in the PR (details in [CONTRIBUTING.md](CONTRIBUTING.md#meta-model)).

**License:** CC0-1.0 — public domain.
