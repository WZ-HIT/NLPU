# Public Detect contract v1; judgment v2 and investigation notes v1

This directory contains only public code and a public schema. It never reads host
labels, hidden inventories, target patches or model credentials. Each formal Detect
run mounts a separate read-only snapshot and records all file hashes.

All three SDD methods and all material groups share `judgment.py` (update-judgment-v2).
Judge task requirements against current source and explain why the method itself
needs edits. Reference maintenance can matter without changed behavior; related
calls, missing annotations or shared dependencies alone do not justify selection.
The paired examples in `judgment.py` are generic and contain no benchmark answers.

For candidates actually investigated, save a short note separately from the final
draft (the example is illustrative, replace its ID and evidence with real source):

    python3 /run/sdd-public/decisions.py save --directory PLANNING --repository /workspace < note.json
    python3 /run/sdd-public/decisions.py status --directory PLANNING

See `decision-example.json`. Notes include task requirement, method-edit reason,
support, counterevidence, unknowns, edit scope, selected/excluded/pending state and
evidence exposure. `name_only`, `complete_result` and `source_expanded` are separate
claims; a search string is not proof that the complete result or source was read.
Refs can use source `path:lines` in every group, and material pointers when present.
These are self-reported observations, not proof of attention or ground truth.

Only existing test identities pass save validation. New tests or test moves can be
discussed against an existing investigated identity, but cannot become selected
method-content targets. Selected requires method_content and supporting evidence;
this format check does not prove necessity. Helper-only changes are separate.

Each compact note is at most 2,200 UTF-8 bytes, at most 3 revisions per identity,
256 investigated identities per run; unchanged saves are free. Limits return
explicit errors, never silently drop records or restrict the final predictions.
At a limit stop logging and record that diagnostic coverage is incomplete in the
normal planning notes; continue the required investigation and final output.
State is atomically replaced at `.detect-progress/candidate-decisions.json`, with
previous revisions retained. No extra model review, extra final-draft validation
or new scoring fields are introduced. All groups share the same note budget.

`python3 /run/sdd-public/contract.py version` reports implementation and schema hashes.
`validate --repository /workspace --file PATH --protocol testcase-v1` returns two
layers: JSON structure and exact base source identity. Errors have stable codes and
field positions. Identity diagnostics do not automatically remove predictions:
the host retains the original invalid-identity false-positive policy.

The final draft is exactly `{"candidates": []}`, or a candidates array containing
objects with `path`, `symbols` and `reason`. Source definitions, including nested
class names, are counted once; inherited aliases are not new source methods.

Selecting a method requires task requirements linked to current source. An import,
mock, annotation or shared dependency is only evidence to inspect, not proof of a
required edit. Method-internal reference edits are not automatically excluded as
method renames. AST-identical formatting is excluded; the current protocol does
not prove semantic equivalence of AST-changing rewrites. If a shared-helper edit
suffices, its test users must not all be selected by relatedness alone.

`save --directory PLANNING [--pending QUESTION]` reads a revisable JSON draft from
stdin and atomically saves `.detect-progress/progress.json`. Pending questions are
separate from the final schema. `finalize --directory PLANNING --repository
/workspace --protocol testcase-v1` validates and publishes the final JSON. At most
three distinct-draft validations are allowed; unchanged checks are cached. A
provisional progress record cannot be sealed as a finished result. This helper
does not force publication, correct candidates from labels, or recover failed runs.

`status` reports remaining wall time from the runner deadline. Start finalization
with 180 seconds left, or upon the native rollout reminder; token remaining stays
unknown without an explicit runtime report. Check completion rate together with
recall: earlier termination alone is not proof of improvement.

`BASH_ENV` loads tool shell functions, including in `bash -lc`. For an explicit
interpreter invocation use `python3 /run/sdd-public/tool.py openspec|specify|cc-sdd
ARGS`. The existing sandbox denies direct execution of tool shebang scripts;
this launcher uses the pinned allowed interpreters without weakening that policy.
Use `git grep`, `grep`, `find` or `python3` when `rg` is absent. Required SDD stages
remain unchanged; the probe performs only neutral tool and contract operations.
