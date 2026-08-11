---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_jtag_lc_negative_test
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
- path: hw/sys/smc/dv/build/runs/20260807_035201__verilator__smc_efuse_jtag_lc_negative_test/smc_efuse_jtag_lc_negative_test/logs/smc_efuse_jtag_lc_negative_test.log
  sha256: 02843f081476c8c69b8db4e8e8272ce0a2afbc711e612c5390a1957aa53665a3
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

# Grade Report — smc_efuse_jtag_lc_negative_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this
> report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Owner rework closed residual FIND-002: ALLOW now requires
> exact `resp=OKAY` and explicitly scopes identity `rdata` as not scored
> on the Verilator stub (`0xBADCAB1E` logged, not compared).

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `4ebda509…`)

| Item | Prior (log `4ebda509…`, PASS) | This audit (log `02843f08…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | none |
| FIND-001 `[NO-SKIP-TO-PASS]` | closed | **still closed** — `with_timeout` → `self.errors` + `assert not self.errors` |
| FIND-002 `[EXACT-EXPECTATION]` | open — identity ALLOW OKAY+`0xbadcab1e` unscored as identity | **closed** — ALLOW exact `resp=OKAY`; code/VIP/log state response-code-only and `rdata` not scored (stub artifact); BLOCK still DECERR+`0xBADCAB1E`; LC_STATE exact `0xe1` |
| FIND-003 `[NO-DUMMY-DEAD-CODE]` | closed | **still closed** — PeakRDL `smc_addr`; no obsolete `0xC000_Bxxx` comments |
| Kept log | `4ebda509f25d3d1f36405a11034ddbed2663b035b186cf4fb55a2f2caa21b85e` | `02843f081476c8c69b8db4e8e8272ce0a2afbc711e612c5390a1957aa53665a3` (newer PASS `20260807_035201`) |
| Stimulus path | `tb_lc_state` + `ej_axi` JTAG OTP deny/allow; SEP_IN LC_STATE exact | unchanged contracts; ALLOW branch tightened + stub scope logged |
| Repo / model | `c10b6d63…` / `2c815fa08277` | `c10b6d63…` / `2c815fa08277` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via `/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit` only after material test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — product `tb_lc_state` pin + `ej_axi` JTAG OTP AXI-Lite + SEP_IN CSR mirror + public CPU JTAG TAP pin VIP; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — BLOCK fails without DECERR / without `0xBADCAB1E`; ALLOW fails without `resp=OKAY` or on timeout; LC_STATE `csr_read(..., expected=packed)` mismatches fail; final `assert not self.errors` |
| E1 skip-to-pass | ✅ clean — prior soft `csr_read_bounded` / `accesses == 3` removed; timeout appends errors and fails the gate |
| E2 empty phase | ✅ clean — NON_ID read/write BLOCK, CHIPLET_ID/PACKAGE_ID ALLOW, LC_STATE exact, CPU JTAG VIP all execute; deferred full LC matrix documented elsewhere |
| S1 silent fail | ✅ clean — mismatches append `self.errors` then assert; JTAG IDCODE/DTMCS asserts raise; LC_STATE scoreboard compares `exp=0xe1` |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI check #1 and protocol VIP check #1 active |
| Phase-S obligations — L1 | ✅ clean — ALLOW is exact `RESP_OKAY` with documented response-only scope (stub `rdata` not scored); BLOCK DECERR+signature; LC_STATE exact; `[TIMEOUT-MUST-FAIL]` on claimed paths; addresses via `smc_addr`; force-free; seed logged; enrolled in `vplan_triplets.toml` (included by `all.toml`); DENY has same-test ALLOW positive control at resp-code level; ROM/efuse preload is post-PASS trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_negative_test.py`
  sha256 `7c334a9e3b929e1012781486309de22b5764e27e363965e90111b6268ab39f21`
- Sequence helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_jtag_lc_negative_test_seq.py`
  sha256 `fc30cf86fd13ac56689135b005e4bf874a6f5c584e026a6c09d318e9be34e062`
  (PeakRDL addresses + strict `read_lc_state_exact`)
- Helpers on proof path: `smc_addr_map.smc_addr`, `SmcCsrSeq.csr_read` (strict expected), `OcahAxiLiteMaster` on `ej_axi`, `smc_jtag_vip_utils.check_cpu_jtag_pin_vip`
- Log: `hw/sys/smc/dv/build/runs/20260807_035201__verilator__smc_efuse_jtag_lc_negative_test/smc_efuse_jtag_lc_negative_test/logs/smc_efuse_jtag_lc_negative_test.log`
  sha256 `02843f081476c8c69b8db4e8e8272ce0a2afbc711e612c5390a1957aa53665a3` (verified)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277` · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: `tb_lc_state` PROD packed `0xe1`; ej_axi NON_ID read LOCKS `@0xc0007000` DECERR+`0xbadcab1e`; CHIPLET_ID `@0xc0007008` OKAY+`0xbadcab1e` (rdata not scored); PACKAGE_ID `@0xc0007028` OKAY+`0xbadcab1e` (rdata not scored); NON_ID write DECERR; SEP_IN CHIP_CONFIG_LC_STATE `@0xc000290c` → `0xe1` exact; CPU JTAG IDCODE `0x10CA0555` MATCH
- Final gate: `assert not self.errors` plus JTAG VIP asserts; protocol VIP `csr_accesses=5 timeouts=0`
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (pulled into `all.toml` via `includes`)
- Bring-up trailer: efuse/ROM hex preload lines after PASS; not used as CSR golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>02843f08…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| NON_ID read BLOCK | 326–336 | `@0xc0007000` resp=3 `rdata=0xbadcab1e` `blocked=True` | test `:78` / `_check_read` |
| CHIPLET_ID ALLOW | 337–340 | `@0xc0007008` resp=0 `rdata=0xbadcab1e` + "not scored — Verilator stub" | test `:79-81` / `:167-180` |
| PACKAGE_ID ALLOW | 341–344 | `@0xc0007028` resp=0 `rdata=0xbadcab1e` + "not scored — Verilator stub" | test `:82-84` / `:167-180` |
| NON_ID write BLOCK | 345–355 | `@0xc0007000` resp=3 `blocked=True` | test `:85` / `_check_write` |
| LC_STATE exact | 356–369 | `@0xc000290c` → `0xe1` scoreboard `exp=0xe1` | seq `read_lc_state_exact` / test `:88-89` |
| CPU JTAG VIP | 371–375 | IDCODE `0x10CA0555` MATCH; DTMCS version 0x1 | test `:95` |
| protocol VIP | 376–377 | `csr_accesses=5 timeouts=0 passed=True`; details name OKAY + stub non-score | test `:96-106` |
| cocotb result | 385–387 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether PROD JTAG deny/allow + LC_STATE mirror prove the SPEC eFuse JTAG LC access-control matrix (O2 / full multi-state matrix) — Skill 3; this test documents the full matrix as living in `smc_efuse_jtag_lc_access_matrix_test`.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.
- Identity-value correctness of CHIPLET_ID / PACKAGE_ID under real sensed eFuse (explicitly deferred; Verilator stub `rdata` not scored).

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
