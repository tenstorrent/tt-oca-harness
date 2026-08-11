---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_output_fabric_wr_rd_responder_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094615__verilator__smc_output_fabric_wr_rd_responder_test/smc_output_fabric_wr_rd_responder_test/logs/smc_output_fabric_wr_rd_responder_test.log
  sha256: 96d0efed07d75fd96eb7493991d4b882217ae0c2056bb0f46b60b2dd4bb0c544
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

# Grade Report — smc_output_fabric_wr_rd_responder_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): pass-all filter program,
> JTAG AXI WR/RD through SYS_OUT, SmcMemoryModel UPDATE#1/CHECK#1, and
> responder last_addr/last_wdata match — Layer 2 entry is still not evaluated
> in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `7145a522…`)

| Item | Prior (log `7145a522…`, PASS) | This audit (log `96d0efed…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 matrix | all L1 rows ✅ clean; L2 — not evaluated | unchanged — L1 ✅ clean; L2 — not evaluated |
| Kept log | `7145a52276f54780cf91171b95ae05c38357efd5bfc80b619edcff77b7c5e439` | `96d0efed07d75fd96eb7493991d4b882217ae0c2056bb0f46b60b2dd4bb0c544` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN CSR + JTAG AXI fabric WR/RD; TB-local `SmcMemoryModel` golden (not DUT deposit); responder counters are passive TB observe; no force on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` / memory-model `got == exp`, responder `last_addr`/`last_wdata` exact asserts, count floors, `memory_model_*_seen >= 1`, and `accesses == 6` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle / allow_timeout skip branch; AXI timeout raises |
| E2 empty phase | ✅ clean — 6 filter CSR writes, 1 fabric write, 1 fabric read, responder delta, model activity gates all execute (log checks #1–#8 + UPDATE/CHECK #1) |
| S1 silent fail | ✅ clean — mismatch/timeout raise; scoreboard asserts on OKAY + golden compare |
| O1 checker disabled | ✅ clean — SYS AXI + memory-model scoreboard path active; protocol VIP records after asserts (does not assert `passed`) |
| Phase-S obligations — L1 | ✅ clean — filter CSR addrs from PeakRDL `smc_reg.py`; fabric window is TB `axi_sim_mem` base (not an SMC CSR); timeouts fail; min activity on model/responder; seed logged; enrolled in `vplan_triplets.toml`; `ClockCycles(8)` is post-AXI settle before TB counter sample (completion already handshake-owned); ROM/efuse trailer not proof-path substitution |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_output_fabric_wr_rd_responder_test.py`
  (scenario body lives in the test; no separate `*_test_seq.py`)
- Helpers: `hw/sys/smc/dv/cocotb/seq_lib/smc_output_fabric_vip_utils.py`
  (`output_fabric_pass_all_cfg_seq`, `jtag_axi_write`/`read`, `check_output_responder_delta`)
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
  (`update_golden` / `check_golden` → TB `SmcMemoryModel`)
- SYS_OUT monitor: `hw/sys/smc/dv/cocotb/env/smc_output_axi_monitor.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094615__verilator__smc_output_fabric_wr_rd_responder_test/smc_output_fabric_wr_rd_responder_test/logs/smc_output_fabric_wr_rd_responder_test.log`
  sha256 `96d0efed07d75fd96eb7493991d4b882217ae0c2056bb0f46b60b2dd4bb0c544`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L359–L365:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: inbound/outbound pass-all filter program (6 SEP_IN writes) → JTAG AXI
  write `0x02000000`/`0x1122334455667788` with `update_golden` → JTAG AXI read
  with `check_golden` → `check_output_responder_delta(write/read_delta=1,
  last_addr/last_wdata)` → `memory_model_updates_seen/checks_seen >= 1`
- Observed in log: SYS AXI checks #1–#6 filter CSR; #7 write + memory-model
  UPDATE #1; #8 read `rdata=0x1122334455667788` + CHECK #1; SYS_OUT monitor
  `1 R / 1 B; R {OKAY=1}; B {OKAY=1}`; protocol VIP details updates=1 checks=1
- Addressing: filter CSR symbols from `hw/sys/smc/regs/gen/py/smc_reg.py`
  (`SMC_*_FILTER_CTRL_0__*_REG_ADDR`); log addrs `0xc0015000`/`0xc0016000`
  match; `OUTPUT_FABRIC_ADDR` is TB SYS_OUT window (not PeakRDL CSR)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout;
  scoreboard memory-model mismatch raises
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image
  load; not used as fabric golden substitution
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>96d0efed…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| inbound pass-all | 280–308 | SEP_IN writes START/END/CONFIG `@0xc0015008/10/00` | `program_inbound_pass_all` |
| outbound pass-all | 309–328 | SEP_IN writes `@0xc0016008/10/00` wdata `0x1003013` | `program_outbound_pass_all` |
| fabric write | 330–338 | JTAG write `@0x02000000` ← `0x1122334455667788`; UPDATE #1 | `jtag_axi_write(update_golden)` |
| fabric read | 339–353 | JTAG read rdata match; CHECK #1 | `jtag_axi_read(check_golden)` |
| responder / VIP | 354–358 | protocol VIP updates=1 checks=1; SYS_OUT `1R/1B` OKAY | `check_output_responder_delta` + monitors |
| cocotb result | 359–365 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether JTAG AXI WR/RD plus TB responder/scoreboard golden proves the SPEC output-fabric
  filter/security properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
