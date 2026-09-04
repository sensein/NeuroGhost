# NeuroGhost Ecosystem Governance

> **Status: Provisional** — This document tracks the satellite modules that
> feed into or extend the NeuroGhost registry. It is a living spec; entries
> are added as modules are formally onboarded.
> **The page needs updates!**

---

## Overview

NeuroGhost core (`sensein/NeuroGhost`) is the central registry and MCP server.
Around it sit independently maintained **satellite modules** — separate
repositories owned by their respective teams — that contribute schemas,
alignment pipelines, or tooling back into the core.

Each satellite module is self-governing: it sets its own release cadence,
internal review process, and roadmap. Integration into NeuroGhost core
happens exclusively through pull requests, and every such PR requires
**exactly one approval from the designated NeuroGhost approver** for that
module before merging.

```
 ┌──────────────────────────────────────────────────┐
 │                 sensein/NeuroGhost               │
 │                    (core registry)               │
 └────────────┬─────────────────────────────────────┘
              │                    │
       PR approval           PR approval
              │                    │
   ┌──────────▼──────┐   ┌────────▼────────────┐
   │    Proteus      │   │   search_hybrid      │
   │ (neurovium)     │   │  (sensein)           │
   └─────────────────┘   └──────────────────────┘
```

---

## Satellite Module Registry

| Module | Repository | Maintainer | Focus | Status | NeuroGhost Approver |
|--------|-----------|------------|-------|--------|---------------------|
| **Proteus** | [neurovium/Proteus](https://github.com/neurovium/Proteus) | @neurovium (Nema) | Cross-schema alignment pipeline | Provisional | @Sulstice |
| **search_hybrid** | [sensein/search_hybrid](https://github.com/sensein/search_hybrid) | @sensein | Hybrid search & retrieval tooling | Provisional | @Sulstice |

> **Provisional** means the module is tracked here but has no formal SLA yet.
> **Active** means the module has merged at least one PR into core and follows
> this spec. **Archived** means the module is no longer maintained.

---

## Contribution Workflow

### From a satellite module into NeuroGhost core

1. **Work happens in the satellite repo.** The module team develops, tests,
   and reviews changes internally before proposing them to core.

2. **Open a PR against `sensein/NeuroGhost` `main`.** The PR description must
   identify which satellite module it comes from and link the corresponding
   work in the satellite repo.

3. **One approval required.** The designated NeuroGhost approver for that
   module reviews and approves the PR. No other approvals are required, but
   any NeuroGhost maintainer may comment.

4. **CI must pass.** All existing tests, the schema validation workflow, and
   (where applicable) the registry rebuild must be green before merging.

5. **Squash or merge — no rebases onto main.** The merge method is merge
   commit so the satellite module's authorship is visible in `git log`.

### Reverting satellite contributions

If a satellite PR is merged prematurely or introduces a regression, any
NeuroGhost core maintainer may open a revert PR without waiting for the
satellite module's approval. The revert is merged as soon as one core
maintainer approves it.

---

## Adding a New Satellite Module

To register a new module:

1. Open a PR that adds a row to the table above with the module name,
   repository URL, maintainer GitHub username, and a one-line focus summary.
2. Set `Status` to **Provisional**.
3. Designate a NeuroGhost approver (defaults to `@Sulstice`).
4. The PR is merged by any NeuroGhost core maintainer.

---

## Core Maintainers

| Name | GitHub | Role |
|------|--------|------|
| Suliman | @Sulstice | Lead maintainer, final approver |
| Puja Trivedi | @puja-trivedi | Core contributor; meta-model moderator |
| Dorota Jarecka | @djarecka | Meta-model moderator |

### Meta-model Moderation

Changes to `meta_model.yaml` and `schema_registry_utils/` require
approval from at least one **meta-model moderator** before merging:

| Moderator | GitHub |
|-----------|--------|
| Puja Trivedi | @puja-trivedi |
| Dorota Jarecka | @djarecka |

This covers any PR that modifies the LinkML meta-model schema, the generated
Pydantic models, the hashing logic, or the graph DDL derived from the
meta-model.

---

## Updating This Document

This document lives at `docs/GOVERNANCE.md`. Changes to the satellite module
table or approver assignments require a PR approved by `@Sulstice`.
