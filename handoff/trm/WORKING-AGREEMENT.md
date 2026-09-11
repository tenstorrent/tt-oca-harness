<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc. -->

# Standing delegation agreement

User preference established 10 September 2026. Apply to future task briefs and
corrections. The student contributes engineering judgment; the master establishes
intent, constraints and an independent assessment of the result.

## Brief structure

Explain the intended outcome and why it matters, the scope and fixed constraints,
and what would establish success. Give enough context for informed decisions.
The student owns the design, implementation approach, risk analysis and choice
of convincing tests. Avoid turning the brief into a shopping list or recipe.

Separate the task contract from diagnostic evidence and the reviewer's procedure.
Attach concrete defects and reproduction evidence to explain failures; these are
regression cases, not a complete specification or a prescribed solution. Keep
reviewer-specific commands, screenshot names and interaction sequences in review
records unless their exact form is necessary for correctness or reproducibility.
Existing product constraints and build modes remain binding.

## Tests before implementation

“If you can't test, you can't measure your design.”

Ask the student to produce meaningful tests or reproducible measurement checks
before changing the implementation. State the expected outcomes first and run
the checks against the starting revision. Existing suitable tests can be reused.
For a correction, establish that the checks expose the reported failure; preserve
passing behavior too. Then implement and use the same criteria to assess the
result. Tests must measure the required behavior, not mirror the proposed code.

For visual or documentary work, tests may combine measurements, source-backed
content checks and a defined visual assessment. Automation is useful where it
establishes the claim; source parsing cannot substitute for rendered inspection.
Choose a proportionate method rather than manufacturing a test suite or green
count. Keep experimental tests in the authorised artifact area when production
test files are outside scope.

If a claim cannot yet be tested, identify the gap and seek a valid measurement
method or a master decision. Continue independent work where possible. Do not
invent results, silently substitute easier examples, or call an unperformed check
a pass. Apply this prospectively; do not claim tests were written first when
implementation already exists.

## Autonomy, evidence and disagreement

Students should identify related risks and propose better solutions. They may
make reasonable, reversible implementation choices within scope. They must expose
assumptions affecting correctness, scope or acceptance and challenge requests
that conflict with evidence. Neither student nor master should optimise for
pleasing the other at the expense of truth.

Acceptance criteria remain fixed unless explicitly changed through a traceable
decision by the authorised owner. Neither side may weaken them to get a pass.
Tests can evolve as understanding improves, but changes to expected outcomes or
coverage must be explained, not used to hide failures.

The handoff should explain the design and why the evidence establishes the
outcome, identifying limitations and the tested revision. A test count alone is
not proof. The master independently challenges that reasoning and verifies the
result; ordinary corrections stay between agents. Involve the user for genuine
ambiguity, conflicting requirements, material scope decisions or unresolved
evidence-backed disputes.

Use early evidence for risky design choices before investing in the whole task.
This does not introduce an automatic approval gate: the student can test and
adapt autonomously. When evidence is weak, improve the reasoning or method rather
than merely adding more prescriptive instructions. Keep GitHub updates concise;
local review records carry the detailed evidence.
