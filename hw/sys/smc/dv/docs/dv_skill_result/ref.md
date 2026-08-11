This proposal adds an AI-assisted quality layer on top of our existing DV flow — it does not replace any part of it. FCOV, code coverage, regression, design review, and signoff all remain unchanged. The goal is to surface weak or missing proof earlier, with less manual status tracking.

The layer is delivered as three AI skills, one per phase: Skill 1 derives the SPEC-based feature_list and generates the per-testcase VPLAN checkbox sets and their mapping (VPLAN); Skill 2 self-audits each completed testcase against its checkboxes (test creation); Skill 3 is an independent IP peer-audit at the end of P2.

Scope-specific checks. Checkbox generation and IP peer-audit at IP scope, testcase self-audit at testcase scope, subsystem/SoC as future work.

Two layers, kept separate. The feature_list (what the SPEC requires) is distinct from the checkbox sets (that each testcase step executed correctly). Self-audit proves the checkboxes; the peer-audit owns the check that all checkbox sets together fully cover the feature_list.

Peer review is advisory. An independent reviewer — someone who did not implement the IP — uses a fresh, read-only AI context. It produces findings only; no signoff or tracker authority. It runs with or without an existing checkbox set.

Clear ownership boundaries. Designer owns intended behavior; DV owner owns implementation and evidence; signoff authority owns waivers; the peer reviewer owns quality findings; the existing process retains final "Done."

VPLAN Phase — Define the proof

Before any test is written, Skill 1 turns the spec into a concrete verification contract at two distinct levels. First, it derives the feature_list: an atomic, spec-cited inventory of every in-scope required behavior — what the SPEC requires. Second, for each testcase it generates checkbox sets — the per-step checks that a testcase executed correctly, each with an exact expected result and a grep-able evidence token — replacing vague intent like "the feature works" with something that can actually be proven.

The two are tied together by a bidirectional feature ↔ checkbox mapping: every checkbox maps to one or more features, and the union of all testcase checkbox sets must fully cover the feature_list. The concept mirrors functional coverage (FCOV): a feature is like a cover point that must be exercised, and a checkbox is the logged proof that a step was covered. A milestone closes when the checkbox sets together cover every required feature and every mapped checkbox is proven by retained log evidence.

Input: pinned SPEC revision, milestone scope, IP boundary.

Output: the feature_list, per-testcase checkbox sets, and the feature ↔ checkbox mapping — filed as P0/P1/P2 GitHub issues.

Owner: Skill 1 drafts; the designer approves the feature semantics and mapping.



feature_list

Checkbox sets

Comes from

the SPEC

the testcases / VPLAN

Answers

What must be verified?

Did each step execute correctly?

Level

requirement (IP-wide)

execution (per-testcase step)

Unit of

milestone coverage accounting

logged proof

Changes when

the SPEC changes

the test implementation changes

Owned/checked by

Skill 1 generates · Skill 3 checks full coverage

Skill 1 generates · Skill 2 self-audits

Filed as GitHub issues, each labeled by priority (P0 / P1 / P2) and containing its description, steps, and checkboxes.

Test Creation Phase — Prove each testcase

With the contract approved and frozen, the DV owner implements each testcase to hit its assigned checkboxes. Once a testcase's simulation passes, Skill 2 runs a self-audit against the approved contract and grades every required checker — only a checker with the exact expected evidence token, at the current revision, counts as proven. A simulation PASS starts the audit; it does not complete it.

This is the "hit the bin" step from the VPLAN analogy: the testcase runs, the log emits the evidence token, and Skill 2 confirms the bin was genuinely covered — not vacuously, not by a stale or default path. Skill 2 works on one testcase at a time; the IP-wide coverage check belongs to Skill 3. It can also run on in-flight projects that never started from a checkbox set. Ideally the auditor is a different model from the one that wrote the test, so no model grades its own work.

Input: one completed testcase (simulation PASS) + its approved checkbox set.

Output: a per-checker grade; on all-proven, an authorized tracker sync to evidence-closed.

Owner: the DV owner runs it and closes findings; read-only by default.



Tracker sync. Once logging-proof is confirmed and with explicit authorization, Skill 2 syncs the GitHub issues: ToDo → InProgress while iterating, and on full proof the DV owner confirms the transition to Done. GitHub mirrors the versioned checklist and evidence — it is not the source of truth.

Use a different model for the audit (cross-model check)

