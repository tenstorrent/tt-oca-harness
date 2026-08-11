<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMC_CLOCK_GATING — DV Skill Flow Overview (Plan → Impl → Audit → Re-audit)

- **IP**: `SMC_CLOCK_GATING`
- **Milestone example**: `P1` (Done)
- **Purpose**: Fully describe Skill 1 plan, Skill 1.5 impl, Skill 2 audit, Skill 3 peer audit, and the **rework / re-audit / amend / re-review** loops
- **Detail records**: `smc_cg_skill1.md` · `smc_cg_skill2.md` · `smc_cg_skill3.md`
- **Status board**: `hw/sys/smc/dv/tb/audit_status_smc_clock_gating.md`
- **Last updated**: 2026-08-05

> All flow diagrams in this file use **ASCII lines** (no Mermaid rendering dependency).

---

## 0. One-line chain

```
SPEC + Pin
  -> Skill 1 contract (FL / Plan / Cards) + Owner approve
  -> Skill 1.5 impl + kept log tokens
  -> Skill 2 first-pass grade
       |-- NOT-READY --> 1.5 rework --> Skill 2 re-audit  (multi-round OK)
       |-- contract wrong --> Skill 1 amend --> then 1.5 --> 2
  -> After all cards CLOSED: Skill 3 peer
       |-- no reverse --> independent reverse inventory --> Skill 3 re-review
       |-- FAIL omission --> Skill 1 amend --> 1.5 --> 2 --> Skill 3 re-review
  -> Owner signoff -> Milestone Done
```

If a child session stalls: CANCELLED, then relaunch the **same skill**; do not revoke an already-approved contract.

---

## 1. End-to-end flow (including re-audit / re-review)

```
                    +------------------+
                    |  Pin confirmed   |
                    |  Pinned SPEC     |
                    |  Quality policy  |
                    +--------+---------+
                             |
                             v
                    +------------------+
                    | Skill 1 Plan     |
                    | draft FL/Plan/   |
                    | Cards/packets    |
                    +--------+---------+
                             |
                             v
                    +------------------+
              +---->| Owner approve?   |----+
              |     +--------+---------+    |
              |              | yes          | no (candidate fix)
              |              v              |
              |     +------------------+    |
              |     | Skill 1.5 Impl   |<---+  (also from amend
              |     | one approved card|         after re-approve)
              |     +--------+---------+
              |              |
              |              v
              |     +------------------+
              |     | Sim + kept log   |
              |     +--------+---------+
              |              |
              |              v
              |     +------------------+
              |     | All CHK tokens?  |
              |     +--+------+--------+
              |   no   |      | yes
              |   (contract)  |
              |        |      |    no (impl bug)
              |        |      |         |
              |        v      |         v
              |  Skill1 Amend |  Skill1.5 Rework ----+
              |        |      |         |            |
              |        |      |         +----------->|
              |        |      |              (re-run sim)
              |        |      v
              |        |  +------------------+
              |        |  | Skill 2 Fresh    |
              |        |  | audit (NEW id)   |
              |        |  +--------+---------+
              |        |           |
              |        |           v
              |        |  +------------------+
              |        |  | Grade result?    |
              |        |  +--+------+--------+--+
              |        |     |      |           |
              |        |  NOT-READY CLOSED   stalled
              |        |     |      |           |
              |        |     v      |           v
              |        |  class FIND|     Cancel +
              |        |     |      |     relaunch Skill2
              |        |     +------+-----------+
              |        |     | impl | contract  |
              |        |     v      v           |
              |        |  Rework  Amend---------+--> Skill1
              |        |  1.5       |
              |        |     |      |
              |        |     v      |
              |        |  new log   |
              |        |     |      |
              |        |     +------+--> Skill2 re-audit
              |        |                    |
              |        |           CLOSED   |
              |        |              |     |
              |        |              v     |
              |        |     +------------------+
              |        |     | More cards open? |
              |        |     +--+-----------+---+
              |        |    yes |           | no
              |        |        v           v
              |        |   Skill1.5    +------------------+
              |        |   next card   | Skill 3 Fresh    |
              |        |               | peer audit       |
              |        |               +--------+---------+
              |        |                        |
              |        |                        v
              |        |               +------------------+
              |        |               | Peer result?     |
              |        |               +--+----+----+-----+
              |        |                  |    |    |
              |        |         INSUFF. FAIL PASS stalled
              |        |           |      |    |    |
              |        |           v      |    |    v
              |        |    Reverse inv.  |    | Cancel+
              |        |    (indep S1)    |    | relaunch S3
              |        |           |      |    |
              |        |           v      |    |
              |        |    Skill3        |    |
              |        |    re-review ----+    |
              |        |           |           |
              |        |           +----FAIL---+--> Skill1 Amend
              |        |                        |     (omission)
              |        |                        |           |
              |        |                        |           +--> 1.5 --> S2 --> S3 re-review
              |        |                        v
              |        |               +------------------+
              |        |               | Owner signoff    |
              |        |               +--------+---------+
              |        |                        |
              |        |                        v
              |        |               +------------------+
              |        |               | Milestone Done   |
              |        |               +------------------+
              |        |
              +--------+  (amend path returns to Skill1 draft)
```

