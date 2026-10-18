---
name: propose-mappings
description: Propose cross-schema mappings for the NeuroGhost registry with your own model and open a PR containing only the mappings the user approved. Use when the user wants to map/align terms between two registered schemas (e.g. "map aind properties to bids", "find which dandiset classes match bbqs").
---

# Propose mappings (user-approved)

Produce a reviewed mapping file — `mappings/*.sssom.tsv`, format in
`neuro_ghost/mappings.py` — for two schemas already in the registry, judged by
you and **approved row by row by the user**, then open a PR with it. Every
row in the PR is a mapping the user accepted, recorded under their GitHub
login. Nothing is published until a maintainer merges the PR.

Work in batches and keep the user in control: you propose, they decide.

## 1. Set up

- Run from the repository root, on an up-to-date `main`
  (`git fetch upstream && git switch -c mappings/<short-name> upstream/main`, or
  `origin` if they work directly on sensein/NeuroGhost).
- `gh auth status` must show a logged-in account. Get the login with
  `gh api user --jq .login` — it is the `author_id` and `reviewer_id` of
  every row. Never type it in by hand or use anyone else's.
- Python with `requirements.txt` installed (the candidate step needs
  `sentence-transformers`).
- Ask which **subject** and **object** schemas (source labels as in
  `data/registry.json` → `sources[].label`, e.g. `aind`, `bids`, `asset`)
  and whether to map **properties** or **classes**. Suggest starting small
  (one pair of schemas, classes first, or a subset of classes).

## 2. Candidates

Generate candidates with the free embedding model into a scratch file, not
into `mappings/`:

```bash
python neuro_ghost/propose_mappings.py <subject> <object> --kind <properties|classes> \
  --top-k 3 --min-score 0.5 --author "$LOGIN" --out /tmp/candidates.sssom.tsv
```

These are only leads. You may also add a better target from the object
schema that embeddings missed — look it up in `data/registry.json`.

## 3. Judge (you)

For each subject entity, read both sides' names and definitions in
`data/registry.json` (and the class they belong to), then decide:

- `skos:exactMatch` — same meaning, interchangeable
- `skos:closeMatch` — nearly the same; fine for most data translation
- `skos:broadMatch` / `skos:narrowMatch` — the object is broader / narrower
- `skos:relatedMatch` — related, not substitutable
- none — not a match (drop it; don't show it unless asked)

Give each a confidence (0–1) and **one sentence** of reasoning. Be strict:
same name with different meaning (e.g. `description` of a Dandiset vs of
an Activity) is not a match.

## 4. Approve (the user)

Show **at most ~10 rows at a time** as a compact table:
`# · subject · relation · object · confidence · reason`. Ask the user to
answer per row: **accept**, **reject**, **change relation**, or **skip**
(e.g. "1-4 accept, 5 reject, 6 narrowMatch, rest skip"). Continue until
the candidates are done or the user stops. Never mark a row accepted
without their explicit answer.

Include only accepted rows in the file. Rejected rows are included only if
the user asks for that (as `REJECTED`, which records "this is not a match").

## 5. Write the mapping file

`mappings/<YYYY-MM-DD>_llm_<subject>__<object>_<kind>.sssom.tsv`:

```
# mapping_set_id: <file name without .sssom.tsv>
# mapping_date: <YYYY-MM-DD>
# mapping_tool: llm/<your exact model id>
# mapping_justification: semapv:ManualMappingCuration
# author_id: <login>
subject_id	predicate_id	object_id	confidence	review_status	reviewer_id	review_date	comment
aind:Subject.sex	skos:exactMatch	bids:Columns.sex	0.95	ACCEPTED	<login>	<YYYY-MM-DD>	<your one-sentence reason>
```

Tab-separated; references are `source:Class` or `source:Class.prop`
exactly as the candidates file wrote them. Then validate:

```bash
python neuro_ghost/mappings.py validate mappings/<file>
```

Fix anything it reports before going on.

## 6. Open the PR — ask first

Show the user a summary (counts, the file path) and **ask before**
committing, pushing, or opening the PR. Then:

```bash
git add mappings/<file>
git commit -m "Mappings: <subject> → <object> (<kind>), approved by <login>"
git push -u origin <branch>
gh pr create --base main --title "Mappings: <subject> → <object> (<kind>)" --body "<summary: how many, method llm/<model>, all approved by <login>>"
```

(From a fork: `--repo sensein/NeuroGhost --head <login>:<branch>`.)

The PR's **Mapping Check** verifies the file, that every reference exists,
and that every accepted/rejected row names an author of the PR as reviewer.
