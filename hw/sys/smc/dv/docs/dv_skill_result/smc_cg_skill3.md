<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — Skill 3 Steps and Results

- **IP**: `SMC_CLOCK_GATING`
- **Milestone**: `P1`
- **Skill**: `dv_peer_audit` (Skill 3)
- **Board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **Status**: **P1 re-opened by independent re-review** — advisory **`FAIL`** (2 required REAL-GAP).
  Prior advisory `PASS` + owner signoff `minshaoho` @ `2026-08-05T14:28:00+08:00` remains in the record, but is
  superseded by this fresh-context re-review; whether the board changes is an owner decision (Skill 3 has no signoff authority)
- **Last updated**: 2026-08-05
- **Report**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md`
- **Reverse inventory**: `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md`
- **Reverse inventory agent**: [Reverse inventory SMC CG](12817b98-d1fd-49bb-93f0-ac94f37ca022)
- **Skill 3 FAIL agent**: [Skill3 re-review reverse inv](acef077d-92a4-4ff4-8ca6-5856cfaed726)
- **Skill 3 final agent**: [Relaunch Skill3 final review](8e56f4a0-dfe9-4a4c-ab22-fee895088f9f)

## 1. Entry conditions (gates)

Skill 3 is a milestone / IP peer audit and should start only after:

1. Skill 1 contract is approved (done — see `smc_cg_skill1.md`; including INT-ZEROER amend).
2. All in-milestone cards in the plan have a runnable test + kept log (Skill 1.5).
3. Every card has a Skill 2 grade; target is acceptable closure (PROVEN / signed deferral), with no open Blocking.
4. Owner has decided:
   - DMA FIND-001…005 rework + re-audit
   - `SMC_CG_TEST_MODE_BYPASS_TEST` PASS + audit after `prim_clkgater` `i_te` fix
   - FIND-001 amend → `smc_zeroer_cg_indep_test` impl + Skill 2
5. Board arrow moved to Skill 3.

**Entry state (this final re-review)**: 8/8 Skill 2 grades are `EVIDENCE-CLOSED-AWAITING-SIGNOFF`; force/deposit owner constraint recorded clean in each grade; FL r2 approved with `INT-ZEROER-CG-INDEP`.

## 2. Execution steps (this run — final re-review after amend)

1. Fresh Skill 3 subagent (model `cursor-grok-4.5`; `run_id` ≠ all prior participants, including prior peer audits / reverse inventory / amend / indep impl+audit).
2. Freeze hashes: pin / feature_list r2 / plan / cards / grades×8 / quality policy / testlist `clock.toml` / pinned SPEC paths / reverse inventory.
3. Mode determination: `CHECKBOX-MAPPING` (approved FL + approved plan + approved cards; pin/plan milestone both P1).
4. `closure.py` union-coverage: denominator **19 of 23** (4 signed `OUT-OF-MILESTONE` → `MILESTONE-DEFERRED` excluded); **covered 19/19**; allocation intent / proof-class / cells all clean; `INT-ZEROER-CG-INDEP` ← `CHK-ZINDEP-DECOUPLE`.
5. Cross-testcase / O2 / E3: no conflicts; 8 anchors all in `hw/sys/smc/dv/testlists/clock.toml`; sampled PROVEN re-verify (17 tier-A + 10 tier-B; 27/27 token hits); sequence force/deposit scan clean.
6. Reverse inventory **diff** (do not re-derive): candidate vs sealed FL r2 → packaging CLEAN; **INT-ZEROER-CG-INDEP → CLEAN** (cells match).
7. Update `SMC_CLOCK_GATING_PEER_AUDIT.md` (including **DELTA** vs prior FAIL); `schema_check` → `valid`; `render_lint --kind peer-audit` → `agree`.
8. Update board + this file.

## 3. Results

| Item | Result |
|---|---|
| Peer-audit run_id | `dv_peer_audit-SMC_CLOCK_GATING-P1-20260805T141900+0800-fresh-grok45-final` |
| Model | cursor / grok / 4.5 |
| Mode | `CHECKBOX-MAPPING` |
| Union coverage | **19/19** required keys PROVEN (inventory 23; excluded 4 → P2) |
| Reverse-diff disposition | **CLEAN** |
| Blocking gaps | 0 REAL-GAP / 0 BLOCKED |
| Advisory verdict | **`PASS`** |
| Report path | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PEER_AUDIT.md` |
| schema_check / render_lint | `valid` / `agree` |

### DELTA vs prior Skill 3 (`…130700+0800…` / `FAIL` / CONFIRMED-OMISSION)

| Item | Prior | Now |
|---|---|---|
| FL | r1 · `interactions: []` | **r2 · INT-ZEROER-CG-INDEP** |
| Grades | 7 | **8** (+ indep 2/2 PROVEN) |
| Union coverage | 18/18 of 22 | **19/19 of 23** |
| Reverse disposition | CONFIRMED-OMISSION | **CLEAN** |
| FIND-001 | Blocking | **cleared** |
| Result | FAIL | **PASS** |

