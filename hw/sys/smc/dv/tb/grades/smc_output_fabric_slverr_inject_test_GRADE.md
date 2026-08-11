---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_output_fabric_slverr_inject_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094616__verilator__smc_output_fabric_slverr_inject_test/smc_output_fabric_slverr_inject_test/logs/smc_output_fabric_slverr_inject_test.log
  sha256: 9996b6aab270c05daff6d9e161e3cf137be6508b9586aa084ac49f87b0289059
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

# Grade Report — smc_output_fabric_slverr_inject_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): OKAY WR/RD positive control,
> TB axi_sim_mem `rerr` SLVERR inject + exact `resp_code`/rdata/monitor delta,
> clear + OKAY readback, responder and memory-model activity gates — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `9996b6aa…`)

| Item | Prior (log `9996b6aa…`, PASS) | This audit (log `9996b6aa…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none (0 Blocking · 0 Major · 0 Minor) | none (0 Blocking · 0 Major · 0 Minor) |
| Layer 1 matrix | all L1 rows ✅ clean; L2 — not evaluated | unchanged — L1 ✅ clean; L2 — not evaluated |
| Kept log | `9996b6aab270c05daff6d9e161e3cf137be6508b9586aa084ac49f87b0289059` | same (sha256 re-verified) |
| repository_revision | `c10b6d63…` | `c10b6d63…` |
| auditor.run_id | `cursor/grok/4.5-reaudit-20260806` | `cursor/grok/4.5-reaudit-20260806` (fresh-context reconfirm) |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN filter CSR + JTAG AXI; `_program_sys_out_err` writes TB-owned `axi_sim_mem` werr/rerr via `tb_output_err_*` (documented non-DUT Force); `tb_output_axi_*` observation is passive |
| F2 can't-fail checker | ✅ clean — exact `resp_code` OKAY/SLVERR, SLVERR rdata vs stored DATA, monitor `r_slverr`/`r_okay`/`b_okay` deltas, responder last_addr/last_wdata, `memory_model_{updates,checks}_seen` equality are reachable `AssertionError` paths; scoreboard `expected_resp` binds SLVERR on the inject beat |
| E1 skip-to-pass | ✅ clean — missing `tb_output_err_we` / `tb_output_axi_bresp` asserts fail bring-up; AXI timeout raises; no missing-handle skip-to-pass |
| E2 empty phase | ✅ clean — pass-all cfg (6 CSR), Phase A OKAY WR/RD, Phase B SLVERR read, Phase C clear+OKAY, responder/model/monitor gates all execute |
| S1 silent fail | ✅ clean — mismatch/timeout raise; scoreboard `expected_resp` assert on proof path; SYS_OUT monitor `check_phase` fails on DECERR |
| O1 checker disabled | ✅ clean — SYS AXI + memory-model scoreboard and SYS_OUT monitor active (`allow_slverr` only permits expected inject; DECERR still hard-fails); log checks #1–#10 + memory-model UPDATE/CHECK |
| Phase-S obligations — L1 | ✅ clean — filter CSR addresses from PeakRDL `smc_reg.py`; fabric window `0x0200_0000` is TB axi_sim_mem (not an SMC CSR); SLVERR negative has same-test OKAY positive control; post-AXI `ClockCycles(8)` settle after handshake (not a completion substitute); timeouts fail; seed logged; enrolled in `vplan_triplets.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS trailer not golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_output_fabric_slverr_inject_test.py`
  sha256 `4ef1361a85fe0cbab62f9af311df7f643893c69445fc369f9c70b369e63e52e2`
  (scenario inline in `run_scenario`; no separate `*_seq.py`)
- Proof-path helpers (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_output_fabric_vip_utils.py`
  sha256 `eee6662628f092d536ef5b0369431604a2373f56308d313347280d3f1558b201`
  (`output_fabric_pass_all_cfg_seq`, `jtag_axi_write`/`read`, `check_output_responder_delta`,
  `output_fabric_model`, RESP_* constants)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
  (`expected_resp`, `update_golden` / `check_golden`; `allow_error` softens `resp_ok` only —
  exact SLVERR still gated by `expected_resp` + test asserts)
- SYS_OUT monitor: `hw/sys/smc/dv/cocotb/env/smc_output_axi_monitor.py`
- Agent timeout FAIL-ON: `hw/sys/smc/dv/cocotb/env/smc_sys_axi_agent.py`
- TB err-map API: `hw/sys/smc/dv/tb/tb_top.sv` programs `u_output_mem.{w,r}err` on
  `tb_output_err_we` (external-slave model; silicon-equivalent SLVERR)
- Log: `hw/sys/smc/dv/build/runs/20260806_094616__verilator__smc_output_fabric_slverr_inject_test/smc_output_fabric_slverr_inject_test/logs/smc_output_fabric_slverr_inject_test.log`
  sha256 `9996b6aab270c05daff6d9e161e3cf137be6508b9586aa084ac49f87b0289059`
  (content hash re-verified; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: program inbound/outbound filter-0 pass-all → Phase A JTAG WR/RD OKAY
  with golden → program `tb_output_err_*` SLVERR → Phase B JTAG read
  `allow_error` + `expected_resp=SLVERR` + rdata==stored DATA → clear err map →
  Phase C OKAY golden readback → responder delta (1W/3R) + model update/check
  counts + monitor tallies
- Observed in log: SYS AXI checks #1–#6 (filter CSR) + #7–#10 (JTAG WR + 3 RD);
  memory-model UPDATE #1 / CHECK #1–#2; JTAG read `rresp: 2` at L356–L358;
  SYS_OUT monitor snap `r_okay=2, r_slverr=1, b_okay=1`; protocol VIP
  `csr_accesses=10`
- Addressing: filter CSR symbols from PeakRDL
  `SMC_{INBOUND,OUTBOUND}_FILTER_CTRL_0__*` in `smc_output_fabric_vip_utils.py:22-36`;
  `OUTPUT_FABRIC_ADDR` is TB SYS_OUT window (documented non-CSR)
- Shortcut posture: `tb_output_err_*` programs pulp `axi_sim_mem` werr/rerr
  (external-slave model API with silicon-equivalent SLVERR); Phase A exercises
  the same fabric path with inject OFF
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (also listed in suite
  arrays therein)
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as fabric golden substitution
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>9996b6aa…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| inbound pass-all | 280–308 | SEP_IN writes `0xc0015008/10/00` | vip_utils `:62-67` |
| outbound pass-all | 309–329 | SEP_IN writes `0xc0016008/10/00` | vip_utils `:69-74` |
| Phase A WR + golden | 330–338 | write `0x02000000`; memory-model UPDATE #1 | test `:63-71` |
| Phase A RD + golden | 339–353 | read OKAY; memory-model CHECK #1 | test `:72-82` |
| Phase B SLVERR RD | 354–360 | `rresp: 2`; scoreboard check #9 | test `:86-100` |
| Phase C OKAY RD | 361–369 | read OKAY; memory-model CHECK #2 | test `:103-113` |
| responder + monitor | 370–375 | snap `r_slverr=1`; SYS_OUT 3R/1B | test `:115-145` |
| cocotb result | 376–383 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether OKAY→SLVERR→OKAY through JTAG→SYS_OUT plus filter pass-all proves the
  SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
