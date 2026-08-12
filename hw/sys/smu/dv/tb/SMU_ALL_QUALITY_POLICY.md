<!-- SPDX-License-Identifier: Apache-2.0 -->
# Pinned DV Quality Policy — v0.3 (pilot)

**Location:** `.claude/skills/dv_common/DV_QUALITY_POLICY.md` (Skill 1/2/3 default when no
other `quality_policy` is specified)
**Status:** draft for pilot · **Environment:** SMU-scope SEP (values here are pilot values,
not generic defaults) · **Pinned by:** git revision / content SHA-256 of this file
**Consumed by:** Skill 1 (vocabulary), Skill 2 (rules, PASS definition, thresholds),
Skill 3 (sampling, severity mapping)

This is the minimal first version. It exists to unblock the pilot: it defines the common
low-quality test patterns as enforceable rules, plus the minimum vocabulary and thresholds the
three skills require as input. Sections marked *(pilot default)* are expected to be tuned
after the first iteration.

Sources of the failure catalogs: (a) the 2026 audit of AI-driven DV tasks in
`dv/{smu,smc,sep,dtp}` (626 cocotb + 886 SV files), which confirmed **51 findings** where a
test reported success without real proof — see the
[Proposed Workflow](https://tenstorrent.atlassian.net/wiki/spaces/~712020c5d81ce1e2804c8690f94dc0fb1236d3/pages/2623505266/Proposed+Workflow)
page; (b) the `dv_shortcut_audit` design
(`tt-oca-hw/.dv/artifacts/dv_shortcut_audit/2026-06-16-dv_shortcut_audit-design.md`), whose
14-category taxonomy of sim-vs-silicon divergence was motivated by the SEP boot-ROM
`.data`/`.rodata`→DCCM backdoor finding; (c) v0.2 additions: recurring failure modes of
AI-generated DV tests (zero-activity pass, RTL-copied golden, blind-delay sync,
negative-without-positive-control, and related) drawn from general DV practice — these are
preventive rules, not yet all tied to a local finding. Rules from (a)/(b) map to failure
modes actually observed in this repository.

---


## 1. Forbidden low-quality test patterns (the rule set)

A testcase or shared DV helper violating any rule below cannot have its affected checkers
graded `PROVEN`, regardless of simulation PASS. Rule IDs are the canonical tags used by
Skill 2/3 findings.

### F — Faked pass (17/51 findings)

**`[NO-FABRICATED-VERDICT]`** — the verdict is invented, not measured.
Tells: `actual = expected` before the compare; hardcoded `True`; canned/mock return standing
in for a DUT result.
Real case (`smu_lifecycle_debug_policy_test.py`):

```python
actual_result = expected_result        # set to the expected value
if actual_result == expected_result:   # always True
    log.info("[PASS] ... as expected")
```

**`[NO-ALWAYS-PASS-CHECKER]`** — the check cannot fail on any RTL.
Tells: `assert True`; 1-bit/tautological compares; golden taken from the same TB variable
that programmed the DUT.

**`[NO-BACKDOOR-WRITE]`** — TB writes its own success state, or forces a net and reads the
same net back. General rule in every environment; the only escape is a structured,
human-approved exception record (§6).

### E — Empty test (12/51 findings)

**`[NO-SKIP-TO-PASS]`** — the test returns/marks pass when an HDL path or earlier step is
missing or unavailable.
Real case (`smu_dtp_otp_debug_access_test.py`): forces `arvalid` straight through and checks
only propagation — `feat_ctrl` is never set, so there is no allow/deny behavior under test.

**`[NO-EMPTY-PHASE]`** — a phase/function that only logs and returns true; `# in real test...`
placeholders; no-op stubs counted as implemented.

**`[REGRESSION-ENROLLED]`** — orphan tests: a checker/sequence exists but is enrolled in no
regression/testlist, yet the plan marks it done (E3).

**`[NO-ZERO-ACTIVITY-PASS]`** — an aggregate checker (scoreboard, monitor-fed compare loop,
transaction-log diff) passes because it observed **zero items**: the loop body never ran, so
zero mismatches were found. The checker exists, is enabled, and is logically correct — it was
simply never fed (a mis-bound monitor collects silently into an empty queue).
Tells: a compare loop with no minimum-count assertion; `if (queue.size() > 0)` wrapping the
entire check; no `expected_count` reconciliation against the stimulus actually issued.
Rule: every aggregate check must assert a minimum activity count derived from the stimulus;
zero observed items is a fail, never a pass.

### S — Silent fail (12/51 findings)

**`[MUST-FAIL-ON-MISMATCH]`** — a real mismatch that only logs and never fails.
Tells: mismatch handled by `log.info`/`uvm_info`/`uvm_warning` with no
`assert`/`raise`/`uvm_error`; a guard condition that can never fire; a catch-all handler
swallowing failures (`except Exception: pass`, or a `try` around the whole test body that
demotes any error to a log line / skip / pass).
Real case (`smu_jtag2axi_security_test.py`):

```python
tdo_bits = await scan_dr_bits([1], 1)        # always returns 1 bit
log.info("Gated DR response: %s", tdo_bits)  # logs it
if len(tdo_bits) != 1:                        # length is always 1
    raise AssertionError(...)                 # so this never fires
```

Logs the gated response but only checks its length — never that the access was blocked.

### O — Other (10/51 findings)

**`[NO-DISABLED-CHECKER]`** — scoreboard/VIP/assertion switched off for the test (O1).

**`[NO-WRONG-TARGET]`** — the test verifies a real but different property than the plan
requires (O2). Intent-level: detected by Skill 3 comparing the test to its card's `PROOF`
target, not by structural review.
Real case (`smu_feat_ctrl_monitor_test.py`): checks that the DTP debug wire *mirrors* the SEP
value — never that the gating expression consuming `feat_ctrl` actually blocks access
(the pattern that let issue #3538 through a "passing" test).

**`[BY-DESIGN-EXCEPTION]`** — an intentionally forced pass (O3) is allowed **only** with an
explicit documented justification in the approved card; undocumented, it is a finding.

### Cross-cutting proof rules

**`[EXACT-EXPECTATION]`** — checkers state and prove exact values/transitions; "non-OKAY",
"some error", or activity alone is not a contract.
**`[TIMEOUT-MUST-FAIL]`** — every bounded wait converts expiry into testcase failure with
last-state diagnostics; a wait that cannot fire is a fail, not a pass.
**`[EVIDENCE-TOKEN-CONDITIONAL]`** — a positive-evidence token (`CHK-<NAME>: ...`) is emitted
only after the mapped behavior executed and its exact expectation passed; unconditional
success messages are prohibited.

**`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`** — a deny/blocked/error assertion is indistinguishable
from a broken path: a test proving "access is blocked" also passes when the whole bus is dead.
Every negative check (lock, lifecycle gating, debug policy, error response) counts only if the
same mechanism's allow/normal path is proven working — in the same test or in a test the card
explicitly links. Without the positive control, the checker is at best
`INSUFFICIENT-EVIDENCE`, never `PROVEN`.

**`[NO-BLIND-DELAY-SYNC]`** — a fixed delay standing in for a completion handshake: `await
Timer(100, "ns")` / `#100;` followed directly by a sample or assertion. It passes by luck of
sim timing, hides real latency behavior, and breaks under a different seed or config.
Tells: magic cycle counts with no comment tying them to a spec bound; timing-unstable results
across seeds; a delay tuned upward until the test passed.
Rule: completion synchronization must be event/handshake-based with a bounded timeout
(`[TIMEOUT-MUST-FAIL]`); a bare delay may only bridge steps whose latency is itself the
spec-defined quantity being checked.

**`[INDEPENDENT-EXPECTED-MODEL]`** — the reference model is a transcription of the RTL
algorithm (CRC, scrambler, address decode, arbitration re-implemented by reading the RTL):
when the RTL is wrong, the golden is wrong the same way, and the compare can never catch it.
This is the model-level face of the "golden from the same TB variable" tell in
`[NO-ALWAYS-PASS-CHECKER]`.
Rule: expected values must be derived independently of the DUT implementation — SPEC formula,
independent reference implementation, or a pre-approved fixed vector table. An
`EXPECT-SOURCE` reading "derived from RTL" is a finding.

**`[ADDRESS-FROM-AUTHORITATIVE-MAP]`** — the *addressing* face of the rule above.
`[INDEPENDENT-EXPECTED-MODEL]` and `[EXACT-EXPECTATION]` both govern the right-hand side of a
comparison (what value we expect); this governs the left-hand side (what we actually read or
wrote). A test can hold a perfect, SPEC-derived expected value and still prove nothing because
it addressed the wrong register.
Rule: every register address, field offset, and bit position on the proof path is imported by
symbol from the generated register header (the RDL / IP-XACT output), never hand-copied as a
numeric literal. Where no generated header exists, the literal cites the SPEC table and
revision. Any register name appearing in a log line or report must derive from the same symbol
used to address it.
Tells: a numeric address literal in a test or helper when a generated map exists in the same
repo; a logged register name that cannot be traced to the symbol that was read; an offset table
maintained by hand in parallel with a generated one.
Why it is not merely style: a hand-copied literal silently rots when the RDL is regenerated,
and a wrong literal makes the retained log assert a register identity that does not hold —
turning evidence into misinformation. The dangerous case is not a crash but a *pass*: reads of
unmapped space commonly return `0x00000000`, which equals the reset value of many registers, so
a test that does compare values can still pass against an address that was never the register
under test. Adding a comparison does not close this finding; sourcing the address does.
Real case (`i3c_reg_reset_value_full.py:16-29`): 6 of 12 hand-written offsets addressed a
different register than the name they were logged under — `HC_CAPABILITIES` read `0x008`
(actually `CONTROLLER_DEVICE_ADDR`), and `TTI_CONTROL`/`TTI_INTERRUPT_ENABLE` read `0x1C4`/
`0x1D4`, both unmapped, returning `0x00000000`. The authoritative map
(`I3CCSR_reg.py`) was already imported by symbol elsewhere in the same testbench.

**`[SEED-REPRODUCIBLE]`** — any test using randomization must record its seed in the kept log
and be rerunnable to the same result from that seed. An unreproducible random failure is
uninvestigable; an unreproducible random pass is unauditable (Skill 2/3 re-verification
depends on reproduce-from-seed).
Tells: `random` calls with no logged seed; time-derived seeds; seed logged but not actually
applied.

**`[X-AWARE-CHECK]`** — comparisons blind to X/Z. In SV, `==` against a signal that can be X
yields false and silently takes the else branch; in cocotb, `int(sig.value)` on an X/Z value
raises or resolves arbitrarily. A check that passes because X made the failing branch
unreachable proves nothing, and X-optimism is a classic sim-vs-silicon divergence.
Rule: checks on signals that can legitimately be X/Z during the checked window must handle
the X case explicitly (`===`/`$isunknown`, or resolve-and-assert-known first).

**`[NO-ORDER-DEPENDENCE]`** — a test depends on state left behind by an earlier test in the
same sim/regression session (skipped re-init, inherited configuration, warm memory): it
passes only in one ordering and breaks when run standalone or reshuffled.
Tells: no reset/init at test start; comments like "must run after X"; standalone run fails
while the regression passes.
Rule: every test establishes its own entry state (or the card documents an explicit,
approved test-chain contract).

---

## 2. DV shortcuts to avoid (sim-vs-silicon divergence)

A **shortcut** bypasses the real hardware path with a DV-only substitute for sim speed or
convenience (backdoor / force / skip / scaled time / sim-only path / behavioral stub).
Shortcuts are not always forbidden — but every shortcut on a proof path must pass the two
governing questions from the `dv_shortcut_audit` risk rubric, and an undocumented shortcut on
a proof path is a finding:

1. **No-HW-equivalent** — does it substitute for a mechanism that does not exist in silicon?
   If yes, it can never support a `PROVEN` grade (Critical).
2. **Real-path-unverified** — is the real path ever verified by at least one test with the
   shortcut OFF? If never, the shortcut masks the feature: affected checkers cannot claim
   `LIVE` proof.

**`[NO-UNJUSTIFIED-PRELOAD]`** — memory/ROM/TCM/register/efuse/OTP backdoor preload
substituting for the real boot/load/programming path.
Tells: `$readmemh`/`uvm_hdl_deposit` into memory or register arrays, `backdoor_dccm/iccm`,
`+*_HEX_FILE`, `+*preload_efuse`/`shadow_reg`, and scrub-disable build defaults that only work
because of the preload (`DCCM_SCRUB_BYTES ?= 0`).
Real case (`sep_rom_non_secure_boot_test`): the `.data`/`.rodata`→DCCM backdoor substitutes
for a HW data-init mechanism that **does not exist in silicon** (ROM is IFU-only; LSU/DMA
cannot read it) — Critical / no-hw-equivalent. Time-0 program-image load remains a standing
approved exception (§6).

**`[NO-FORCED-INTERNAL-STATE]`** — `force`/`release`, `uvm_hdl_force`/`uvm_hdl_deposit` on
internal DUT state, key/seed/RNG injection (`+*_HACK`, pinned seeds standing in for real
entropy), and clock/reset forcing (forced PLL lock, bypassed reset sequencing). This is the
shortcut face of `[NO-BACKDOOR-WRITE]` (§1) and follows the same exception process (§6).

**`[NO-SKIPPED-REAL-SEQUENCE]`** — skipping a real boot/init/calibration/training step.
Tells: `+*SKIP*`/`+*BYPASS*` plusargs, `skip_fuse_sense`, `keep_default_init`, ifdef-wrapped
skip branches. A checker downstream of a skipped step cannot claim `LIVE` proof of the
skipped step's feature.

**`[TIME-SCALING-QUALIFIED]`** — timeout/wait/iteration scaling and fast-clock configs
(shortened counters, reduced dividers, power-on-time shrink) are acceptable **only** when the
scaled quantity is not itself the verified behavior and the scaling is visible: the
controlling plusarg/define is named on the card, not buried in a Makefile or TB default.

**`[NO-SIM-ONLY-RTL-PATH]`** — `` `ifdef SIM ``-style branches that change the active
datapath mean the verified config ≠ the tapeout config; such a path cannot support closure
for the real config. Pure synth-stripped assertion/coverage/waveform code is excluded (zero
silicon risk); a deliberately disabled check is `[NO-DISABLED-CHECKER]` (§1), and an outer
synthesis guard does not make a disabled check safe.

**`[BEHAVIORAL-STUB-DECLARED]`** — a behavioral/DPI model or stub replacing a real IP on a
DUT-critical interface (crypto DPI models, vendor OTP models) must be declared on the card. A
checker whose proof path crosses a stubbed interface cannot claim `LIVE` proof of the stubbed
IP's behavior; closure use needs designer signoff.

**Peer-audit note:** shortcuts that are *present but never activated* by any test in the
testlist are surfaced during peer audit rather than silently ignored — an unexercised backdoor
is often the most dangerous kind.

---

## 3. Severity mapping *(pilot default)*

| Severity | Rules | Effect on Skill 2 | Effect on Skill 3 result |
|---|---|---|---|
| **Blocking** | all §1 F-group rules (`[NO-FABRICATED-VERDICT]`, `[NO-ALWAYS-PASS-CHECKER]`, `[NO-BACKDOOR-WRITE]`), `[NO-SKIP-TO-PASS]`, `[MUST-FAIL-ON-MISMATCH]`, `[NO-DISABLED-CHECKER]`, `[NO-WRONG-TARGET]`, `[TIMEOUT-MUST-FAIL]`, `[NO-ZERO-ACTIVITY-PASS]`, `[NEGATIVE-NEEDS-POSITIVE-CONTROL]`, `[INDEPENDENT-EXPECTED-MODEL]`, `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, `[CONTRACT-MATCH]`, `[BUILD-MODEL-IDENTITY]` | affected checker cannot be `PROVEN`; recommendation `NOT-READY` | blocking → `FAIL` (real gap / false-PROVEN class) |
| **Major** | `[NO-EMPTY-PHASE]`, `[REGRESSION-ENROLLED]`, `[EXACT-EXPECTATION]`, `[EVIDENCE-TOKEN-CONDITIONAL]`, `[NO-BLIND-DELAY-SYNC]`, `[SEED-REPRODUCIBLE]`, `[X-AWARE-CHECK]`, `[NO-ORDER-DEPENDENCE]`, `[LIVENESS-COMPLETENESS]` | affected checker not `PROVEN` until fixed | `PASS-WITH-FINDINGS` at most; blocking if it affects a required scenario |
| **Minor** | style, layering, duplication, and dead-code findings: `[REUSE-AND-LAYERING]`, `[NO-DUMMY-DEAD-CODE]` | reported; does not block the checker | `PASS-WITH-FINDINGS` |
| **Shortcut rules (§2)** | per the two governing questions | no-HW-equivalent → affected checker can never be `PROVEN` (Blocking); real-path-unverified → no `LIVE` proof claim (Major); documented + qualified use → reported only | no-HW-equivalent on a required scenario → `FAIL` |

**Conditional adjustments.** A few tags carry a different severity depending on what the
violation actually costs:
- `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — Blocking when the literal resolves to a different
  register or to unmapped space (the evidence asserts a false identity). Major when the address
  is correct but hand-copied rather than sourced from the generated map (latent rot only).
- `[NO-DUMMY-DEAD-CODE]` — Minor by default. Major when the dead code *resembles an active
  check* (an expected value computed but never compared, a commented-out assertion left in
  place), because a reader reasonably concludes that checking happens when it does not.
- `[CONTRACT-MATCH]` — Blocking as a contract defect (the card names a producer or value the
  implementation does not use); route it to Skill 1 for regeneration, never patch it in the
  test. In `MODE=NO-CHECKBOX` the *absence* of a card is already carried by the mode and the
  mandatory `NOT-READY`; do not additionally file it as a finding, which double-counts one
  fact.

**Default for any obligation tag not listed above.** The severity follows what the violation
does to the proof, not how hard it is to fix:
- the checker's proof does not hold without it → **Blocking**
- the proof still stands but is measurably weaker or unreproducible → **Major**
- only style, layering, duplication, or dead code is affected → **Minor**

**Unmapped tags are a policy bug, not auditor discretion.** If a tag cannot be placed by the
explicit rows or the default rule above, the auditor records the severity as
`UNMAPPED-IN-POLICY`, states which of the three effects it believes applies, and proceeds —
it never invents a severity. Auditors run in fresh contexts and cannot see each other, so an
invented severity silently diverges between reports. Each `UNMAPPED-IN-POLICY` occurrence is an
action item for the policy owner to resolve here.

---

## 4. Vocabulary *(pilot minimal set)*

This section is the **shared dictionary for checkbox-card attributes**, not a Layer-1
fake-pass checklist (§1–§2). It defines the only legal values for fields such as
`evidence_class` and `closure_tier`, plus what counts as an authoritative SPEC source and
the environment's frontdoor/stimulus policy quoted into card `GUARDRAILS`.

**How Skills use it:**

| Skill | Role |
|---|---|
| **Skill 1** | **Writes** these values onto each candidate card (or `TBD-` if this policy is unset). A card cannot be approved while a vocabulary field remains `TBD-`. |
| **Skill 2** | **Does not invent** vocabulary here. It reads the values from the **approved card** and grades evidence against that declared bar (Layer 2). Layer 1 structural audit uses §1–§2, not this section. |
| **Skill 3** | **Does not invent** vocabulary here. It uses approved-card `closure_tier` / evidence class for sampling priority and closure judgment, and enforces the frontdoor/observation vocabulary as environment policy. |

Humans choose the per-card values (via Skill 1 draft + card approval) from this table; auditors
must not silently upgrade or downgrade them.

**Evidence classes:**

| Class | Meaning |
|---|---|
| `strict-e2e` | end-to-end behavior proven force-free at architecturally visible boundaries, with cycle-adequate observation |
| `frontdoor-func` | functional behavior proven through the approved frontdoor path; passive hierarchical reads allowed |

**Closure tiers:**

| Tier | Meaning |
|---|---|
| `A` | required for milestone closure; sampled by peer audit with priority |
| `B` | required; routine sampling |
| `C` | advisory/stretch; never blocks closure |

**Milestone vocabulary:**

The normative four (DV_SKILL1_SPEC.md §3). A pin carrying any other value is invalid, not a
guess to be resolved — the milestone bounds which scenarios this run's testcase set must
close, so an unrecognised one silently changes the plan's denominator.

| Milestone | Meaning |
|---|---|
| `P0` | bring-up / observability |
| `P1` | nominal function |
| `P2` | feature / error breadth |
| `P3` | corner / stress / gaps |

**Review budget:**

Countable limits, per DV_SKILL1_SPEC.md §4.2 and §4.7 rule 6. These are counts and not
minutes on purpose: a generator cannot evaluate a review-time target, and two reviewers will
not apply one consistently, so time can never be the thing conformance is measured against.
A card exceeding a per-card limit must be split or carry an explicit `size_justification` on
its testcase record; a packet exceeding `max_rows_per_packet` / `max_cards_per_packet` is a
generation finding and must be split by area or by anchor.

| Limit | Value |
|---|---|
| `max_steps_per_card` | 12 |
| `max_checkers_per_card` | 12 |
| `max_cards_per_packet` | 16 |
| `max_rows_per_packet` | 120 |

**Authoritative SPEC sources:** in-repo `.adoc`/`.md` under `hw/*/doc/` and `doc/` at a pinned
git revision. RTL, DV code, VPLANs, and testcases are never SPEC sources.

**Frontdoor / stimulus policy (SMU_SEP):** firmware-first stimulus; TB touches only top-level
pins and approved external-master ports. Passive hierarchical reads are allowed for
observation; internal writes/forces/deposits are backdoor (§1 `[NO-BACKDOOR-WRITE]`).

---

## 5. Authoritative PASS definition *(pilot, SMU_SEP cocotb)*

A run counts as PASS for Skill 2 entry only when **all** hold:

1. the cocotb result summary reports the test passed (no `FAIL`/`ERROR` result records);
2. the testcase's own final assertion gate executed (e.g. `assert not errors` plus the
   expected proof-line count, where the test defines one);
3. zero unexplained `ERROR`/`FATAL`/`Traceback` records in the kept log — the only accepted
   suppressions are those listed in an approved exception record;
4. process exit code alone is never sufficient.

Kept log location: the testbench's standard `sim_output/`/log path for the run; the log file
(and its content hash) is part of the evidence manifest.

---

## 6. Exceptions, freshness, and separation *(pilot defaults)*

**Backdoor/observation exception record** (required for any `[NO-BACKDOOR-WRITE]` escape):
approver (human), reason, why frontdoor is impossible, exact path/operation scope, approval
revision, review/expiry revision. Missing or scope-exceeded records fail the affected checker.
Time-0 memory preload via `$readmemh`/`+SEP_ITCM_HEX_FILE` of the program image is a standing
approved exception for SMU_SEP (initial-state load, not runtime behavior).

**Finding waiver (Skill 2, per testcase):** a Layer 1 finding the owner has reviewed and
accepted for now. It is recorded in the grade report's `waivers:` array with four fields —
`tag`, `path`, `reason`, `approved_by` — and carried into the next round's report only when
`approved_by` is non-null, which is what keeps the human, not the auditing skill, the author
of the carve-out. Its only effect is presentational: the finding is still detected, still
listed, and still shown in the Layer 1 matrix (as `waived`, never `clean`), but it leaves the
owner's action list and stops blocking the evidence-closed recommendation.

Two limits make it safe to use freely. **A `Blocking` finding may not be waived this way** —
Blocking means the checker's proof does not hold, and silencing it is how a fake pass reaches
a green report; route it to an approved-card `[BY-DESIGN-EXCEPTION]` or to a Skill 3
requirement waiver. **A waiver never changes a checker grade** — a finding listed in a
checker's `finding_ids` keeps that checker un-proven regardless. Removing a *scenario* from
the closure denominator remains Skill 1's accepted plan row or Skill 3's requirement-waiver
record; a finding waiver never touches coverage.

**Freshness:** evidence is `STALE` when any of SPEC revision, card revision, testcase source,
build/config identity, or the kept log's hash no longer match the audited set, or when a
linked issue changes state.

**Fresh context *(mandatory, unconditional)*:** every Skill (1/2/3) invocation MUST run its
substantive work in a fresh context with no carryover from any session that authored, audited,
generated, or even substantively *discussed* the IP's features / expected values / gaps. This
is unconditional — it applies even when the current session never wrote the artifact, because a
formed opinion contaminates judgment as surely as authorship does (the pilot proved it: a
context that had discussed an IP's coverage gaps reproduced exactly those gaps). Enforce it by
dispatching the whole workflow to a fresh subagent that receives only the neutral inputs (pin /
artifact / spec paths + the `SKILL.md`) and no conversational history, or by refusing and
requiring reinvocation in a new session. This is the **load-bearing separation requirement.**

**Model separation *(optional / best-effort)*:** author and auditor model tuples SHOULD be
recorded honestly on every artifact, but a differing model is **not required** and never blocks
a grade or verdict. Rationale: in a single-provider harness the only way to "differ" is to
downgrade the auditor to a weaker family, which tends to lose more real findings than the model
diversity gains; and empirically the independence that matters comes from the fresh context
above, not from different weights. A team MAY still elect cross-family review as an optional
escalation for closure-critical checkers; if so, record the tuple and the reason. Legacy
testcases with unknown author provenance: Layer 1 audit always runs; Layer 2 grading is
permitted with the report marked `provenance: legacy`.

---

## 7. Sampling and thresholds *(pilot defaults — tune after first iteration)*

| Item | Pilot value |
|---|---|
| Skill 1 citation spot-check (A1) | 10 features or 100%, whichever is smaller |
| Skill 3 PROVEN re-verification floor | all tier-`A` checkers + 20% random sample of the rest (min 5) |
| Escalation on a false-PROVEN | full re-verify of that behavior class, capped at 20 checkers before human escalation |
| Randomized checkbox adequacy | every `required_cells` value of the mapped scenario hit in the retained logs. **No seed floor**: how many seeds are run is the regression owner's scheduling decision, reported as context and never graded. An unreached cell is a stimulus defect, not a shortage of seeds. |
| Artifact freeze for peer audit | none for the pilot (single-IP, single-owner) |
| Review packet budgets (**enforced**) | the countable limits in §4 "Review budget" — 12 steps / 12 checkers per card, 8 cards / 40 rows per packet |
| Reading time (courtesy only, never the enforcement basis) | designer feature packet ≈ 30 min; Skill 2 report ≈ 5 min; Skill 3 executive+blocking ≈ 15 min |

---

## 8. Revision control

This policy is pinned by git revision. Every Skill 1/2/3 artifact records
`quality_policy: {path, revision}`. Changing this file is a formal, reviewed change: audits
already performed remain valid against the revision they cite; new audits use the new
revision. Undefined terms are not left to auditor discretion — if a needed rule or threshold
is missing here, the audit reports `INSUFFICIENT-EVIDENCE` for the affected judgment and the
gap is fed back into this policy.