### Frozen hashes (summary)

| Artifact | content / file sha256 |
|---|---|
| feature_list (content_sha256) | `a22b78b40765efe57912f03934312f6b07a8582c351fa97c4ff0169d49bcca20` |
| testcase plan (content_sha256) | `23856412227c96ff9b0ac8e23dc49901183c598bad8b9e5e3d9a49914686edcd` |
| cards (content_sha256) | `c097f008eb7eb94183188970bf1c95c21977bc6c721f0b9bc65d735324834f69` |
| quality policy | `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75` |
| pin file (raw) | `d6800e9969c71c359b003b166f3004c7cde592843f2fadbd0653f9167c02b2f3` |
| reverse inventory (content_sha256) | `535b4a2d146baf5f1c822ecc0588516d0016b92fe18725e5d626558c711eef92` |
| reverse inventory (raw file) | `66bb946be0bd01be55378d109202ed8554e03714733f106e05fe6edbffee2a7d` |
| combined SPEC (concat) | `1dc1b2229d99fe54e4cd98d661b827d41cb40e213cfef1d9c5ac6d60d6cc9d26` |
| grade smc_zeroer_cg_indep_test | `e19a9e288bd1b764b9fa3c96cce9513d03a403e69384653ad57e769309ccf220` |

## 4. Known OUT-OF-MILESTONE (not counted in P1 closure)

From Skill 1 plan (already signed; Skill 3 counts as `MILESTONE-DEFERRED`, not a gap):

- DMA-CG-CTRL.S5 / S6 (hyst sweep / race) → P2
- ZEROER-AXICLK-CG.S5 / ZEROER-REGCLK-CG.S5 (race) → P2

## 5. Next actions

```text
# P1 Skill 3 advisory PASS — optional human signoff.
# When starting P2 (deferred races / hysteresis breadth):
/dv_vplan_gen \
  --pin hw/sys/smc/dv/tb/SMC_CLOCK_GATING_PIN.yaml \
  --milestone P2 \
  --planning-dir hw/sys/smc/dv/tb \
  --board hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md
```

### 5.1 Reverse inventory candidate — produced and already diffed (2026-08-05)

Fresh, anchor-blind Skill 1 subagent (model `cursor / claude / sonnet-5`; run_id
`dv_vplan_gen-SMC_CLOCK_GATING-reverse-inventory-20260805T121100+0800-fresh-claude-sonnet5`)
produced the reverse feature inventory without ever opening
`SMC_CLOCK_GATING_PIN.yaml`, any `SMC_CLOCK_GATING_*.md` artifact, grade, peer-audit
report, or testlist. Inputs were the 9 pinned `hw/sys/smc/doc/` SPEC sources plus the
boundary text only.

| Item | Value |
|---|---|
| Output path | `hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md` |
| Status | `candidate` (no approvals, no allocations, no ticked boxes) |
| Features / scenarios / interactions | 6 / 18 / 1 |
| SF-* findings | 5 (`SF-001`..`SF-005`; 1 High, 2 Medium, 2 Low) |
| Skill 3 disposition (prior FAIL) | CONFIRMED-OMISSION on `INT-ZEROER-CG-INDEP` |
| Skill 3 disposition (this PASS) | **CLEAN** — FL r2 contains matching interaction + cells |

## 6. Independent re-review (2026-08-05, third Skill 3 run) — advisory `FAIL`

Executed by a **different human + different model** in a brand-new read-only context, without inheriting any prior Skill 3 conclusion.

| Item | Result |
|---|---|
| Peer-audit run_id | `dv_peer_audit-SMC_CLOCK_GATING-P1-5aa9c629a618-fresh-opus5-rereview` |
| Reviewer / Model | `brucehsu` / anthropic · claude · opus-5 (prior was `minshaoho` lineage / cursor · grok · 4.5) |
| Mode | `CHECKBOX-MAPPING` (pin `milestone: P1` == plan `milestone: P1`, gate confirmed) |
| Denominator | inventory **23** − excluded **4** = required **19**; **covered 17** |
| REAL-GAP | **2** — `SMC-CG-ARCH-PARAMS.S3`, `CG-DFT-TEST-BYPASS.S2` |
| Findings | **5 🔴 Blocking · 12 🟠 Major · 2 🟡 Minor** |
| Reverse-diff disposition | **CLEAN** (key-level clean; cell-level diff also done, 8 advisory P2 candidate cells) |
| Advisory verdict | **`FAIL`** |
| schema_check / render_lint | `valid` / `agree` |

### 6.1 Why this differs from the prior `PASS`

Prior-run coverage arithmetic (19/19) was correct at the key level; the deltas all come from **three checks the prior run did not do or did not pass**:

1. **Contract vs implementation diff (intent mode `O2`)** — `SMC-CG-ARCH-PARAMS.S3` (enable-threshold, intent explicitly
   *"independent of the hysteresis count"*) was actually measured using the **same field**
   `CLOCK_GATE_CONTROL.CG_HYSTERESIS` for the same re-gate delay; `smc_static_cg_sanity_test_seq.py:22` itself says
   `# SF-002: Enable Threshold == Hysteresis Control (same programmable field).`, and its values {8,63} are a
   subset of `.S1` {8,31,63}. One measurement credited to two required keys → `.S3` judged **REAL-GAP**, routed back to Skill 1
   (**must not** change the test).