Skills are kept in separate fresh contexts — but stronger still is running the audit on a different model from the one that created the testcase. For example, use one model (e.g. Opus) to generate and implement the testcase, and a different model (e.g. GPT) to run Skill 2's evidence audit.



End of P2 — IP peer audit (advisory)

When P2 test creation is complete, an independent quality review runs at the gate. A reviewer who did not implement the IP uses a fresh, read-only AI context to re-check selected high-value and shared-infrastructure paths — it does not re-run the entire self-audit. The reviewer records cited findings and one of four plain results: Pass, Pass with findings, Fail, or Insufficient evidence. Pass / Pass with findings feed the existing signoff; on Fail / Insufficient evidence, findings return to the DV owner to fix and re-run, and the peer only re-verifies.

Its defining IP-level job — the one a per-testcase self-audit structurally cannot do — is to confirm that the union of all testcase checkbox sets fully covers the feature_list: no required feature left uncovered, no checkbox orphaned. It also samples checker logic for validity and non-vacuity, reviews shared infrastructure once, and hunts common-mode risk. It is advisory throughout — no signoff or tracker authority, and the existing process still owns the final "Done."

Input: frozen artifacts — SPEC, feature_list, checkbox sets, mapping, code, logs.

Output: cited findings + one result (Pass / Pass with findings / Fail / Insufficient evidence).

Owner: an independent peer, not the implementer; ideally a different model.



Human check stays mandatory — AI does the volume, humans own the judgment

AI does most of the work — it generates the checkboxes, audits every testcase, and reviews the IP — but a human approval gate remains required at every phase, not optional:

VPLAN (after Skill 1): the designer approves feature semantics and the mapping. If the requirement itself is wrong, every downstream AI proof is proving the wrong thing.

Test creation (after Skill 2): the DV owner reads the audit result, closes findings, and authorizes the tracker sync. AI marks a checker PROVEN; a human confirms before it becomes evidence-closed.

End of P2 (after Skill 3): a human peer makes the final call; any AI-derived candidate (feature_list, testlist) requires owner/designer approval; final signoff and "Done" always stay in the existing human process.

This is a must, for a specific reason: an LLM tends to confirm rather than refute — it is prone to rationalizing uncertain evidence as a pass, especially when it sees a green log. Without a human gate, green lights inflate and "PROVEN" loses its meaning. The skills are deliberately built to draft but never self-approve: letting AI bless its own output is the exact failure this workflow exists to prevent (it is why we keep contexts separate and prefer a different model for the audit). The human gate is the final backstop against a confident false-positive — and the accountable signoff decision, which can ship a hole if wrong, must rest with a person, not a model.

In short: AI covers the volume — every testcase, every checker — and humans own the judgment: is the intent right, is the green trustworthy, can we sign it off.



Proposed Workflow

1. Why an AI quality layer on top of the current DV flow?

Our existing DV flow — FCOV, code coverage, regression, design review, and signoff — is built on one implicit assumption: that each test actually proves what it claims to prove. Coverage metrics tell us whether a test ran, not whether it verified the right thing.

AI-assisted and AI-generated DV work stresses exactly that assumption. An AI can produce a testcase that compiles, runs, reports PASS, and closes its VPLAN checkbox — while proving nothing. These tests look complete and pass regression, so nothing in the current flow flags them.

A recent audit of our AI-driven DV tasks made this concrete: 51 findings where a test reported success without real proof — empty assertions, always-true checks, phases that silently skip, log-only "failures," and tests that verify the wrong target.

The takeaway: coverage and regression confirm a test exists and runs; they cannot confirm it actually verifies its intent. As AI accelerates test generation, that blind spot scales with it. This proposal adds an AI-assisted quality layer to close that gap — it does not replace any part of the existing flow.

2. What the 51 findings look like (F / E / S / O)

Every hollow test fails in one of three plain ways — we label them F / E / S — plus an Other bucket for the rest. The point of the taxonomy is that these failure modes are enumerable and detectable, not vague suspicions.

Bucket

Plain meaning

What the AI actually did

F — Faked pass

Faked pass.

Invented a pass instead of measuring one.

E — Empty test

Couldn't-test, passed anyway.

Gave up quietly and called it green.

S — Silent fail

Saw the bug, said nothing.

Wrote the check but forgot to make it fail.

O — Other

Not one of the three: checker switched off, wrong thing checked, or forced-pass on purpose.

—

Breakdown by bucket (51 findings)

