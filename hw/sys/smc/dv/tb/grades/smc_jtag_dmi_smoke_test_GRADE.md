---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_jtag_dmi_smoke_test
ip: SMC_ACTIVE_REGRESSION
anchor: null
mode: NO-CHECKBOX
no_contract_reason: STANDALONE-REQUEST
entry_status: NOT-EVALUATED
repository_revision: c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7
spec: []
card_sha256: null
card_revision: null
card_path: null
testcase_plan:
  path: null
  plan_revision: null
  testcase_revision: null
  testcase_record_sha256: null
  parent_approved: null
evidence_class: null
closure_tier: null
quality_policy:
  path: /home/minshaoho/.claude/skills/dv_common/DV_QUALITY_POLICY.md
  revision: 51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75
build_config: default
simulator: verilator
simulator_version: 5.050 2026-07-01
compile_target: default
model_fingerprint: 2c815fa08277
compile_inputs_sha256: null
seeds:
- 1
logs:
- path: hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_jtag_dmi_smoke_test/smc_jtag_dmi_smoke_test/logs/smc_jtag_dmi_smoke_test.log
  sha256: 5db48f910f19be3cebcf53c1831142e2b9bea9d6813d02d91f5ac537b9e3722c
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-reaudit-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings:
- id: FIND-001
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py:53-55
  observed: >-
    Proof-path DEBUG_RESET release uses a hand-copied field bit
    `CPU_RESET_CTRL_DEBUG_RELEASE = CPU_RESET_CTRL_DEFAULT | (1 << 24)`, and the
    sequence readback gate repeats `reset_ctrl & (1 << 24)`. The register
    *address* is correctly imported from PeakRDL
    (`SMC_CPU_CTRL_RESET_CTRL_REG_ADDR` / `0xC0039020`), but the field bit
    position is not: generated headers already define
    `CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm/bp` (`cpu_ctrl.h`) and
    `CPU_CTRL_RESET_CTRL_DEBUG_RESET_N_N0_SCAN_MASK/SHIFT` (`smc_reg.svh`) with
    shift/mask = 24 / 0x1000000. The literal currently matches (latent rot),
    not a false-identity Blocking case. Python `smc_reg.py` exports the address
    and default but not the field mask.
  closure_condition: >-
    Build `CPU_RESET_CTRL_DEBUG_RELEASE` (and the seq readback mask) from the
    generated DEBUG_RESET field symbol/mask (C header bm/bp, SVH MASK/SHIFT, or
    an exported PeakRDL Python symbol if added); do not keep a parallel
    `(1 << 24)` constant as the addressing source of truth.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_dmi_smoke_test_seq.py:64-68
  observed: >-
    After `assert dm_ver == 2` on `dmstatus & 0xF`, the sequence also
    `assert self.dmstatus != 0`. With version forced to 2, the non-zero assert
    cannot fail on any RTL path that reached the prior gate; it reads as a
    second live check while adding no fail-capable sensitivity.
  closure_condition: >-
    Drop the redundant `dmstatus != 0` assert (keep the exact version==2 gate),
    or replace it with an independently derived exact field check that can fail
    when version==2 alone would not.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_jtag_dmi_smoke_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> IDCODE/DTMCS/dmstatus frontdoor path completed with `dmstatus.version==2` after
> dmactive — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `016f3a7d…`)

