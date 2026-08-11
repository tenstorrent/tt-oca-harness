---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_ecc_fault_inject_test
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
- path: hw/sys/smc/dv/build/runs/20260807_034418__verilator__smc_ecc_fault_inject_test/smc_ecc_fault_inject_test/logs/smc_ecc_fault_inject_test.log
  sha256: bcd72161d76fc480d46b2a9d662d1a86ba7551483cb9d00e36147163787dbf58
test_author:
  human_id: unknown
  run_id: unknown
  model:
    provider: unknown
    family: unknown
    version: unknown
auditor:
  human_id: minshaoho
  run_id: cursor/grok/4.5-fixloop-20260806
  model:
    provider: cursor
    family: grok
    version: '4.5'
exceptions: []
checkers: []
findings: []
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_ecc_fault_inject_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): cocotb
> `TESTS=1 PASS=1 FAIL=0 SKIP=0`, `CHK-ECC-INJECT` after SBE/recovery/DBE waits, zero
> unexplained `ERROR`/`FATAL`/`Traceback` — Layer 2 entry is still not evaluated in this
> mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `32365591…`)

| Prior id | Tag | Status this round | Notes |
|---|---|---|---|
| FIND-001 | `[NO-ALWAYS-PASS-CHECKER]` | CLOSED | TB `ecc_probe_fire` removed from score; `tb_top.sv:931-939` increments only on DUT `cpu_scratch0_inject_fire`. Seq arms SBE during live scratch boot (`+smc_hold_cpu_boot` + `min_pass.ecc.hex`), clears on first fire, proves recovery (further scratch reads, fire held), then DBE. Log L335–L355 / `CHK-ECC-INJECT` |
| FIND-002 | `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | CLOSED (stays) | `RAS_BANK_INFO` still via `smc_addr(...)`; no new hand-copied scored address |
| Kept log | `32365591…` → `bcd72161…` | UPDATED | New run dir `20260807_034418__verilator__…`; sha256 matches invoker claim |
| Sequence sha256 | `80282b9d…` → `a599e56e…` | UPDATED | Live-boot DUT fire / recovery / DBE body |
| Test sha256 | `4a4fb5ec…` → `dadd319c…` | UPDATED | VIP details cite DUT scratch0_inject_fire |
| Repo rev | `c10b6d63…` | UNCHANGED | Matches invoker `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none | Nothing to drop; no signed entries |

## Your to-do — none

**Then:** Layer 1 is clean for this standalone request. No card migration is owed here
(`STANDALONE-REQUEST`). Re-invoke `/dv_test_audit smc_ecc_fault_inject_test` only if the
implementation or kept log changes; Skill 3 / a future approved card is outside this audit's
standing.

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — inject pins are DUT inputs; scored `fire_count` is TB latch of DUT `cpu_scratch0_inject_fire` only (probe unused); no TB write of success state |
| F2 can't-fail checker | ✅ clean — prior FIND-001 closed; TIMEOUT if no DUT fire; recovery `assert mid_after == mid` and DBE `_wait_fire_count_gt` fail on RTL/wiring defects |
| E1 skip-to-pass | ✅ clean — missing `+smc_scratch_ram_hex` raises; no HDL-path skip-to-pass |
| E2 empty phase | ✅ clean — SBE first-fire clear, recovery scratch-read wait, DBE fire, RAS_BANK_INFO read, `CHK-ECC-INJECT` all execute on this PASS |
| S1 silent fail | ✅ clean — fire/scratch waits raise `AssertionError` on bound expiry; recovery mismatch raises |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard + protocol VIP path active in log |
| Phase-S obligations — L1 | ✅ clean — DUT-authentic fire path; `smc_addr` for RAS; bounded RisingEdge waits fail-on-expiry; X via `is_resolvable`; seed logged; enrolled in `all.toml` / `vplan_triplets.toml`; scratch hex enables live fetch (not scored as golden); `+skip_fuse_sense` not on ECC score path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_ecc_fault_inject_test.py`
  sha256 `dadd319c59e563e74f337109d4e05929d5668ea86cdcd70c9b4b9d6988bf0e4d`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_ecc_fault_inject_test_seq.py`
  sha256 `a599e56e5844d41816fb311791b5f855cc1eef3c0c51c6a024ba0bdf7bf87494`
- Address helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py`
  sha256 `cc43ce2029ebd0ceda50d06c3f9e7e8b7d04bcdd0b63510999ae7a85afd9c803`
- TB glue (proof path): `hw/sys/smc/dv/tb/tb_top.sv:927-939` — probe assigned unused;
  `ecc_inject_fire_count_q` increments only on `cpu_scratch0_inject_fire`; mirror
  `tb_cpu_scratch0_inject_fire`. DUT port map `:1048-1050`
- DUT fire source: `hw/top/smc_cpu_mem_integration.sv:146-155` —
  `scratch0_inject_fire_o` = bank0 read while `ecc_inject_sbe_i`/`dbe_i` armed; rdata
  corruption mux at `:127-136` (not scored as syndrome)
- Scoreboard / VIP: SYS AXI checks + protocol VIP `cpu:smc_ecc_fault_inject_test`
- Log: `hw/sys/smc/dv/build/runs/20260807_034418__verilator__smc_ecc_fault_inject_test/smc_ecc_fault_inject_test/logs/smc_ecc_fault_inject_test.log`
  sha256 `bcd72161d76fc480d46b2a9d662d1a86ba7551483cb9d00e36147163787dbf58`
  (verified via `manifest.py hash-file`; matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L365–L367:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: arm SBE → release held scratch boot → clear on first DUT fire → recovery
  (more scratch reads, fire held) → arm DBE in fill window → RAS_BANK_INFO read
- Observed: L335 SBE `0 -> 1` (scratch_reads=2); L337 RECOVERY fire held at 2; L338
  DBE `2 -> 3`; L355 `CHK-ECC-INJECT: SBE 0->1 recovery_hold=2 DBE 2->3`; VIP
  `csr_accesses=7` `passed=True`
- Enrollment: `hw/sys/smc/dv/testlists/all.toml`, `vplan_triplets.toml`
  (`+smc_hold_cpu_boot`, `+smc_scratch_ram_hex=…/min_pass.ecc.hex`)
- Bring-up: `+skip_fuse_sense` / efuse+ROM hex flush after PASS; not used as ECC golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Prior waivers: none (`waivers: []` — nothing carried forward)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>bcd72161…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| SBE first fire + clear | 335 | `0 -> 1` at cycle 187; scratch_reads=2; inject cleared | seq `_clear_sbe_on_first_fire` |
| Recovery | 336–337 | scratch_reads advance; fire_count held at 2 | seq `:158-173` |
| DBE fire | 338–339 | `2 -> 3` via DUT scratch0_inject_fire path | seq `_wait_fire_count_gt` |
| Boot release log | 340 | `+smc_hold_cpu_boot` vector `0xc0060000` | `_release_held_cpu_boot` |
| RAS_BANK_INFO | 342–353 | `0xc0002910` → `0x0` OKAY | seq `:193` via `smc_addr` |
| CHK + VIP | 355–357 | `CHK-ECC-INJECT` + protocol VIP passed | seq `:196-203` / test `:21-29` |
| cocotb result | 361–367 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |
| scratch image flush | 375 | `min_pass.ecc.hex` bank0 nonzero=4 | testlist plusarg |

</details>

## Not concluded

- Whether SBE/DBE inject behavior matches the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