Bucket

Count

Detailed failure-modes

F · Faked pass

17

fabricated verdict (10) + always-true / tautology (7)

E · Empty test

12

skip-to-pass (7) + placeholder phase (4) + orphan (1)

S · Silent fail

12

log-only / advisory-info (12)

O · Other

10

checker disabled (5) + wrong-thing checked (2) + by-design (3)

Failure-mode legend

F1 fake pass/fail · F2 can't-fail check · E1 jumps to pass · E2 empty stub phase · E3 never-runs / dead · S1 logs only, never fails · O1 checker turned off · O2 checks wrong thing · O3 intentional by design

Why this matters for the workflow. The buckets are not evenly hard to catch. F and S (faked pass, log-only) and most E are structural — you can spot them from the test code alone, without knowing design intent. O2 (checks the wrong target) and E3 (never wired in) are intent failures — the code looks reasonable and only reveals itself when checked against what the VPLAN says the test was supposed to prove. This split is exactly what motivates two distinct skills in Section 3: a structural self-audit, and an intent-level peer-audit.

F / E / S / O — real examples from the audit

One real example per bucket, taken from audited tests — every one reports PASS while proving nothing.

F — Faked pass · smu_lifecycle_debug_policy_test.py

actual_result = expected_result        # set to the expected value
if actual_result == expected_result:   # always True
    log.info("[PASS] ... as expected")

Compares a value to itself — 100% pass on any RTL.

E — Empty test · smu_dtp_otp_debug_access_test.py

probe.force(arvalid_src, 1)                 # force the request in
require_equal(arvalid_dst, 1,               # only checks it propagates
              "OTP ar_valid propagation")   # feat_ctrl is never set

Forces the access straight through — never sets feat_ctrl, so there is no allow/deny to test.

S — Silent fail · smu_jtag2axi_security_test.py

tdo_bits = await scan_dr_bits([1], 1)        # always returns 1 bit
log.info("Gated DR response: %s", tdo_bits)  # logs it
if len(tdo_bits) != 1:                        # length is always 1
    raise AssertionError(...)                 # so this never fires

Logs the gated response but only checks its length — never that the access was actually blocked.

O — Other (wrong target) · smu_feat_ctrl_monitor_test.py

require_equal(dtp_soc_debug, sep_val,
              "DTP soc_debug mirrors SEP feat_ctrl")  # checks the wire
# never checks the gating expression that consumes feat_ctrl

Verifies the wire mirrors the value — not that the gate actually blocks access.

Scope note. This was a targeted audit of dv/{smu,smc,sep,dtp} (626 cocotb + 886 SV files; OSS vendor code excluded), not a full-coverage sweep. The 51 findings are confirmed instances, not a statistical estimate.

3. Three AI skills

This layer adds three AI skills, one for each phase of the existing DV flow. Each skill works at one scope, checks one target, and catches a specific set of the failure-modes from Section 2. Together they connect what the SPEC asks for to what the test actually proves.

Two artifacts hold the layer together and are kept separate on purpose:

feature_list — what the SPEC requires (the intent). This is the plan we close against, like an FCOV cover plan.

checkbox sets — the proof that each test step really ran and checked the right thing (the evidence). Each checkbox is like an FCOV bin: it must be hit by real logged proof, not just claimed by the test author.

Skill 1 builds both. Skill 2 checks that every checkbox has real logged proof behind it. Skill 3 merges all checkbox sets and closes them against the feature_list — the proof-level version of FCOV coverage closure.

Skill 1 — VPLAN generation





Scope

IP

Phase

VPLAN

Target

Build the SPEC-based feature_list, the per-testcase checkbox sets, and the feature_list → checkbox mapping.

Role

The source of intent. It does not audit tests — it builds the reference the other two skills check against.

This is the leverage point. The intent failures from Section 2 (O2, E3) can only be caught if there is a clear, machine-checkable statement of what each test is supposed to prove. Skill 1 writes that statement. It also fixes the "plans overstate completion" problem from the audit — where VPLANs marked empty placeholders as Implemented — because the checkboxes come from the SPEC, not from the test author.

The quality ceiling is set here: a bad VPLAN makes every audit below it useless.

Skill 2 — Testcase self-audit





Scope

Testcase

Phase

Test creation

Target

Check each finished testcase against its own checkbox set, reading the test code line by line.

Owner

The DV owner who wrote the test.

Catches