---

## 2. Re-audit / Re-review detail diagrams

### 2.1 Skill 2: audit ↔ rework ↔ re-audit (multi-round OK)

```
  [Impl done: tokens in log]
            |
            v
  +---------------------+
  | Fresh Skill2 audit  |  <---+  (stalled: cancel + relaunch)
  | NEW auditor.run_id  |------+
  +----------+----------+
             |
             v
      +------+------+
      | recommendation |
      +--+--------+--+
         |        |
    NOT-READY   EVIDENCE-CLOSED
         |        |
         v        v
  +-------------+  +------------------+
  | Grade FIND |  | Grade + DELTA   |
  | list        |  | (if re-audit)    |
  +------+------+  +--------+---------+
         |                   |
         v                   v
  +-------------+     Owner signoff
  | Class FIND  |            |
  +--+-------+--+            v
     |       |         (card done)
  impl/    contract
  exact    wrong
     |       |
     v       v
 Skill1.5  Skill1
 Rework    Amend
     |       |
     v       v
 New kept  New/revised
 log sha   card --> Impl --> (back to Fresh Skill2)
     |
     v
 Fresh Skill2 RE-AUDIT ----+
 (must cite prior FIND     |
  CLOSED in DELTA)         |
     |                     |
     +---------------------+
             |
        still NOT-READY? --> another rework round
        CLOSED? ----------> next card / Skill3
```

### 2.2 Skill 3: peer ↔ reverse ↔ re-review ↔ amend

```
  [All Skill2 grades CLOSED]
            |
            v
  +---------------------+
  | Fresh Skill3 peer   | <---+ (stalled: cancel + relaunch)
  +----------+----------+     |
             |                |
             v                |
      +------+------+---------+
      | peer result |
      +--+----+----+--+
         |    |    |
        IE   FAIL PASS
         |    |    |
         v    |    +--> Owner signoff --> Done
  No reverse  |
  artifact    |
         |    |
         v    |
  +---------------+
  | Independent   |
  | Skill1 reverse|
  | inventory     |
  | SPEC+boundary |
  | only          |
  +-------+-------+
          |
          v
  +---------------+
  | Skill3        |
  | RE-REVIEW     |
  | + DELTA       |
  +--+----+-------+
     |    |
   FAIL  PASS --> signoff --> Done
   omission
     |
     v
  +---------------+
  | Skill1 AMEND  |
  | add missing  |
  | interaction    |
  +-------+-------+
          |
          v
  Owner approve
          |
          v
  Skill1.5 impl new/changed card
          |
          v
  Skill2 audit (+ re-audit if needed)
          |
          v
  Skill3 RE-REVIEW again -----> PASS or more amend
```

### 2.3 Actual timeline for this IP (line form)

