---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_register_boundary_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_register_boundary_depth_test/smc_register_boundary_depth_test/logs/smc_register_boundary_depth_test.log
  sha256: 6165cff8cd252fc1709c70647757b2f0b7e018aaf09dc0fea554f6317c5c33d1
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_register_boundary_depth_test_seq.py:10-21
  observed: >
    Absolute hex CSR literals were removed from the sequence, but the proof path
    still hand-computes register addresses: `SCRATCH_COLD_7` /
    `SCRATCH_COLD_WARM_7` as window `smc_addr(..._BASE_ADDR) + 0x1C`, and
    `CHIP_CONFIG_VERSION_HI` as `smc_addr(...CHIP_CONFIG_BASE_ADDR) + 0x4`, while
    `VERSION_LO` uses the CHIP_CONFIG window base rather than
    `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR`. PeakRDL already
    exports
    `SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD{,_WARM}_SCRATCH_BASE_ADDR(idx)` and
    `CHIP_CONFIG_VERSION_{LO,HI}_BASE_ADDR`, loadable via
    `smc_indexed_addr` / `smc_addr`. On the same proof path,
    `catalog_entry` still cross-checks against
    `smc_csr_field_catalog.py` which keeps `SCRATCH_COLD_WARM_7 = 0xC000_289C`
    as an absolute literal plus the same hand offsets. Computed values currently
    match the generated macros (latent-rot class, not false-identity).
  closure_condition: >
    Drive every `BOUNDARY_READS` / `BOUNDARY_WRITES` address from the per-register
    generated symbols (`smc_indexed_addr(...SCRATCH_BASE_ADDR, idx)` and
    `smc_addr(...VERSION_{LO,HI}_BASE_ADDR)`), and align `catalog_entry` sources
    the same way so no hand offset or absolute hex remains on this proof path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_register_boundary_depth_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0` with 16 SYS AXI scoreboard checks completing; Layer 2
> entry is still not evaluated under `STANDALONE-REQUEST`.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `3251ff2d…`)

| Item | Prior (log `3251ff2d…`, PASS) | This audit (log `6165cff8…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | 🟠 1 Major FIND-001 (same tag) |
| FIND-001 | open — absolute hex literals `0xC000_2800`…`0xC000_2904` on seq proof path | **still open / narrowed** — seq now uses `smc_addr` window bases, but hand `+0x1C` / `+0x4` remain; catalog still has `SCRATCH_COLD_WARM_7 = 0xC000_289C`; per-register indexed / VERSION_* symbols unused |
| Kept log | `3251ff2d7ea384b50ef561fc7b87f2c9a1e482c5fb3b19119706847e828e0ab5` PASS seed=1 | `6165cff8cd252fc1709c70647757b2f0b7e018aaf09dc0fea554f6317c5c33d1` PASS seed=1; 16/16 SYS AXI checks |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand offsets / catalog literal on boundary CSR addresses |

<details>
<summary>1. 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq + catalog</summary>

Seq imports window bases via `smc_addr` but still adds `+ 0x1C` (scratch idx 7) and
`+ 0x4` (VERSION_HI), and addresses VERSION_LO via `CHIP_CONFIG_BASE_ADDR` instead of
`VERSION_LO_BASE_ADDR`. Generated indexed scratch macros and VERSION_LO/HI symbols exist
in `smc_addr.h` / `smc_addr_map`. Catalog twin still holds absolute
`SCRATCH_COLD_WARM_7 = 0xC000_289C` and the same hand offsets on the `catalog_entry`
cross-check. Values currently match → Major (latent rot), not Blocking false-identity.

**Close when:** every `BOUNDARY_READS` / `BOUNDARY_WRITES` address (and matching catalog
entries used by this proof path) come from per-register generated symbols
(`smc_indexed_addr(...SCRATCH_BASE_ADDR, idx)`, `smc_addr(...VERSION_{LO,HI}_BASE_ADDR)`);
no hand offset or absolute hex remains as the addressing source of truth.

</details>

**Then:** owner remediates FIND-001 (mirror `smc_register_sanity_test_seq` indexed-symbol
style), re-keeps a PASS log, then re-invoke `/dv_test_audit`. Do not invent a card here
(`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to independently supplied `expected`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` and driver timeout `AssertionError` are reachable; final `accesses == 16` fails if a step is dropped |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; `wait_fuse_sense_done` raises on miss |
| E2 empty phase | ✅ clean — real AXI reset-read / write-readback / restore sequence (16 accesses) |
| S1 silent fail | ✅ clean — mismatch/timeout raise; PASS log shows scoreboard value checks |
| O1 checker disabled | ✅ clean |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`; timeouts fail; enrolled in `batch_b.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_register_boundary_depth_test/smc_register_boundary_depth_test/logs/smc_register_boundary_depth_test.log`
  sha256 `6165cff8cd252fc1709c70647757b2f0b7e018aaf09dc0fea554f6317c5c33d1`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L417:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_register_boundary_depth_test.py`
  sha256 `de6ab23c9584f31ea54160903ddbe122d03e691b90b497758bdd9c52fe8f20d9`
  starts `smc_register_boundary_depth_test_seq` on `sys_axi_agent.sequencer`, then records
  protocol VIP CSR accesses.
- Seq: `hw/sys/smc/dv/cocotb/seq_lib/smc_register_boundary_depth_test_seq.py`
  sha256 `ca004522a4426761c5bcd8fd8be817891b0572794e16e3572837314b991489d3`
  body: `wait_fuse_sense_done` → catalog validate → 6× boundary reset reads → 2×
  save/write/readback → reverse restore; final `assert self.accesses == 16`.
- Scoreboard evidence (L293–L405): SYS AXI checks #1–#16 include RO
  `CHIP_CONFIG_VERSION_LO` `rdata=0x100a0 exp=0x100a0`, scratch write-readback
  `0x13572468` / `0x24681357`, and restore-to-0 compares.
- Protocol VIP (L406–L407): `csr_accesses=16 timeouts=0` completion record; scoreboard
  treats `passed` as a non-asserted completion marker; DUT value proof is the SYS AXI path.
- Addressing: seq `:10-21` uses `smc_addr` window bases + hand `+0x1C`/`+0x4`; catalog
  twin `smc_csr_field_catalog.py:25-39` still has absolute `0xC000_289C` for
  `SCRATCH_COLD_WARM_7`; generated truth in `hw/sys/smc/regs/gen/c/smc_addr.h`
  (indexed scratch + VERSION_LO/HI) currently MATCH numerically.
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied for this path).
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected` when set.
- Enrollment: `hw/sys/smc/dv/testlists/batch_b.toml`, `all.toml`, `vplan_triplets.toml`.
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not used
  as CSR golden substitution on this proof path.
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log.
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX).
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`.

</details>

## Not concluded

- Whether boundary RO/RW restore proves the SPEC register properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
