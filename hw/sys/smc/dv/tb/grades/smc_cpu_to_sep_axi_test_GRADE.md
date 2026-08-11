---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cpu_to_sep_axi_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094557__verilator__smc_cpu_to_sep_axi_test/smc_cpu_to_sep_axi_test/logs/smc_cpu_to_sep_axi_test.log
  sha256: 5da4ed40f9d191caaae96464af83870ab44abd847b35069076ee711d7ba370eb
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
findings: []
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cpu_to_sep_axi_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect** in the
> test by itself.

## DELTA (re-audit)

| Item | Prior grade | This round |
|---|---|---|
| Kept log | `…/20260806_084625…` sha256 `d9a6ef3b…` | `…/20260806_094557…` sha256 `5da4ed40…` (verified) |
| `repository_revision` | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| `auditor.run_id` | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Findings | none | none (no new Layer 1 hits) |
| Waivers carried | none | none (prior `waivers: []`; nothing unsigned to drop) |
| Verdict / recommendation | `0/0 PROVEN` / `NOT-READY` | unchanged |

Proof-path sources unchanged vs prior (`test`/`seq` sha256 match prior cites). Stimulus
shape, scoreboard #1–#9, and cocotb PASS evidence reproduce on the new kept log.

## Your to-do — 0 items (none)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| — | — | — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit smc_cpu_to_sep_axi_test`
only after material test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem` / `OcahAxiMaster`; scoreboard compares DUT `rdata` to PeakRDL reset / programmed pattern; no force/deposit on CSR proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok` and driver timeout `AssertionError` are reachable; powergood exact assert in `check_cpu_bfm_observability` can fail; protocol VIP `passed` is not asserted (completion marker only) |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — five CPU_CTRL reset reads + scratch write/readback/restore (9 SYS AXI scoreboard checks logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#9); AXI monitor tallies OKAY |
| Phase-S obligations — L1 | ✅ clean — PeakRDL addresses + RDL DEFAULT expecteds; timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden; seq closing relies on per-access scoreboard expecteds (not vacuous `accesses` alone) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_cpu_to_sep_axi_test.py`
  sha256 `e4ee160795103520623f68410f2fed52a3ce3145e77e98433ae06d2d66cd64ad`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_to_sep_axi_test_seq.py`
  sha256 `bd2c4ba3ecacccf4cc9be4784a983648fef6b521e75155dceac36668f5dd573c`
- Helpers on proof path: `smc_csr_seq_utils.SmcCsrSeq`, `smc_scoreboard._check_sys_axi`,
  `smc_sys_axi_agent._drive`, `smc_cpu_vip_utils.check_cpu_bfm_observability`
- Log: `hw/sys/smc/dv/build/runs/20260806_094557__verilator__smc_cpu_to_sep_axi_test/smc_cpu_to_sep_axi_test/logs/smc_cpu_to_sep_axi_test.log`
  sha256 `5da4ed40f9d191caaae96464af83870ab44abd847b35069076ee711d7ba370eb`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L367–L369:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Addressing: PeakRDL `smc_reg` symbols (`SMC_CPU_CTRL_*_REG_ADDR` +
  `CPU_CTRL_*_REG_DEFAULT`); spot-checked symbols match logged addresses
  (`0xc0039000`…`0xc0039080`) and reset expecteds
- Stimulus: `csr_read_many(CPU_CTRL_READS)` (RESET_VECTOR_0 / RESET_CTRL /
  CORE_RESET_PULSE_COUNT / WDT_TIMEOUT / TEST_CTRL with RDL defaults) →
  scratch write/readback `0xC511_0001` → restore-to-0 → CPU BFM observability →
  protocol VIP record (`csr_accesses=9`)
- Scoreboard cites (kept log): checks #1–#5 reset reads match expected
  (`0xc0040000`, `0x10f`, `0x100008`, `0x4000`, `0x0`); #6–#9 scratch WR/RD/WR/RD
  with pattern then zero; protocol VIP #1 at L359
- AXI monitor: `7 R beats, 2 B resps; R-resp tally OKAY=7; 0 errors` (L361)
- Observability: `powergood=1 rst_primary=1 rst_wdt=1` after resolvable asserts (L357)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
  (policy §6 standing preload; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotbext AXI `DeprecationWarning`s
  and fuse-sense / ROM INFO
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>5da4ed40…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| RESET_VECTOR_0 RD | 293 | `rdata=0xc0040000 exp=0xc0040000` | seq `CPU_CTRL_READS` |
| RESET_CTRL RD | 300 | `rdata=0x10f exp=0x10f` | seq |
| CORE_RESET_PULSE_COUNT RD | 307 | `rdata=0x100008 exp=0x100008` | seq |
| WDT_TIMEOUT RD | 314 | `rdata=0x4000 exp=0x4000` | seq |
| TEST_CTRL RD | 321 | `rdata=0x0 exp=0x0` | seq |
| SCRATCH WR/RD | 334–341 | write `0xc5110001`, readback match | `csr_write_readback` |
| SCRATCH restore | 348–355 | write `0`, readback `0` | `csr_restore` |
| CPU BFM obs | 357 | powergood/rst resolvable + powergood==1 | `check_cpu_bfm_observability` |
| protocol VIP | 359 | `csr_accesses=9 timeouts=0` | `record_protocol_vip` |
| cocotb result | 367–369 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether SEP_IN master-BFM CPU_CTRL reachability proves the SPEC "CPU-to-SEP" path
  properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