```
Skill1.5 Impl
    |
    v
Skill2 Audit -----------> NOT-READY (FIND-001..N)
    |
    v
Skill1.5 Rework wave ---> new kept logs
    |
    v
Skill2 Re-audit --------> EVIDENCE-CLOSED  (x7 then x8)
    |
    v
Skill3 Peer ------------> INSUFFICIENT (no reverse)
    |
    v
Reverse Inventory -------> candidate file
    |
    v
Skill3 Re-review -------> FAIL (INT-ZEROER omission)
    |
    v
Skill1 Amend -----------> INT-ZEROER-CG-INDEP + new card
    |
    v
Owner approve
    |
    v
Skill1.5 Impl indep ----> kept log 1c39f29a...
    |
    v
Skill2 Audit indep -----> 2/2 CLOSED
    |
    v
Skill3 Final re-review -> PASS 19/19 CLEAN
    |
    v
Owner signoff ----------> P1 Done
```

### 2.4 Re-audit / Re-review rules table

| Item | Skill2 re-audit | Skill3 re-review |
|---|---|---|
| Trigger | grade = NOT-READY and new log exists | no reverse / FAIL / after amend |
| Session | Fresh, new run_id | Fresh, new run_id |
| Artifact | same-path grade + **DELTA** | same-path PEER_AUDIT + **DELTA** |
| Forbidden | weaken checker; use old log | peer derives reverse itself |
| After | CLOSED → next card or Skill3 | PASS → owner signoff |

---

## 3. Roles and artifacts

| Stage | Skill | Who | Output | Human gate |
|---|---|---|---|---|
| Plan | Skill 1 `dv_vplan_gen` | Fresh draft | FL Plan Cards packets | Owner approve |
| Impl | Skill 1.5 `dv_test_impl` | Impl session | seq test testlist kept log | choose env |
| Audit | Skill 2 `dv_test_audit` | Fresh auditor | `grades/*_GRADE.md` | Owner signoff |
| Peer | Skill 3 `dv_peer_audit` | Fresh peer | `*_PEER_AUDIT.md` | Owner signoff Done |

Hard constraints: no DUT force/deposit; 1.5 does not grade; 2 does not change the contract; 3 does not derive reverse; one sim at a time in the same workspace.

---

## 4. Skill 1 — Plan

```
Pin confirmed
      |
      v
Fresh Skill1 (draft only)
      |
      v
Freeze feature list
      |
      v
Plan + Cards
      |
      v
Packets + schema_check
      |
      v
   Owner approve?
    |         |
   yes       no --> fix candidate --> back to Fresh Skill1
    |
    v
Handoff Skill1.5
    |
    +---- later: Amendment (DMA S3 / INT-ZEROER) --> re-approve
```

| Event | Behavior |
|---|---|
| Initial approval | 7 cards; 4 defer to P2 |
| DMA S3 amend | card r2 keep-enabled |
| Skill3 FAIL amend | add INT-ZEROER + `smc_zeroer_cg_indep_test` |

---

## 5. Skill 1.5 — Impl and Rework

### 5.1 Initial implementation

```
Approved card
      |
      v
Entry gates OK? --no--> Refuse / back Skill1
      | yes
      v
Env: cocotb + tb_top
      |
      v
Write seq + test + testlist
      |
      v
run_dv.py --> kept log
      |
      v
All CHK tokens in log?
      |                |
     yes              no
      |                |
      v                v
Handoff Skill2    Root cause?
                     |        |
                 contract   impl/sim
                     |        |
                     v        v
               Skill1 Amend  Rework 1.5 --> re-run
```

```bash
module load verilator/5.050 gcc/13.2.1
python3 tools/dv/run_dv.py --dut smc_wrapper --items <anchor> --tool verilator --seed 1
```

### 5.2 Rework from Skill2 FIND

