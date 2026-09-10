# Project intake and autonomous execution

For a new project with no confirmed configuration, present this short table once.
Prefill information already supplied by the user. Defaults are proposals until
confirmed, except when the user explicitly asks to start immediately or reuse a
known preset. In that case announce the resolved configuration and proceed.

| Setting | Proposed default | Alternatives |
| --- | --- | --- |
| Model target | Requested model; verify exact checkpoint | Clarify materially different variants |
| Execution | Autonomous completion | Checkpointed collaboration |
| Semantic views | Model algorithm | Inference execution, backend implementation, or combination |
| Coverage | Whole model | Named modules |
| Depth | Logical operators | Module summary or implementation detail |
| Organization | Hierarchy master | Continuous dataflow or paired output |
| Files | Editable Draw.io, PNG, SVG | User-selected formats |

The user may reply "use defaults" or change only selected rows. Batch remaining
material ambiguities into one clarification. Research facts such as head counts,
source entrypoints, required module families, and tensor shapes yourself. Do not
ask the user to supply facts obtainable from the selected evidence. If several
checkpoints could match the request and materially differ, resolve that ambiguity
before committing semantic scope.

Reviewer, source verification, semantic validation, and final acceptance are
required quality steps, not optional table rows. Do not ask whether to enable the
first required independent Reviewer when applicable collaboration rules permit
skill-requested delegation. An actual higher-priority prohibition is a blocker;
describe the precise restriction instead of calling Reviewer optional.

Different views may use different depths. Preserve such a request explicitly;
do not silently force it into the current single-depth request_contract schema.
Use separate scoped project records for different depths while keeping their
common source snapshots consistent. Explain this choice in the configuration.

## Persistent choices

Record semantic choices and the original task in `project.request_contract` and
their realization in `project.delivery_scope` as defined in compiler-workflow.md.
Save interaction choices in `project-state.json.execution_contract`:

```json
{
  "mode": "autonomous",
  "configuration_status": "confirmed",
  "confirmation_source": "User message confirming the proposed configuration",
  "output_formats": ["drawio", "png", "svg"],
  "checkpoints": [],
  "replan_after_non_improving_attempts": 3
}
```

`mode` is `autonomous` or `checkpointed`; `configuration_status` is `proposed` or
`confirmed`. An explicit "start now" or "reuse the previous configuration" is a
valid confirmation source; silence is not. For checkpointed work, name the actual
user-review milestones in `checkpoints`. Do not add an approval after every tool.
For resume/local edits, reuse saved choices and ask only about unresolved material
conflicts. A missing legacy execution record is not a reason to re-ask an explicit
autonomous instruction: record it and continue. Execution choices live outside
semantic IR so switching interaction mode alone does not invalidate source review.

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
