---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_input_output_fabric_wr_rd_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094555__verilator__smc_input_output_fabric_wr_rd_test/smc_input_output_fabric_wr_rd_test/logs/smc_input_output_fabric_wr_rd_test.log
  sha256: 49d2891ce77260bf011606a20b08f557d72ce254d40e6d774599087cb709a21c
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

# Grade Report — smc_input_output_fabric_wr_rd_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): pass-all filter program,
> JTAG AXI WR/RD through SYS_OUT with memory-model golden, and output-responder
> last_addr/last_wdata gates all executed — Layer 2 entry is still not
> evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `6f8e4443…`)

| Item | Prior (log `6f8e4443…`, PASS) | This audit (log `49d2891c…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 matrix | all L1 rows ✅ clean; L2 — not evaluated | unchanged — L1 ✅ clean; L2 — not evaluated |
| Kept log | `6f8e44434f9a90e14644cb9f9fa1554fdd6064c205a8419fc5b4af362b29296f` | `49d2891ce77260bf011606a20b08f557d72ce254d40e6d774599087cb709a21c` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| auditor.run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN filter CSR writes + JTAG AXI WR/RD; TB `tb_output_axi_*` are passive hierarchical reads; TB-local `SmcMemoryModel` golden (not DUT deposit); no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — `assert accesses == 6`, scoreboard `resp_ok` / memory-model `got == exp`, responder `last_addr`/`last_wdata` equality, and `memory_model_{updates,checks}_seen >= 1` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI timeout raises `AssertionError` |
| E2 empty phase | ✅ clean — 6 filter CSR writes, JTAG write+read, responder delta, model update/check gates all execute |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; SYS_OUT monitor `check_phase` asserts on DECERR |
| O1 checker disabled | ✅ clean — SYS AXI + memory-model scoreboard and SYS_OUT monitor active (log checks #1–#8; memory-model UPDATE/CHECK #1; monitor 1R/1B) |
| Phase-S obligations — L1 | ✅ clean — filter CSR addresses from PeakRDL `smc_reg.py`; fabric window `0x0200_0008` is TB axi_sim_mem (not an SMC CSR); post-AXI `ClockCycles(8)` settle after handshake (not a completion substitute); timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS trailer not golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_input_output_fabric_wr_rd_test.py`
- Proof-path helpers (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_output_fabric_vip_utils.py`
  (`output_fabric_pass_all_cfg_seq`, `jtag_axi_write`/`read`, `check_output_responder_delta`)
- Name-adjacent seq (not invoked by this test; used by `smc_input_fabric_axi_wr_rd_test`):
  `hw/sys/smc/dv/cocotb/seq_lib/smc_input_output_fabric_wr_rd_test_seq.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
  (`update_golden` / `check_golden`)
- SYS_OUT monitor: `hw/sys/smc/dv/cocotb/env/smc_output_axi_monitor.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094555__verilator__smc_input_output_fabric_wr_rd_test/smc_input_output_fabric_wr_rd_test/logs/smc_input_output_fabric_wr_rd_test.log`
  sha256 `49d2891ce77260bf011606a20b08f557d72ce254d40e6d774599087cb709a21c`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: program inbound/outbound filter-0 pass-all → JTAG AXI write
  `0x02000008 <- 0x8877665544332211` with `update_golden` → JTAG read
  `check_golden` → `check_output_responder_delta(write_delta=1, read_delta=1,
  last_addr/last_wdata)` → `memory_model_{updates,checks}_seen >= 1`
- Observed in log: SYS AXI checks #1–#6 (filter CSR) + #7–#8 (JTAG WR/RD);
  memory-model UPDATE #1 / CHECK #1; SYS_OUT monitor `1 R / 1 B` OKAY;
  protocol VIP `csr_accesses=8`
- Addressing: filter CSR symbols from PeakRDL
  `SMC_{INBOUND,OUTBOUND}_FILTER_CTRL_0__*` in `smc_output_fabric_vip_utils.py:22-36`;
  `OUTPUT_FABRIC_ALT_ADDR` is TB SYS_OUT window (documented non-CSR)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout;
  scoreboard memory-model mismatch raises
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as fabric golden substitution
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>49d2891c…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| inbound pass-all | 280–308 | SEP_IN writes `0xc0015008/10/00` | vip_utils `:62-67` |
| outbound pass-all | 309–328 | SEP_IN writes `0xc0016008/10/00` | vip_utils `:69-74` |
| JTAG write + golden | 330–338 | write `0x02000008`; memory-model UPDATE #1 | test `:37-43` |
| JTAG read + golden | 339–353 | read matches; memory-model CHECK #1 | test `:44-49` |
| responder + VIP | 354–358 | protocol VIP csr_accesses=8; SYS_OUT 1R/1B | test `:50-70` |
| cocotb result | 359–366 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether JTAG→SYS_OUT WR/RD plus filter pass-all proves the SPEC properties a
  future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
