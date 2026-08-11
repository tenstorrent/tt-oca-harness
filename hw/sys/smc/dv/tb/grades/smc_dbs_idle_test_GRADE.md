---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_dbs_idle_test
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
- path: hw/sys/smc/dv/build/runs/20260806_144013__verilator__smc_dbs_idle_test/smc_dbs_idle_test/logs/smc_dbs_idle_test.log
  sha256: 5c3d7ed947cc8b851b6621c9c51b00e50a74947757f5681e908062ae069c81b0
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

# Grade Report — smc_dbs_idle_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> five SYS AXI diagnostic CSR reads completed OKAY at PeakRDL DFX/NDM/RAS symbols —
> Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `41bcd629…`)

| Item | Prior (log `41bcd629…`, PASS) | This audit (log `5c3d7ed9…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 FIND-001 · 🟠 FIND-002 | **cleared** — none open (`findings: []`) |
| FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` DFX false identity | open Blocking — bare/false window `0xC001_0208/0210` vs PeakRDL DFX `0xC000_B808/B810` | **CLOSED** — `smc_addr(SMC_TOP_DFX_CTRL_DEBUG_{CTRL,BUS_MUX}_BASE_ADDR)` → `0xC000_B808/B810`; RDL reset expecteds `0x0`; log L314/L321 |
| FIND-002 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` NDM hand offsets | open Major — `NDM_RESET_BASE + 0x4/+0x8` residual | **CLOSED** — per-register `smc_addr(SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_{PROCESS,CLUSTER_COUNT}_BASE_ADDR)` |
| Sequence sha256 | `a3193a9c105723cb32eb7046da6920839e8dcfb90ad2c7d43f35c3fc73793c97` | `f6095acab0c866b7cf080bd03a52fe94da882835940c6d8fdd13c21dc0eb0dcc` |
| Kept log | `41bcd629f31eb74a753b761f9608e1a2248948643fd644ffe8be8026a85ac13f` (wrong DFX window) | `5c3d7ed947cc8b851b6621c9c51b00e50a74947757f5681e908062ae069c81b0` (DFX @ `0xc000b808/b810`; content sha256 verified) |
| Repo / model | `c10b6d63…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Auditor run_id | (prior Blocking-open grade) | `cursor/grok/4.5-fixloop-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit` only after material
test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; expecteds compared to DUT `rdata` in scoreboard; no force/deposit on CSR path; protocol VIP `passed` is a completion marker only (scoreboard does not assert it as CSR golden) |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / `got==exp` and sequence `assert accesses == len(DIAGNOSTIC_READS)` are reachable FAIL-ON paths; diagnostic VIP `axil_active==0` / resolvable asserts can fail |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — five real SYS AXI diagnostic reads + bounded observability sample (log checks #1–#5) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert; VIP idle/resolvable asserts |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (5 checks); protocol VIP analysis port records the diagnostic item |
| Phase-S obligations — L1 | ✅ clean — all five proof-path addresses from `smc_addr(...)` / PeakRDL `smc_addr.h` (RAS + NDM per-reg + DFX `DEBUG_{CTRL,BUS_MUX}`); DFX expecteds RDL reset `0x0`; NDM CLUSTER_COUNT `0x4` documented as tied-HW regression-lock (not DUT-copied); timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_dbs_idle_test.py`
  sha256 `af5f480f50d20f40c3b175a2e16a437ef7dfc714faa1441a06354f8c35054cf6`
- Sequence (actual): `hw/sys/smc/dv/cocotb/seq_lib/smc_ecc_dfd_dbs_sanity_test_seq.py`
  sha256 `f6095acab0c866b7cf080bd03a52fe94da882835940c6d8fdd13c21dc0eb0dcc`
  (no `smc_dbs_idle_test_seq.py`; P0 alias reuses ECC/DFD/DBS sanity seq)
- Diagnostic VIP helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_diagnostic_vip_utils.py`
  sha256 `fb159d657fc2a2d9f9817c45c41f1aaf7f4a9f726e70673b270f663e421caff2`
- Authoritative map: `smc_addr_map.smc_addr` ← `hw/sys/smc/regs/gen/c/smc_addr.h`
  (`SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_RAS_BANK_INFO_BASE_ADDR=0xC0002910`,
  `…_NDMRESET_PROCESS_BASE_ADDR=0xC0002A04`,
  `…_NDMRESET_CLUSTER_COUNT_BASE_ADDR=0xC0002A08`,
  `SMC_TOP_DFX_CTRL_DEBUG_CTRL_BASE_ADDR=0xC000B808`,
  `SMC_TOP_DFX_CTRL_DEBUG_BUS_MUX_BASE_ADDR=0xC000B810`)
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive`, `check_diagnostic_observability`
- Log: `hw/sys/smc/dv/build/runs/20260806_144013__verilator__smc_dbs_idle_test/smc_dbs_idle_test/logs/smc_dbs_idle_test.log`
  sha256 `5c3d7ed947cc8b851b6621c9c51b00e50a74947757f5681e908062ae069c81b0` (content sha256 verified)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Repo rev: `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7`
- Policy: `51a3357d9c31a018d69451b055bc956c089af26e1051368e25ce396c84ac2a75`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L333–L335:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: five CSR reads from `DIAGNOSTIC_READS` then `check_diagnostic_observability` (8 clk settle + resolvable/idle asserts) then protocol VIP record (`csr_accesses=5`, proxy)
- AXI monitor trailer: `5 R beats, 0 B resps; R-resp tally OKAY=5; 0 errors` (L327)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log (only a cocotb INFO mentioning AssertionError message formatting)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-fixloop-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>5c3d7ed9…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| RAS_BANK_INFO | 293 | read `0xc0002910` → `0x0` exp=`0x0` OKAY | seq `:16` |
| NDMRESET_PROCESS | 300 | read `0xc0002a04` → `0x0` exp=`0x0` OKAY | seq `:17` |
| NDMRESET_CLUSTER_COUNT | 307 | read `0xc0002a08` → `0x4` exp=`0x4` OKAY | seq `:18` |
| DFX_DEBUG_CTRL | 314 | read `0xc000b808` → `0x0` exp=`0x0` OKAY | seq `:19` |
| DFX_DEBUG_BUS_MUX | 321 | read `0xc000b810` → `0x0` exp=`0x0` OKAY | seq `:20` |
| diagnostic VIP | 323 | sync_irq=0 axil_active=0 rst_primary=1 | utils `:10-29` |
| protocol VIP | 324–326 | diagnostic proxy csr_accesses=5 | test `:23-28` |
| cocotb result | 329–335 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | seq `:32` |

</details>

## Not concluded

- Whether DBS/DFD/ECC diagnostic CSR reachability (and the idle/proxy alias naming) proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