F1 fake pass/fail · F2 can't-fail check · E1 jumps to pass · E2 empty stub phase · S1 logs only, never fails

Checkbox set vs. a single PASS — the FCOV idea, applied to proof. FCOV changed how we trust a test. We stopped believing "the test ran" and instead defined real bins and measured whether each one was hit, recorded in a coverage database. A pass became a measurement, not a claim.

The checkbox set uses the same idea for correctness. Instead of trusting the one PASS at the end, each checkbox must be backed by logged proof from the run — a real comparison that ran, a real assertion that fired. One verdict is a single bit. A checkbox set with proof behind each box is evidence you can audit.

A concrete set of audit rules, checked line by line. The FCOV idea sets the goal; the audit rules do the work. At testcase scope the skill reads the code line by line and applies a fixed list of pass/fail rules, each one aimed at a known failure-mode from Section 2. For example:

Audit rule

Blocks

[NO-ALWAYS-PASS-CHECKER]

F2 — assert True, 1-bit tautologies, any check that cannot fail

[NO-BACKDOOR-WRITE]

F1 — TB writes its own PASS magic, or forces a net then reads back the same value

[NO-FABRICATED-VERDICT]

F1 — canned / mock return values standing in for a real result

[NO-SKIP-TO-PASS]

E1 — returns pass when an HDL path or earlier step is missing

[NO-EMPTY-PHASE]

E2 — no-op stub phases, # In real test placeholders

[MUST-FAIL-ON-MISMATCH]

S1 — a mismatch that only logs, with no uvm_error / assert / raise

Because each rule maps to a code pattern, the self-audit is a simple, mechanical action, not a judgment call: for each checkbox, point to the logged proof for it, and confirm no rule is violated. No proof, or a rule broken → the checkbox is not met → the test is not done — the same way an unhit bin shows untested behavior even when the test "passed."

Skill 3 — IP peer-audit





Scope

IP

Phase

End of P2

Target

Review an IP's testcases against VPLAN intent, and check that all checkbox sets together cover the feature_list.

Reviewer

Someone who did not write the testcase, using a fresh, read-only AI context.

Authority

Advisory only. It reports findings; it holds no signoff or tracker authority.

Catches

O2 checks the wrong thing · E3 never-runs / dead / not wired in — plus feature_list coverage gaps.

Coverage closure, applied to proof. Peer-audit has two jobs. The first is intent review (below). The second is a simple, mechanical action taken straight from FCOV coverage closure: in FCOV we merge every test's coverage database across the regression and check that every bin in the plan was hit. Skill 3 does the same thing one level up — it merges every testcase's checkbox set across the IP and checks that, together, they cover every item in the feature_list.

This gives a real diff, not an opinion:

feature_list − (all checkbox sets combined) = the uncovered items

Any feature_list item with no checkbox behind it is a coverage hole — the proof-level version of an unhit bin — found by the tool, not argued over.

Higher-level audit — steps and checkboxes, not every line. Skill 3 works at IP scope, so it does not have to read every testcase line by line the way Skill 2 does. It audits at the step ↔ checkbox level: does each test step map to a checkbox, and do the checkboxes together close the feature_list? Only when a checkbox looks wrong does it drill down into the code. This keeps peer-audit at a scale one reviewer can handle across a whole IP, while the line-by-line rules stay with the test's own owner in Skill 2.

Intent review — what only a peer can catch. The rest are intent failures: the code looks fine and passes a structural self-audit, and the problem only shows up when you compare the test to what it was meant to prove. Issue #3538 is this case — smu_feat_ctrl_monitor_test checked wire continuity (O2) instead of the gating policy the plan said it covered, so no self-audit could catch it. Only a reviewer comparing the test to VPLAN intent — and running the coverage diff above — closes this gap.

The three skills at a glance



Skill 1 — VPLAN gen

Skill 2 — Self-audit

Skill 3 — Peer-audit

Scope

IP

Testcase

IP

Phase

VPLAN

Test creation

End of P2

Target

intent baseline

structural proof

intent proof + coverage

Owner / actor

DV owner

DV owner (self)

Independent reviewer

Catches

(enables the rest)

F1 F2 E1 E2 S1

O2 E3 + coverage gaps

Authority

—

—

advisory (findings only)

4. How the three skills hook into the current DV flow

