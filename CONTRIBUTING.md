# Contributing

Contributions are welcome when they preserve the skill's evidence-first workflow and deterministic acceptance gates.

## Development setup

Fork or clone the repository, then install the pinned ELK dependency:

```bash
npm ci --prefix vendor/elk
```

Python 3.10 or newer is required. The Python tools otherwise use only the standard library.

## Making changes

- Keep `SKILL.md` at the repository root so the repository can be installed directly as a Codex skill.
- Treat the architecture IR as the semantic source of truth. Layout JSON and Draw.io XML are generated artifacts.
- Update the relevant reference contract when changing validation or compilation behavior.
- Preserve stable semantic IDs and deterministic output where possible.
- Keep model-specific claims, cell IDs, exceptions, and generated outputs outside this generic skill repository.
- Do not commit `node_modules`, Python caches, rendered test artifacts, or local project state.

Changes to topology, granularity, semantic projections, or delivery gates should include a focused regression test. Pure documentation changes do not require a new test.

## Validation

Run the test suite from the repository root:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

If your change affects ELK layout, first run:

```bash
npm ci --prefix vendor/elk
```

Validate the skill package when the Codex skill-creator tools are available:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" .
```

For rendering changes, also export a representative diagram with the official Draw.io CLI and inspect both the full view and detail regions. Automated geometry checks do not replace visual inspection.

## Pull requests

Describe the concrete diagram behavior that changed, the contract or source evidence behind it, and the commands used for validation. Include a small reproducible fixture for bug fixes when practical. Do not add model-specific examples unless they demonstrate a reusable compiler or contract behavior.