2. **Preconditions (negative needs positive control)** — `CG-DFT-TEST-BYPASS.S2` never proved in the same run that both
   Zeroer clocks "would have been gated"; that file's `_program_cg` is the only version in the whole slate **without CSR readback**,
   and never checked `tb_zeroer_cg_en == 1` → **REAL-GAP**. (DMA leg has positive control, so the asymmetry is an objective fact.)
3. **independent-evidence gate was derived, not self-declared** — 17 `closure_tier: A` checkers have only a
   single seed / single log; all 153 `seed` entries under `build/runs/` are `1`; multiple run dirs are same-seed reruns and earlier ones are
   `FAIL`/`ERROR`. Prior report still wrote `gate_satisfied: true` with `required: false` / `method: NOT-REQUIRED` / all provenance `null`.

Two more items visible only by reading the working tree:

- **F1 build-model identity** — `hw/common/och_prim_generic/rtl/prim_clkgater.sv:20` was changed to
  `latched_en = i_en | i_te;` (already recorded in this file §1 item 4 as an owner decision, not a stealth change), but all 8 grades record
  `repository_revision: 2ecc7b227e39` (without this change), `compile_inputs_sha256: null`, `exceptions: []`;
  `tb_top.sv` modified, 13 cocotb files untracked. → Evidence cannot be rebuilt from any reviewable revision, and shared common
  RTL correctness needs design-owner approval.
- **F5 always-pass proof line** — `CHK-TIMEOUT-PATHS` fields are all constants with no comparison, yet listed in two tests'
  required-token final gates.

### 6.2 Parts verified clean (prior conclusions hold on these axes)

Evidence integrity: 8/8 log hashes match, **27/27** tokens hit verbatim at declared line numbers, 19/19 coverage artifact hashes match,
0 `ERROR`/`FATAL`/`Traceback`; **no forged or misplaced evidence tokens found**, so the §4.5
behaviour-class full re-verify upgrade path was not triggered. Cross-testcase claim matrix has no conflicts; force-free clean
(only DUT writes are `rst_cool_ni` / `tb_test_en_i`, both TB top-level input pins); proof class all `LIVE`
with no over-credit; `[MERGED-EVIDENCE]` clean (interaction takes its own credit; each of the two features has standalone proof);
8 anchors all enrolled; card↔grade `record_sha256` all match, including DMA card revision 2.

### 6.3 Four OUT-OF-MILESTONE deferrals remain valid

`DMA-CG-CTRL.S5/S6`, `ZEROER-AXICLK-CG.S5`, `ZEROER-REGCLK-CG.S5` are all approved-plan
`OUT-OF-MILESTONE` / `downstream_class: out-of-scope` with `accepted_by`, mapped to `MILESTONE-DEFERRED`
(**not** closure-blocking `OUT-OF-SCOPE`), not counted as gaps, `closes_at_milestone: P2`.

**But P2 must also inherit (F17)**: the only untouched cell of `DMA-CG-CTRL.S5` is `dma_hysteresis_0`, and the test source
notes that `hyst=0` "never runs under cg_enable" and `hyst=1` "loses the frontend→backend handoff". That row is therefore
not a pure breadth deferral and may hide a design issue.

### 6.4 Questions to hand back to the designer

1. Is `prim_clkgater` `i_en | i_te` the correct DFT bypass for shared common RTL, and can it be committed?
2. SF-002: is there an independent enable-threshold field, or is `CG_HYSTERESIS` the only programmable delay?
3. Is DMA behavior at `CG_HYSTERESIS = 0` / `= 1` as expected?
4. Is `clk_periph` clock-gated? (pin boundary says in scope, but no approved artifact answers;
   approved `SF-003` only answered `clk_ref_i` / `clk_telemetry_i`, while the anchor-blind reverse derivation pointed at
   `clk_periph`.)

### 6.5 Next actions (replaces §5)

```text
# P1 is not yet closed. Address the 5 Blocking items first:
#   F3 → Skill 1 amend (merge S3 into S1 or rewrite as an independent field); do not change the test
#   F2 → smc_cg_test_mode_bypass_test_seq: add Zeroer positive control + CSR readback, then Skill 2
#   F1 → design owner decides commit/revert for prim_clkgater; commit tb + cocotb sources;
#         re-run all 8 tests on a reviewable revision; grades record non-null compile_inputs_sha256
#   F4 → 17 tier-A checkers need reproduce-from-seed or independent observation
#   F5 → remove CHK-TIMEOUT-PATHS (or emit only after a real comparison)
# After that: re-run Skill 2 (affected cards) → then Skill 3 re-review.
```

---

*This file is a process record. The formal peer-audit advisory conclusion is authoritative in `SMC_CLOCK_GATING_PEER_AUDIT.md`.*