The layer adds no new phases and changes no existing artifact. Each skill attaches to a phase we already run, produces one new artifact, and is owned by a role already present in that phase. In the flow diagram these new artifacts are shown in yellow, sitting alongside the existing flow — deliberately mirroring how FCOV Spec → FCOV (grey) already runs in parallel with the functional flow. The whole layer is the same discipline as FCOV, applied to correctness proof instead of coverage.

Hook points

Skill

Hooks at phase

Input (existing)

New artifact

Owner / actor

Skill 1 — VPLAN gen

Verification Planning

Spec.

Feature List (+ checkbox sets in TestPlans)

Arch. / Designers + DV Owners

Skill 2 — Self-audit

Create Testcases (P0 / P1 / P2)

TestPlans (checkboxes)

Audit Reports (Self) — one per phase

DV Owner (self)

Skill 3 — Peer-audit

End of P2 → before Analysis Result

Feature List + all checkbox sets

Audit Reports (Peers)

DV Peers (new role)

Skill 1 at Verification Planning

Skill 1 runs where TestPlans are already written, and takes the same input — the Spec. It adds one artifact, the Feature List, and the per-testcase checkbox sets that live inside TestPlans. Nothing about how TestPlans are authored changes; the Feature List is a second output derived from the same SPEC, the way FCOV Spec is derived alongside the plan today. Owner stays the same: Arch./Designers set intent, DV Owners write the plan.

Skill 2 across P0 / P1 / P2

As testcases are created in each phase, the DV Owner runs the self-audit on their own tests and produces an Audit Report (Self) for that phase — one per phase, shown grouped in the diagram. The input is the checkbox set already in TestPlans; the action is the line-by-line rule check from Section 3. This stays entirely inside the existing "Create Testcases" phases and adds no hand-off — the person who writes the test is the person who runs the self-audit.

Skill 3 at end of P2 — the one new role

Skill 3 introduces the only new actor in the flow: DV Peers (marked separately in the diagram). At the end of P2, a reviewer who did not write the tests runs the peer-audit against the Feature List, and produces the Audit Report (Peers). This closes the loop before Analysis Result: the peer report and the coverage diff (Feature List − all checkbox sets) feed the final analysis alongside CodeCov and FCOV. The peer role is advisory — it adds a report, not a gate; the existing phase still owns "Done."

What stays unchanged

Testbench, Testcases, CodeCov, FCOV, regression, and signoff are untouched. The yellow layer only adds artifacts and one advisory review; it removes nothing and re-routes nothing. A team could stop producing the yellow artifacts tomorrow and the original flow would still run exactly as before.

5. Landing plan — two weeks

Target: a working first version of all three skills, adopted on one real IP, within two weeks (Jul 21 – Aug 1, 2026). Scope is intentionally minimal — one builder, one adopter, high-level specs — so the layer is proven on real tests before any wider rollout.

Roles

Role

Owner

Responsibility

Spec / requirements

Henry

Provide the high-level spec and requirements for all three skills — scope, target, audit rules, inputs/outputs. This is the upstream dependency; skill build starts from it.

Skill build

Bruce

Build the three AI skills (VPLAN gen, self-audit, peer-audit) to Henry's spec.

First adopter

MinShao

Run the built skills on his own IP, produce the first real Feature List / Audit Reports, and feed back gaps.

Schedule

Days

Dates

Milestone

Lead

Week 1, early

Jul 21 – Jul 23

Henry delivers high-level spec for all 3 skills (Skill 1 first, so build can start early).

Henry

Week 1, late

Jul 24 – Jul 25

Bruce builds Skill 1 (VPLAN gen); MinShao generates first Feature List + checkbox sets on his IP.

Bruce → MinShao

Week 2, early

Jul 28 – Jul 30

Bruce builds Skill 2 (self-audit) + Skill 3 (peer-audit); MinShao runs self-audit on his testcases.

Bruce → MinShao

Week 2, late

Jul 31 – Aug 1

Peer-audit dry-run on MinShao's IP; collect feedback; adjust specs. First-iteration retro.

All

Sequencing

The three tasks overlap rather than run strictly one after another:

Henry (spec) → Bruce (build) → MinShao (adopt)

Henry delivers Skill 1's spec first so Bruce can start building while the Skill 2 / 3 specs are still being written. MinShao adopts each skill as it lands, so feedback reaches Bruce within the same week — not all at the end.

Definition of done (first iteration)