| Item | Prior (log `016f3a7d…`, PASS) | This audit (log `5db48f91…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major · 🟡 1 Minor | 🟠 1 Major · 🟡 1 Minor |
| Prior FIND-001 DEBUG_RESET `(1 << 24)` | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | **still open** as FIND-001 Major — `smc_cpu_vip_utils.py:53-55` and seq readback mask unchanged |
| Prior FIND-002 redundant `dmstatus != 0` | open Minor `[NO-DUMMY-DEAD-CODE]` | **still open** as FIND-002 Minor — `smc_jtag_dmi_smoke_test_seq.py:64-68` unchanged |
| Kept log | `016f3a7d8fcc6c272673c194df5042cf68f7fcf4fb2926749a1e2c54052fc0d6` | `5db48f910f19be3cebcf53c1831142e2b9bea9d6813d02d91f5ac537b9e3722c` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 1 Major · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_cpu_vip_utils.py:53-55` |
| 2 | finding | FIND-002 | 🟡 Minor | `smc_jtag_dmi_smoke_test_seq.py:64-68` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — DEBUG_RESET bit hand-copied</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py:53-55` (used by
  `smc_jtag_dmi_smoke_test_seq.py:38-49` write + readback mask `(1 << 24)`)
- **Observed:** `RESET_CTRL` address comes from PeakRDL
  `SMC_CPU_CTRL_RESET_CTRL_REG_ADDR`, but `debug_reset_n` is released / checked via
  a parallel `(1 << 24)` literal. Generated
  `CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm/bp` and SVH MASK/SHIFT already
  encode bit 24 — latent-rot class (value currently correct).
- **Closure:** OR/mask using the generated DEBUG_RESET field symbol; drop the
  hand-maintained bit-24 constant on the proof path.

</details>

<details>
<summary>2. FIND-002 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — redundant non-zero after version==2</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_dmi_smoke_test_seq.py:64-68`
- **Observed:** `assert dm_ver == 2` already implies `dmstatus != 0`; the second
  assert cannot fail once the first passed and resembles an extra live check.
- **Closure:** Remove the dead assert, or replace with a fail-capable exact field
  expectation beyond version.

</details>

**Then:** owner remediates FIND-001 (and optionally FIND-002), re-keeps a PASS log for
`smc_jtag_dmi_smoke_test`, and re-invokes `/dv_test_audit smc_jtag_dmi_smoke_test`.
Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI for RESET_CTRL + top-level `tb_cpu_jtag_*` / `tb_cpu_jtag_reset` bit-bang; `dmi_ok` set only after asserts; hierarchical `tb_cpu_debug_dmactive*` is log-only probe |
| F2 can't-fail checker | ✅ clean — IDCODE exact, DTMCS version==0x1, dmstatus.version==2, RESET_CTRL bit readback, DMI status raises, protocol VIP `expected_bytes` compare are reachable FAIL-ON paths (see FIND-002 for one dead follow-on assert) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; TAP bind / DMI helpers raise on status/busy; optional dmactive probe swallow does not gate pass |
| E2 empty phase | ✅ clean — real AXI write/read, TAP reset, IDCODE, DTMCS, dmactive DMI write, dmcontrol/dmstatus DMI reads (log shows non-zero dmstatus=0x004F0CA2) |
| S1 silent fail | ✅ clean — mismatches raise `AssertionError` / `SmcJtagTapError`; success log only after gates |
| O1 checker disabled | ✅ clean — SYS AXI + protocol VIP scoreboard paths active (log checks #1–#2 AXI, protocol VIP #1) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001; 🟡 Minor — FIND-002; else FORCE-free pin/JTAG path; DMI 0x10/0x11 cited as Debug Spec 0.13; seed logged; enrolled in `batch_c.toml` / `all.toml`; dmactive settle uses TCK idle then poll; ROM/efuse hex preload is post-PASS bring-up trailer not DMI golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_jtag_dmi_smoke_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_dmi_smoke_test_seq.py`
- JTAG VIP (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_protocol_vip.py`
- RESET_CTRL helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_vip_utils.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094553__verilator__smc_jtag_dmi_smoke_test/smc_jtag_dmi_smoke_test/logs/smc_jtag_dmi_smoke_test.log`
  sha256 `5db48f910f19be3cebcf53c1831142e2b9bea9d6813d02d91f5ac537b9e3722c` (matches claimed; verified via `sha256sum`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: AXI write RESET_CTRL debug_reset release → TAP reset → IDCODE → DTMCS → DMI dmactive → dmstatus
- Observed in log: IDCODE=0x10CA0555; DTMCS=0x00005071 (version=0x1); dmactive/ack=1; dmcontrol=0x1; dmstatus=0x004F0CA2 (version=2); protocol VIP golden=02 obs=02
- Final gates: seq asserts (DTMCS/dmstatus) + `assert seq.dmi_ok` + scoreboard protocol VIP byte compare (no `CHK-*` tokens — none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload present after PASS; not used by JTAG DMI proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>5db48f91…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| RESET_CTRL write | 280–293 | SEP_IN AXI write `0xc0039020 <- 0x100010f` OKAY | seq `:38-43` |
| RESET_CTRL readback | 295–307 | read `0x100010f` OKAY; scoreboard SYS AXI #1/#2 | seq `:45-50` |
| TAP bind / IDCODE | 308–309 | IDCODE=0x10CA0555 | VIP `:151-172` |
| DTMCS | 310–311 | DTMCS=0x00005071 version=0x1 | VIP `:194-210` / seq `:56-60` |
| dmactive DMI write | 312–315 | op=2 @0x10; dmactive=1 ack=1; dmcontrol=0x1 | VIP `:308-335` |
| dmstatus DMI read | 316–318 | dmstatus=0x004F0CA2 version=2; U7-3 OK | VIP `:336-352` / seq `:62-75` |
| protocol VIP | 319–321 | golden=02 obs=02 passed record | test `:23-36` |
| cocotb result | 324–331 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether IDCODE + DTMCS + dmstatus.version==2 after dmactive proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
