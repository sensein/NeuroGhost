# Mappings

Reviewed cross-schema correspondences — "`aind:Subject.sex` is a close match
for `bids:Columns.sex`" — one file per mapping run, merged through PRs. The
registry rebuild loads every `*.sssom.tsv` here into `Mapping` records
(`neuro_ghost/mappings.py`), and the website shows them on each class and
property with their status, method and who proposed / reviewed them.

## Format

SSSOM-style TSV with a `# key: value` header whose values are defaults for
every row:

```
# mapping_set_id: 2026-10-18_embeddings_asset__bbqs_properties
# mapping_date: 2026-10-18
# mapping_tool: embeddings/all-MiniLM-L6-v2
# mapping_justification: semapv:SemanticSimilarityThresholdMatching
# author_id: github-actions
subject_id	predicate_id	object_id	confidence	review_status	reviewer_id	review_date	comment
asset:Person.identifier	skos:closeMatch	bbqs:Investigator.orcid	0.723	PROPOSED
```

- `subject_id` / `object_id`: `source:Class` or `source:Class.prop` (source
  labels as in `data/registry.json`).
- `predicate_id`: `skos:exactMatch`, `skos:closeMatch`, `skos:broadMatch`,
  `skos:narrowMatch`, `skos:relatedMatch`, `owl:equivalentClass`.
- `review_status`: `PROPOSED`, `ACCEPTED`, `REJECTED` (kept as "not a
  match"), `SUPERSEDED`. Accepting or rejecting needs `reviewer_id`.

## Adding mappings

- **Free model, in CI** — run the *Propose Mappings* workflow (Actions tab)
  with two schemas; it opens a PR where every row is `PROPOSED`.
- **Your own model** — in Claude Code, use the `propose-mappings` skill
  (`.claude/skills/`): your model judges candidates, you approve each row,
  and it opens a PR containing only what you approved.
- **By hand** — write or edit a file and open a PR; check it locally with
  `python neuro_ghost/mappings.py validate mappings/<file>`.

To review mappings, change a row's `review_status` and set `reviewer_id` to
your GitHub login. The *Mapping Check* on the PR verifies the file, that every
reference exists, and that each new review is made by an author of the PR.