All three skills exist and run end-to-end on one IP (MinShao's).

One Feature List, at least one Audit Report (Self), and one Audit Report (Peers) produced from real tests.

A short feedback list from MinShao driving the next spec revision.

This is a pilot, not a rollout. Success is "the loop runs once on real tests and we learned what to fix," not "every IP adopts it."

6. Future work

This proposal delivers the first, minimal version — three skills, one IP, advisory only. The framework is built to grow along several axes.

Scope: up the hierarchy

The three skills stop at IP scope today. The same pattern extends upward:

testcase-level (self-audit) → IP-level (peer-audit) → subsystem / SoC-level audit

A subsystem/SoC-level skill would check that IP-level Feature Lists compose correctly — that cross-IP interactions, integration features, and system-level intent are covered, not just each IP in isolation. This scope is owned by the DV project lead, mirroring how testcase scope is owned by the DV owner and IP scope by a peer.

Closer to the loop: from advisory to CI

Today the skills produce reports for people to read. A later step is to hook self-audit into CI, so a testcase with an unsatisfied checkbox (no logged proof) is flagged automatically on every PR — moving structural checks from advisory toward gating. Peer-audit and intent review stay advisory by design; only the mechanical, structural checks are candidates for automation.

Feedback to the source

The audit findings are data. Aggregated failure-mode statistics can feed back into Skill 1 — surfacing which checkboxes are repeatedly generated poorly, or which SPEC areas produce weak Feature Lists — so VPLAN generation improves over time instead of staying static.

Evolving the rule set

The [NO-…] / [MUST-…] audit rules are a starting list. They should be versioned and extended: when a new failure-mode appears in the wild, it becomes a new rule, and the skill picks it up everywhere at once — the same way a new coverpoint enters an FCOV plan.

Auditing the auditor

The audit skills can themselves have blind spots (false passes, false alarms). The 51 findings from the original audit make a natural golden set: a regression that measures whether the skills still catch every known failure-mode as they evolve. Quality of the quality layer becomes measurable, not assumed.

The Three AI Skills — what each one produces and checks
Scope first. Checkbox/feature generation and peer-audit work at IP scope; self-audit works at testcase scope. The pattern is IP → testcase → IP: plan the whole IP's contract, prove each testcase deeply, then step back and review the IP as a whole.

Skill

Scope

Asks

Method

Skill 1 — feature_list + checkbox creation

IP

What must be verified, and what proves it?

Derive feature_list from SPEC, generate checkbox sets + mapping

Skill 2 — self-audit

Testcase

Did this one testcase prove its contract?

Exhaustive, line-by-line on one completed testcase

Skill 3 — peer-audit

IP

Is the IP fully covered, consistent, and free of blind spots?

DV-expert, sampled, high-level review

All rules are named once in the canonical DV Quality Tag Glossary and referenced below by tag. Phase markers: C = creation, S = self-audit, P = peer-audit. Running example throughout: a completion-interrupt status bit that is write-1-to-clear (W1C).

image-20260712-034432.png
Skill 1 — feature_list + Checkbox Creation · IP scope · Phase C
Extends the existing tt_test_plan skill. It turns the spec into a two-layer contract: what must be verified (feature_list) and what proves each step (checkbox sets).

Input — pinned spec revision + section refs; current milestone (P0–P3), IP boundary, existing testcase inventory; optional register/RTL/reference-test revisions.

Output — the SPEC-derived feature_list; per-testcase checkbox sets (each checker with a stable ID, an exact expected result, and a grep-able evidence token); the bidirectional feature ↔ checkbox mapping. Filed as P0/P1/P2 GitHub issues carrying description, steps, and checkboxes.

What it must get right:

Everything traces to the spec — nothing invented. Each feature cites a real spec section, is one atomic behavior, and the list is complete. [SPEC-CITATION] [ATOMIC-FEATURE] [FEATURE-INVENTORY-COMPLETE]

IDs are stable and scoped. Feature/cell/checker IDs never change; every feature has an approved milestone. [STABLE-ID] [MILESTONE-SCOPE]

Both directions map. Every feature maps to a checker, every checker back to a feature. [TRACEABILITY]

Each checker is provable. It states an exact value/transition (not "something happened") and defines a grep-able token it prints on proof. [EXACT-EXPECTATION] [EVIDENCE-ID]

No hollow checks. A checker can't pass from nothing; a wait that never fires becomes a fail; status is set/cleared/checked. [CHECKER-NONVACUITY] [TIMEOUT-MUST-FAIL] [STATUS-LIFECYCLE]

A human approves the meaning. The designer signs off against a pinned revision; the skill cannot approve its own checklist, and "feature works" / "test passes" are rejected. [DESIGN-APPROVAL]

Example output:

text



FEATURE-ID: IRQ-DONE-W1C   SPEC-REF: IRQ §4.3   MILESTONE: P1
INTENT: completion IRQ asserts, clears by write-1, reads back 0
- [ ] CHK-IRQ-ASSERT   EXPECT: on completion, status bit = 1        EVIDENCE: IRQ_ASSERT_OK
- [ ] CHK-IRQ-W1C      EXPECT: write 1 clears to 0; write 0 no-op   EVIDENCE: IRQ_W1C_OK
- [ ] CHK-IRQ-READBACK EXPECT: after clear, status reads 0          EVIDENCE: IRQ_READBACK_0
- [ ] CHK-IRQ-LINE     EXPECT: IRQ line deasserts after clear       EVIDENCE: IRQ_LINE_DEASSERT
- [ ] CHK-IRQ-TIMEOUT  EXPECT: no assert in N cyc → fail + diag     EVIDENCE: IRQ_TIMEOUT_FAIL
Skill 2 — Test Evidence Self-Audit · Testcase scope · Phase S
Extends the existing oss_dv_audit / tt_dv_audit / smu_sep_dv_audit skills. It adds two things: grading each checker against the contract, and the authorized tracker sync. Exhaustive on one completed testcase.

Input — one completed testcase (simulation PASS) + its approved checkbox contract; the testcase and shared DV code, retained log, seed, build/config identity, regression enrollment.

Output — a grade per checker: PROVEN / FAILED / STALE / NOT-RUN / INSUFFICIENT-EVIDENCE / LINKED-ISSUE (only PROVEN earns [x]). On all-proven: an authorized tracker sync to evidence-closed (awaiting signoff).

What it checks — in plain terms:

The evidence is real. The log reproduces the exact token, path/line, and seed, at the current revision — a PASS alone is not proof. [POSITIVE-EVIDENCE] [EXACT-EXPECTATION] [EVIDENCE-FRESHNESS]

The checker actually works. It can't pass on nothing, and injecting a fault makes it go red — proving it can fail. [CHECKER-NONVACUITY] [CHECKER-SENSITIVITY]

Access and behavior are legitimate. No backdoor force/poke without a documented reason; drive/check through the front door; W1C status fully exercised; waits fail on timeout; negative tests prove both the error and no forbidden side-effect. [NO-BACKDOOR-WRITE] [FRONTDOOR-FIRST] [STATUS-LIFECYCLE] [TIMEOUT-MUST-FAIL] [NEGATIVE-SIDE-EFFECT]

The code is disciplined and clean. Bugs raise uvm_error (never lean on uvm_warning); helpers reused and layered; no dead/dummy code; nothing silently skipped; matches the contract and is regression-enrolled. [SEVERITY-DISCIPLINE] [REUSE-AND-LAYERING] [NO-DUMMY-DEAD-CODE] [NO-UNEXPLAINED-SKIP] [CONTRACT-MATCH] [REGRESSION-ENROLLED]

Scope note. [REUSE-AND-LAYERING] and [NO-DUMMY-DEAD-CODE] cover this testcase's own code only — shared-infra quality is peer-audit's job, not re-checked after every testcase.

Two conditions. With a checkbox set → audit directly against the contract. Without one (in-flight VPLAN) → closed-loop mode: follow the VPLAN, generate checkboxes, simulate, check the proof, iterate — but never invent checkboxes after seeing a passing log; a missing set stays a VPLAN migration gap.

Cross-model. Ideally the audit runs on a different model from the one that wrote the testcase, so no model grades its own work.





Skill 3 — IP Peer-Audit · IP scope · Phase P
An independent peer (did not implement the IP) uses a fresh, read-only AI context. It cannot go line-by-line over every testcase — it is a DV-expert, risk-based, sampled review of logic quality and IP-wide consistency, ideally on a different model again.

Input — frozen IP artifacts: spec, feature_list, checkbox sets + mapping, testcase and shared-infra code, testlists, retained logs, exception list. The self-audit results are taken as input, not trusted blindly.

Output — cited findings + one result: Pass / Pass with findings / Fail / Insufficient evidence. On Fail / Insufficient, findings route to the DV owner to fix and re-run; the peer only re-verifies.

How it works — expert review, not exhaustive:

Coverage. Confirm the union of all checkbox sets fully covers the feature_list — no feature uncovered, no checkbox orphaned. Its defining IP-level job.

Alignment. Do VPLAN ↔ checkbox set ↔ testcase inventory ↔ evidence all agree?

Sampled logic read. On high-value paths: is the if/else correct? is the checker valid or does it pass vacuously? any dead code?

Shared infrastructure, used by every test, is reviewed once — high leverage.

Common-mode judgment: the same wrong assumption baked into stimulus + golden + checker at once.

What it checks:

IP-only rules. Coverage/consistency, shared-infra soundness, common-mode risk, representative proof, and gaps in the checklist. [FEATURE-INVENTORY-COMPLETE] [IP-CHECKLIST-CONSISTENCY] [SHARED-INFRA-QUALITY] [COMMON-MODE-RISK] [REPRESENTATIVE-EVIDENCE] [QUALITY-OBLIGATION-GAP]

Self-audit rules, sampled at IP level. No backdoor crept into shared sequences; checkers can actually fail (no false-positive green); conventions hold IP-wide (e.g. all interrupt registers follow W1C, not just the one self-audited test); no dead/dummy shared code. [NO-BACKDOOR-WRITE] [FRONTDOOR-FIRST] [CHECKER-NONVACUITY] [CHECKER-SENSITIVITY] [EXACT-EXPECTATION] [STATUS-LIFECYCLE] [NO-DUMMY-DEAD-CODE]

Expert-catch example. A testcase is green and self-audit passed it, but the checker reads if (done) assert(status==expected) while done never becomes true in that test — so the assert never runs. A green log rubber-stamps it; a peer reading the logic flags it as vacuous. [CHECKER-NONVACUITY]

It runs with or without existing artifacts. Skill 3 does not require a Skill 1 checkbox set — this is what lets it audit current, in-flight projects. Depending on what exists (feature_list and/or checkbox sets), it picks the right mode: reconcile against the approved contract when it exists, or fall back to a first-principles expert review from the spec, deriving candidates for owner approval. It never invents or self-approves a contract from passing logs, and reports missing artifacts as VPLAN migration gaps.





Future hardening — optional reinforcements for the skills

These are not new skills; each folds into an existing one when we're ready. Listed with rough cost so we adopt only what's worth it — the goal is a workflow people actually run, so anything too heavy is deliberately deferred.

Reverse feature_list diff (into Skill 1 / Skill 3). Have a different model re-derive the feature_list from SPEC and diff it against the approved one; the delta is "possibly-missing requirements." Cost: low. Adopt early — it guards the weakest foundation (an incomplete feature_list invalidates everything downstream) at almost no extra effort.

Adversarial / refute step (into Skill 2 & 3). Add one explicit prompt that tries to break each PROVEN — "when would this checker miss? could this log be a false pass?" — instead of only confirming. Cost: low, high value. Adopt early — it directly counters the LLM's bias to confirm rather than refute. This is the single highest-leverage addition.

Override logging + spot re-check (process around Skill 2/3). When a human overrides an AI finding, record a one-line reason; periodically re-check a sample of human-approved items with another person/model. Cost: low process, no tooling. Adopt early — cheap insurance against the human gate becoming a rubber stamp.

Known-gaps ledger (into milestone closure). Emit an explicit "what we know we have NOT verified" list per milestone (deferred / waived / out-of-scope / untouched state space). Cost: low. Adopt early — honest disclosure, makes signoff meaningful.

Calibration metrics from the pilot (into Skill 2/3 reporting). Track false-positive rate (PROVEN but wrong), false-negative/noise rate, and human-override rate. Cost: medium (needs data collection). Adopt during pilot — this is what moves the workflow from "solid by design" to "solid by evidence."

Re-executable evidence (into Skill 2, selected checkers). For high-value checkers, require the proof to be reproducible from the retained seed, not just a stored log. Cost: medium–high (infra dependent). Adopt later / high-value paths only — strongest for security IP, but too heavy to require everywhere.

Guiding principle for adoption. Add reinforcements only where the risk justifies the friction. Low-cost, high-leverage items (reverse diff, refute step, override logging, gaps ledger) can come early; infra-heavy items (re-executable evidence) stay opt-in on high-value paths. Anything that would make the everyday flow too idealized or too cumbersome is intentionally kept out — a workflow that is too heavy to run protects nothing.
