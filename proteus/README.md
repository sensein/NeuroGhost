# proteus

Alignment computation for the PROTEUS schema registry: proposes SSSOM mappings
between registered schemas. See `CLAUDE.md` for architecture and invariants,
`docs/IMPLEMENTATION_PLAN.md` for build order (currently: Milestone 1 vertical
slice implemented, later stages stubbed).

```bash
pip install -e ".[dev]"
pytest
python -m proteus.pipeline tests/fixtures/schema_a.yaml tests/fixtures/schema_b.yaml out.sssom.tsv
```