```
Skill2 FIND list
       |
       +-- ADDRESS-FROM-MAP --> use smc_addr_map --------+
       |                                                 |
       +-- EXACT-EXPECTATION --> tighten asserts --------+|
       |                                                 ||
       +-- Vacuous timing -----> measure real windows --+||
       |                                                 |||
       +-- Unobservable step --> Skill1 amend ------------|||--> ...
                                                         |||
                                                         vvv
                                              New kept log + sha256
                                                         |
                                                         v
                                              Skill2 RE-AUDIT
```

Common fixes for this IP: `smc_addr_map.py`, exact `edges==N`, derived tokens, gate-off latency, `prim_clkgater` `i_te` OR.

---

## 6. Skill 2 — Audit / Re-audit states

```
[*]
 |
 v
ImplDone (tokens in log)
 |
 v
FirstAudit (fresh Skill2)
 |          |              |
 |       stalled        result
 |          |              |
 |     relaunch      NOT-READY ----+
 |          |              |       |
 |          +--------------+       v
 |                              Rework15 or Amend1
 |                                     |
 |                                     v
 |                              ReAudit (new log)
 |                                |         |
 |                           NOT-READY    CLOSED
 |                                |         |
 |                                +----<----+
 |                                          |
 v                                          v
(loop)                               Owner signoff --> [*]
```

Checklist: verify sha256 → entry PASS → Layer1 → Layer2 → CLOSED or NOT-READY → re-audit writes DELTA.

Path: `hw/sys/smc/dv/tb/grades/<anchor>_GRADE.md`

---

## 7. Skill 3 — Peer / Re-review states

```
[*]
 |
 v
ReadyForPeer (all Skill2 CLOSED)
 |
 v
PeerRun (fresh Skill3)
 |        |         |          |
 |     stalled   result     result
 |        |         |          |
 |   relaunch  INSUFFICIENT  FAIL omission ----+
 |        |         |          |               |
 |        +---------+          |               v
 |                  v          |          Skill1 Amend
 |           ReverseGen        |               |
 |           (indep Skill1)    |               v
 |                  |          |          Impl + Skill2
 |                  v          |               |
 |           PeerRereview <----+---------------+
 |            |         |
 |          FAIL      PASS
 |            |         |
 |            +----> signoff --> [*]
```

Three rounds for this IP: `INSUFFICIENT` → `FAIL` (INT-ZEROER) → `PASS` 19/19 CLEAN.

---

## 8. Loop decision table

| Symptom | Action | Next |
|---|---|---|
| Card unobservable / SPEC wrong | Skill1 amend | 1.5 → Skill2 audit |
| Skill2 NOT-READY | Skill1.5 rework | **Skill2 re-audit** |
| Skill2 contractual FIND | Skill1 amend | 1.5 → Skill2 |
| No reverse | Independent reverse Skill1 | **Skill3 re-review** |
| Reverse omission | Skill1 amend + new test | 1.5 → 2 → **Skill3 re-review** |
| Child session stalled | CANCELLED relaunch | same skill, new run_id |
| All CLOSED, not signed off | Owner signoff | Milestone Done |

---

## 9. Colleague command templates

### Skill1 plan / amend

```text
/dv_vplan_gen SMC_CLOCK_GATING
  planning_dir: hw/sys/smc/dv/tb
  pin: SMC_CLOCK_GATING_PIN.yaml
  Fresh context. Draft only.
```

### Skill1.5 impl or rework

```text
/dv_test_impl <CARD_ID>
  planning_dir: hw/sys/smc/dv/tb
  env: cocotb + tb_top.sv
  constraint: no force/deposit
  # rework: keep FIND ids; new kept log required
```

### Skill2 audit or re-audit

```text
/dv_test_audit <anchor>
  planning_dir: hw/sys/smc/dv/tb
  kept_log: <NEW log path>
  log_sha256: <hex>
  Fresh auditor. NEW run_id.
  If re-audit: write DELTA vs prior grade; do not weaken.
```

### Reverse inventory

```text
/dv_vplan_gen reverse-inventory SMC_CLOCK_GATING
  inputs: pinned SPEC paths + boundary text only
  NO pin anchors, NO existing FL/plan/grades
  output: SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md
```

