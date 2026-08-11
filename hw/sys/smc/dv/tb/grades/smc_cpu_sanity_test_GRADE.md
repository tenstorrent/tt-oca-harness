---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cpu_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094629__verilator__smc_cpu_sanity_test/smc_cpu_sanity_test/logs/smc_cpu_sanity_test.log
  sha256: 6c8c8c2791e8d2fabdb00ad899bf68a1a80443cbc663b01c4fb979ccd10dd947
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_ctrl_map_depth_test_seq.py:22-27
  observed: >
    Partial remediation since the prior grade: `GLOBAL_BASE` and `LOCAL_BASE` now
    import absolute addresses via `smc_addr` PeakRDL symbols. This sanity test's
    SYS AXI proof path is still `smc_cpu_ctrl_map_depth_test_seq` (`CPU_MAP_READS`),
    which hand-computes hang-detector registers as
    `smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR") + 0x40` /
    `+ 0x48`, while generated per-register macros
    `SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_CTRL_BASE_ADDR` and
    `SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR`
    already exist in `smc_addr.h` / `smc_addr_map`. The reserved/open-bus probe
    remains an absolute literal `0xC001_0050` (outside PeakRDL
    `SMC_BASE_CONFIG_SIZE` `0x4C`; last named reg ends at `0x48`). Composed hang-det
    addresses currently match the generated macros (latent-rot class, not
    false-identity); `0x50` is labeled reserved rather than a named register.
  closure_condition: >
    Import hang-det addresses from the per-register `smc_addr` symbols (not
    base+hand-offset), and either drop the `0x50` probe or derive it from
    `smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR") +
    smc_addr("SMC_TOP_SMC_BASE_CONFIG_SIZE")` (or equivalent map-derived bound),
    not a parallel absolute hex constant.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cpu_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): five
> frontdoor SEP_IN SYS AXI reads completed OKAY with matching `rdata`/`exp`, CPU BFM
> observability sampled, and the optional firmware-boot contract honestly stayed unpromoted
> (`mode=proxy`, missing `+smc_rom_hex` / `+smc_scratch_ram_hex`) — Layer 2 entry is still
> not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b692acd0…`)

| Item | Prior (log `b692acd0…`, PASS) | This audit (log `6c8c8c27…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | 🟠 1 Major FIND-001 (same tag) |
| FIND-001 | open — all five `CPU_MAP_READS` addresses hand-copied absolute hex | **still open / narrowed** — `GLOBAL_BASE` / `LOCAL_BASE` now via `smc_addr`; hang-det still `BASE+0x40/0x48`; RSVD still `0xC001_0050` |
| Kept log | `b692acd09855219a78076d89aac89ac5efd3b24452552ae82690031bb014f8d2` PASS seed=1 | `6c8c8c2791e8d2fabdb00ad899bf68a1a80443cbc663b01c4fb979ccd10dd947` PASS seed=1; 5/5 SYS AXI checks; boot still proxy |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hang-det hand offsets + RSVD absolute hex |

<details>
<summary>1. 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq hang-det / RSVD</summary>

`GLOBAL_BASE` / `LOCAL_BASE` now use `smc_addr` PeakRDL symbols. Remaining proof-path
addressing on the shared `smc_cpu_ctrl_map_depth_test_seq`: hang-det as
`SMC_BASE_CONFIG_BASE_ADDR + 0x40` / `+ 0x48` instead of
`HANG_DET_DATA_ACCEL_{CTRL,TIMEOUT_THRESHOLD}_BASE_ADDR`, and reserved probe
`0xC001_0050` as absolute hex. Generated map exists; hang-det literals currently
match → Major (latent rot), not Blocking false-identity. `0x50` is outside map size
`0x4C` and is already labeled reserved in the sequence.

**Close when:** hang-det addresses come from per-register `smc_addr` symbols; the
reserved probe (if kept) is derived from base+size (or equivalent map bound), not a
parallel absolute hex constant.

</details>

