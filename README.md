# Model Sketcher

`model-sketcher` is a Codex skill for producing dense, editable model and code-path architecture diagrams. It treats diagrams as compiled engineering artifacts: source evidence becomes a semantic architecture IR, the IR becomes a reviewed topology contract, and deterministic layout produces an editable Draw.io file.

The skill is designed for source-level model analysis rather than generic presentation graphics. Its compact technical-analysis visual language is model- and framework-agnostic. It can produce a hierarchy master, a continuous end-to-end dataflow view, or a paired delivery derived from the same canonical model.

## What it provides

- Evidence-first architecture modeling with explicit source and configuration claims
- Separate model-algorithm, inference-execution, and backend-implementation projections
- Logical operator diagrams that preserve tensor operations even when kernels are fused
- Generated ASCII topology contracts for review before geometry is created
- An independent, digest-bound topology review gate
- Native and ELK-based deterministic layout
- Compound ELK routing for ordinary cross-region edges, with explicit routing coverage metadata
- Editable Draw.io compilation
- Static delivery audits and rendered SVG checks
- Incremental layout and focused local-revision workflows

## Requirements

- Python 3.10 or newer
- Node.js 18 or newer for the ELK layout engine
- The Draw.io desktop CLI for official rendering and final visual acceptance

The Python tools use only the standard library. Draw.io is optional for semantic validation, layout tests, and most development work, but it is required before a diagram can claim final visual acceptance.

## Installation

Clone the repository directly into your Codex skills directory. The pinned ELK runtime is included, so the standard installation does not require an npm download:

```bash
git clone git@github.com:Shenjiyang/Model-sketcher.git "${CODEX_HOME:-$HOME/.codex}/skills/model-sketcher"
```

If the bundled runtime is missing or must be restored, reinstall the same pinned version with:

```bash
npm ci --prefix "${CODEX_HOME:-$HOME/.codex}/skills/model-sketcher/vendor/elk"
```

Restart Codex if it was already running. Invoke the skill by name:

```text
$model-sketcher
```

For example:

```text
Use $model-sketcher to create a paired hierarchy and end-to-end
operator view for this model. Ground every operation in the supplied source tree.
```

## Workflow

Start by reading [`SKILL.md`](SKILL.md) and [`references/compiler-workflow.md`](references/compiler-workflow.md). The standard compiler path is:

1. Copy `assets/architecture-ir-template.json` into a project directory.
2. Record the requested delivery scope, source evidence, operations, tensor shapes, semantic views, and operator sequences.
3. Validate the architecture IR.
4. Generate the ASCII topology contract and complete an independent topology review.
5. Run deterministic native or ELK layout.
6. Compile the editable `.drawio` document and its audit manifest.
7. Run strict delivery checks, export through Draw.io, and inspect the rendered result.

Validate an architecture IR before layout:

```bash
python3 scripts/validate_architecture_ir.py path/to/architecture.json
```

Run the gated compiler pipeline after the independent review artifact exists:

```bash
python3 scripts/run_compiler_pipeline.py path/to/architecture.json \
  --layout path/to/layout.json \
  --topology-contract path/to/topology.contract.txt \
  --topology-review path/to/topology-review.json \
  --drawio path/to/model.drawio \
  --audit-manifest path/to/model.audit.json \
  --layout-engine elk
```

The pipeline deliberately stops at the topology-review gate when a valid independent review is absent. See [`references/topology-review-workflow.md`](references/topology-review-workflow.md) for the review procedure and [`references/strict-delivery-contract.md`](references/strict-delivery-contract.md) for final acceptance requirements.

`--layout-engine elk` automatically uses compound ELK when ordinary edges cross
regions; `--layout-engine elk-compound` requests it explicitly. It does not fall
back to native routing. Compound layout currently requires full reflow and is
still undergoing real-model quality validation; successful generation is not
visual acceptance. See the layout adapter reference for limitations and results.

## Repository layout

| Path | Purpose |
| --- | --- |
| `SKILL.md` | Skill trigger, operating rules, workflow, and acceptance criteria |
| `agents/openai.yaml` | Codex skill metadata |
| `assets/` | Architecture IR, project-state, audit, and layout examples |
| `references/` | Compiler, topology, layout, rendering, and visual-style contracts |
| `scripts/` | Validators, planners, compiler, renderer, and audit tools |
| `tests/` | Standard-library `unittest` suite |
| `vendor/elk/` | Bundled offline ELK runtime plus pinned npm recovery metadata |

## Development

The bundled runtime is sufficient for tests and normal use. To refresh it during dependency maintenance, install the pinned package, update `vendor/elk/runtime/` from that exact version, and then run the complete test suite:

```bash
npm ci --prefix vendor/elk
python3 -m unittest discover -s tests -p 'test_*.py'
```

Run the skill package validator if the Codex system skills are installed locally:

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" .
```

See [`CONTRIBUTING.md`](CONTRIBUTING.md) before changing contracts, compiler behavior, or diagram acceptance rules.

## License

This project is available under the [MIT License](LICENSE).