### Skill3 peer or re-review

```text
/dv_peer_audit SMC_CLOCK_GATING milestone P1
  planning_dir: hw/sys/smc/dv/tb
  grades: hw/sys/smc/dv/tb/grades/
  reverse_inventory: hw/sys/smc/dv/tb/SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md
  Fresh peer. Do not re-derive reverse.
  If re-review: DELTA vs prior PEER_AUDIT result.
```

---

## 10. Artifact map

```
hw/sys/smc/dv/
├── docs/
│   ├── smc_cg_skill_flow.md      <- this file
│   ├── smc_cg_skill1.md
│   ├── smc_cg_skill2.md
│   └── smc_cg_skill3.md
├── tb/
│   ├── SMC_CLOCK_GATING_PIN.yaml
│   ├── SMC_CLOCK_GATING_SPEC_FEATURE_LIST.md
│   ├── SMC_CLOCK_GATING_TESTCASE_PLAN.md
│   ├── SMC_CLOCK_GATING_VPLAN_DETAIL.md
│   ├── SMC_CLOCK_GATING_*_REVIEW.md
│   ├── SMC_CLOCK_GATING_REVERSE_FEATURE_INVENTORY.md
│   ├── SMC_CLOCK_GATING_PEER_AUDIT.md
│   ├── audit_status_smc_clock_gating.md
│   └── grades/*_GRADE.md
├── cocotb/
├── testlists/clock.toml
└── build/runs/.../logs/*.log
```

---

## 11. Milestone status

### P1 (Done)

| Skill | Status |
|---|---|
| 1 Plan | approved including INT-ZEROER amend |
| 1.5 Impl | 8/8 tokens including rework |
| 2 Audit | 8/8 CLOSED including multi-round re-audit + signoff |
| 3 Peer | PASS (via insufficient → FAIL → final) + signoff |
| Milestone | **Done** |

### P0 (Done — 2026-08-05)

| Skill | Status |
|---|---|
| 1 Plan | approved (3 feat / 4 cards) |
| 1.5 Impl | 4/4 (including 2 new bring-up) |
| 2 Audit | 4/4 PROVEN + signoff |
| 3 Peer | `PASS-WITH-FINDINGS` (13/13 CLEAN; 2 Minor) → owner **Done** |
| Milestone | **Done** |

### P2 (Done — 2026-08-05)

| Skill | Status |
|---|---|
| 1 Plan | approved (3 feat / 3 cards; SF-001 OutstandingTx waived) |
| 1.5 Impl | 3/3 (002 via r2 NOGLITCH amend + re-impl) |
| 2 Audit | 3/3 × 4/4 PROVEN + signoff |
| 3 Peer | `INSUFFICIENT-EVIDENCE` (4/4 COVERED, CLEAN; F1 build-identity / F2 single-seed) → owner review **Done** |
| Milestone | **Done** |

```
P0/P1 DFT re-opened (#4413) · P2 Done (non-DFT)
```
---

## 12. Testplan table (P1 in-milestone)

Status source: `hw/sys/smc/dv/tb/grades/*_GRADE.md` (`EVIDENCE-CLOSED` + owner signoff → **PASS**).