**Then:** owner remediates FIND-001 on the shared sequence, re-keeps a PASS log for
`smc_cpu_sanity_test`, and re-invokes `/dv_test_audit`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to independently supplied `expected`; no force/deposit on CSR path; boot path not entered this run |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp`, non-OKAY `resp_ok`, driver timeout, final `assert self.accesses == len(CPU_MAP_READS)`, and powergood exact assert are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — CSR map path must complete or raise; optional boot with `require_image=False` returns unpromoted with explicit reason and records `proxy=True` rather than claiming boot proof |
| E2 empty phase | ✅ clean — five real SYS AXI reads executed (scoreboard checks #1–#5) plus BFM observability sample |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active; protocol VIP scoreboard only records completion evidence consistency |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`; timeouts fail; enrolled in `vplan_triplets.toml` (via `all.toml`); exact RDL-cited expecteds on map reads; optional boot demotion explained in log; no unconditional CHK success token for boot |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_cpu_sanity_test.py`
  sha256 `b024ebdd80a3aa20dfbb24a5f04d16a9a5ac54e85184f98f8b8c37fd6bf5c8b9`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_ctrl_map_depth_test_seq.py`
  sha256 `42081115c503866e72983d303d22d50b5da6fbae61cf94abb4d2768c27f0648d`
- Helpers on proof path: `smc_csr_seq_utils.SmcCsrSeq`, `smc_scoreboard._check_sys_axi`,
  `smc_sys_axi_agent`, `smc_cpu_vip_utils.check_cpu_bfm_observability`,
  `smc_cpu_vip_utils.check_cpu_firmware_boot_contract` (unpromoted this run)
- Log: `hw/sys/smc/dv/build/runs/20260806_094629__verilator__smc_cpu_sanity_test/smc_cpu_sanity_test/logs/smc_cpu_sanity_test.log`
  sha256 `6c8c8c2791e8d2fabdb00ad899bf68a1a80443cbc663b01c4fb979ccd10dd947`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, cocotb summary L333–L335:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(CPU_MAP_READS)` (5) after
  five scoreboard SYS AXI value checks; protocol VIP records `csr_accesses=5`
  `mode=proxy`
- Scoreboard value checks (log):
  - #1 `0xc0010000` rdata/exp `0x40000000`
  - #2 `0xc0010008` rdata/exp `0xc0000000`
  - #3 `0xc0010040` rdata/exp `0x0`
  - #4 `0xc0010048` rdata/exp `0x1000`
  - #5 `0xc0010050` rdata/exp `0x0` (reserved/open-bus probe)
- BFM observability (log L323): `powergood=1 rst_primary=1 rst_wdt=1` after
  `is_resolvable` + exact powergood assert
- Optional boot (log L324–L325): details =
  `CPU firmware boot infra armed but not promoted (missing +smc_rom_hex / +smc_scratch_ram_hex preload)`
  — not treated as skip-to-pass of the CSR map path
- Addressing: `GLOBAL_BASE` / `LOCAL_BASE` via `smc_addr` (`:20-21`); hang-det
  still `BASE+0x40/0x48` (`:22-23`); RSVD absolute `0xC001_0050` (`:27`); generated
  hang-det macros in `hw/sys/smc/regs/gen/c/smc_addr.h` match the composed values;
  map size `0x4C` excludes `0x50`
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied for this path)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (included by `all.toml`)
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` via `+rom_hex` —
  time-0 image load; not selected by the boot-contract plusarg API and not used as
  CSR golden substitution on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>6c8c8c27…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| GLOBAL_BASE | 280–293 | read `0xc0010000` → `0x40000000` exp match | seq `:20` |
| LOCAL_BASE | 295–300 | read `0xc0010008` → `0xc0000000` exp match | seq `:21` |
| HANG_DET_DATA_ACCEL_CTRL | 302–307 | read `0xc0010040` → `0x0` exp match | seq `:22` |
| HANG_DET timeout thr | 309–314 | read `0xc0010048` → `0x1000` exp match | seq `:23` |
| RSVD 0x50 | 316–321 | read `0xc0010050` → `0x0` exp match | seq `:27` |
| BFM observability | 323 | powergood/rst sample | vip_utils `:76-93` |
| protocol VIP | 324–325 | `mode=proxy csr_accesses=5` boot unpromoted | test `:28-38` |
| cocotb result | 333–335 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:38-39` |

</details>

## Not concluded

- Whether SMC_BASE_CONFIG reset/decode reads plus optional CPU firmware-boot promotion prove the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
