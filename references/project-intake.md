# Project intake and autonomous execution

For a new project, present one prefilled selection form before geometry. Use the
host's user-input controls when available; otherwise render the option table below.
Translate labels into the user's language. Do not replace the form with a prose
recommendation. Users can accept defaults, select alternatives, and supply extra
requirements in free text. Do not make them invent option names or module facts.

| Setting | Default | Available options |
| --- | --- | --- |
| Model target | Prefill from the request | Resolve materially different checkpoints |
| Execution | Autonomous completion | Autonomous / checkpointed |
| Delivery coverage | Whole model | Whole model / named modules |
| Algorithm presentation | Complete logical operators | Logical operators / module summary |
| Organization | Hierarchy overview with detail expansions | Hierarchy / continuous dataflow / paired |
| Delivery views (multiple) | Algorithm | Algorithm / Prefill / Decode / backend Runtime |
| Output files (multiple) | Draw.io, PNG, SVG | Draw.io / PNG / SVG |
| Extra requirements | Empty | Free text |

Follow [analysis-scope-contract.md](analysis-scope-contract.md). Canonical analysis
always includes the complete model algorithm, logical operators and state semantics
that affect computation. Inventory runtime extension boundaries; fully expand the
selected Prefill/Decode/backend views. Unselected physical implementation details
may remain independently reviewed inventory entries, without runtime graph regions.
Already materialized regions must still pass all audits. Do not invent unavailable
implementations. Runtime selection determines execution detail; it is not a second
algorithm-depth setting. Existing legacy intake retains its original full scope
until an explicitly authorized migration.

Whole model plus logical operators means every distinct non-atomic model module
family has a complete operator expansion, with repeated layers represented by
templates and counts. MLA/MoE are examples, never an implicit shortlist. Atomic
operators need no informationless child diagram. Reviewer must discover families
from source independently of Builder's list; machine checks cannot infer an
unrecorded family from source code alone.

Reviewer, source verification, validation and layout engine are internal required
steps, not user-selectable switches. Ask about remaining material ambiguities
together. An explicit instruction to start immediately or reuse confirmed choices
counts as confirmation: record that actual instruction and proceed without another
question. Silence and Builder's own suggestion are not confirmation.

## Record choices and derive delivery

Use the shared tool so UI/table defaults and machine validation agree:

```bash
python scripts/project_intake.py propose project-intake.json --model MODEL_ID
python scripts/project_intake.py show project-intake.json
python scripts/project_intake.py confirm project-intake.json --selection user-choices.json --source-ref USER_MESSAGE_ID --user-quote USER_CONFIRMATION
python scripts/project_intake.py plan project-intake.json --architecture architecture.json
```

The selection file contains only changed choice fields. Omit it to accept the
displayed defaults. Confirmation records one machine-checked intent: accepting
defaults, a non-empty custom selection, an explicit instruction to start
immediately, or reuse of confirmed choices. Ordinary task wording such as
"draw a detailed model diagram" is not confirmation and the CLI rejects it; the
agent must present the form and cite the subsequent response. Short responses
such as "yes", "OK", or their translated equivalent are accepted only as the
quoted response associated with that confirmation source. The agent records the
user's real response, never manufactures one. The host controls whether a popup
is available; this skill does not install a GUI or authenticate a click. The
confirmation digest detects subsequent edits, not identity forgery by another
process with the same file permissions.

Keep `project-intake.json` beside canonical `architecture.json`. Layout/compile
entrypoints and strict delivery/render gates reject absent, proposed, changed or
incompatible intake. For existing projects, reconstruct it from actual prior user
instructions; ask only if those instructions leave a material choice unresolved.

Canonical `request_contract`, `delivery_scope`, source inventory and view
dispositions remain complete and reviewed. Their module mappings describe the
available source-grounded expansions; never rewrite them to hide a failed
delivery view. `analysis_scope` binds reviewed extension boundaries in the IR.
The external intake selects among those views and is not part of
the canonical semantic digest. Adding an already reviewed delivery view reuses
the review. Adding missing operators, paths or a new canonical projection requires
updating the canonical ASCII and re-reviewing the changed semantics.

Inference view definitions declare `runtime_phases: ["prefill"]`, `["decode"]`
or both, based on source. The plan resolves user categories to declared view IDs.
An overview-only choice requires an actual canonical overview projection; it may
not export the detailed view and call it a summary. A combined prefill/decode view
is selected only when both phases are requested. Define phase-specific views when
the user requests just one phase.
Missing categories, empty views, missing module expansions and narrower canonical
coverage fail explicitly. Algorithm selections resolve algorithm-master/operator
views; backend selections resolve backend-runtime views. Runtime inference depth
comes from its complete reviewed paths, not the algorithm-depth dropdown.

Run the existing pipeline for every view in the plan, selecting it using
`--semantic-view VIEW_ID`. Run normal strict and official visual acceptance per
view, then verify all chosen views and formats were produced:

```bash
python scripts/project_intake.py check-files project-intake.json --architecture architecture.json --artifacts delivery-artifacts.json
```

The artifact JSON maps view IDs to format/path objects; paths are relative to
that JSON. File coverage is not a semantic, geometry or visual PASS. Never claim
the entire delivery complete after producing only one selected view.
Finish with `complete_project.py` as specified in
[completion-gate.md](completion-gate.md). It combines this exact selected-file
coverage with freshly verified per-view receipts and rejects substituted exports.

Interaction/recovery state stays in `project-state.json.execution_contract`:
mirror the confirmed mode, confirmation source and output formats there, with
explicit checkpoints only for checkpointed execution. The authoritative choices
are the intake file. A pipeline command finishing does not end the active task.

## Continue after internal failures

In autonomous mode, a failed stage means continue the repair loop:

1. Persist concrete findings and the next corrective action.
2. Repair invalid fields, missing operations, incorrect shapes, branches, or scope.
3. Regenerate ASCII and obtain a fresh independent review after semantic changes.
4. After semantic PASS, repair geometry, compile, audit, render, and inspect.
5. Finish only after acceptance for the confirmed scope or a real external blocker.

A pipeline nonzero exit ends that command, not the agent's task. Reviewer FAIL
and correctable static/render failures are internal feedback, not user checkpoints.
"I will repair this" must be followed by actions in the same active turn; do not
send it as a final answer while actionable work remains. Progress belongs in
commentary. After a Reviewer completes, read its result and continue immediately.
Use suitably sized agent waits and concise status updates instead of repeated
short polling or identical "waiting" messages.

After three non-improving attempts, change the repair strategy: cluster failures,
retrace the relevant source, rebuild an affected region, or revisit layout choices.
This is a replanning threshold, not a permission checkpoint or permission to lower
the acceptance criteria. Do not repeat an unchanged failing attempt indefinitely.

Pause only for a user decision required by conflicting evidence, an unresolved
target/scope ambiguity, unavailable required source/reviewer capabilities, actual
permissions, user-requested checkpoints, or a user stop. Exhaust safe in-scope
alternatives first. Report the concrete blocker, saved recovery state, and exactly
what external input is necessary. Keep unmet requirements explicit.

These are agent execution instructions and durable recovery records. A JSON field
cannot prevent the host from ending a turn; do not claim a Python gate automatically
orchestrates LLM repair/reviewer calls. The agent owns that continuation loop.