| Test name | Description | Checker | Status |
|---|---|---|---|
| `smc_clk_multi_window_test` | Exercise the SMC-level generic programmable hysteresis-window claim across multiple gating windows/delays. | CHK-HYST-WINDOW, CHK-NONVAC | **PASS** |
| `smc_clk_running_test` | Exercise the SMC-level generic per-module activity-detection claim that an active module's clock keeps running. | CHK-ACTIVE-RUNNING, CHK-NONVAC | **PASS** |
| `smc_static_cg_sanity_test` | Exercise the SMC-level generic static per-module gating enable/disable and its configurable enable-threshold delay. | CHK-MODULE-GATING, CHK-ENABLE-THRESHOLD, CHK-NONVAC | **PASS** |
| `smc_dma_cg_activity_test` | Prove the DMA controller's single prim_clk_gater_hysteresis clock-gating decision: cg_enable_i, frontend wakeup, and backend busy all drive the one shared DMA gated clock. | CHK-DMA-GATE-OFF, CHK-DMA-WAKEUP-FRONTEND, CHK-DMA-WAKEUP-BACKEND, CHK-DMA-GATING-DISABLED, CHK-NONVAC | **PASS** |
| `smc_zeroer_axiclk_cg_test` | Prove the Memory Zeroer's axi_clk gating decision end-to-end: axi_clk_enable = disable_cg OR zeroer_busy_o OR ~rst_ni. | CHK-ZAXI-GATE-OFF-IDLE, CHK-ZAXI-BUSY-ENABLE, CHK-ZAXI-DISABLE-CG, CHK-ZAXI-RESET-OVERRIDE, CHK-NONVAC | **PASS** |
| `smc_zeroer_regclk_cg_test` | Prove the Memory Zeroer's reg_clk gating decision end-to-end: reg_clk_enable = disable_cg OR register_activity OR ~rst_ni. | CHK-ZREG-GATE-OFF-IDLE, CHK-ZREG-ACTIVITY-ENABLE, CHK-ZREG-DISABLE-CG, CHK-ZREG-RESET-OVERRIDE, CHK-NONVAC | **PASS** |
| `smc_zeroer_cg_indep_test` | Prove Memory Zeroer axi_clk and reg_clk gating decisions are independent under asymmetric activity (disable_cg=0, out of reset); each domain follows its own formula without the other forcing it enabled. | CHK-ZINDEP-DECOUPLE, CHK-NONVAC | **PASS** |
| `smc_cg_test_mode_bypass_test` | Prove that test_en_i bypasses the DMA and Memory Zeroer clock-gating cells, forcing their gated clocks continuously enabled for manufacturing test. | CHK-DFT-BYPASS-DMA, CHK-DFT-BYPASS-ZEROER, CHK-NONVAC | **FAIL** (post-revert; [#4413](https://github.com/tenstorrent/tt-oca-hw/issues/4413); Skill2 NOT-READY) |

Total **8** tests · all **PASS** (P1 Done).

Races/sweeps once deferred from P1 to P2: see §13 below (P2 Done).

---

## 13. Testplan table (P2 in-milestone)

Status source: `grades/*_P2_GRADE.md` + owner signoff. OutstandingTx/`axi_cg_snoop` waived via SF-001; not listed in this table.

| Test name | Description | Checker | Status |
|---|---|---|---|
| `smc_dma_cg_activity_test` (P2 extend) | DMA hysteresis full-range sweep `{0,1,32,63,64}` + activity-reassert race | CHK-DMA-HYST-SWEEP, CHK-DMA-HYST-RACE, CHK-NONVAC, CHK-TIMEOUT-PATHS | **PASS** |
| `smc_zeroer_axiclk_cg_test` (P2 extend, card r2) | axi_clk busy-boundary race; mid-busy zero glitch; inter-busy CSR gap allowed | CHK-ZEROER-AXICLK-NOGLITCH, CHK-ZEROER-AXICLK-COMPLETION, CHK-NONVAC, CHK-TIMEOUT-PATHS | **PASS** |
| `smc_zeroer_regclk_cg_test` (P2 extend) | reg_clk pending-access-while-gated race (3 cells) | CHK-ZEROER-REGCLK-UNGATE, CHK-ZEROER-REGCLK-ACCESS-COMPLETE, CHK-NONVAC, CHK-TIMEOUT-PATHS | **PASS** |

Total **3** P2 extensions · all **PASS** (P2 Done; Skill3 F1/F2 accepted via owner review).

---

*Contract authority is `tb/SMC_CLOCK_GATING_*.md` / `_P0_` / `_P2_` front-matter; per-card evidence authority is grades; milestone closure authority is each `*_PEER_AUDIT.md` + owner Done.*
