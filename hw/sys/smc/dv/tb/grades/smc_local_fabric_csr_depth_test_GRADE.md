---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_local_fabric_csr_depth_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094556__verilator__smc_local_fabric_csr_depth_test/smc_local_fabric_csr_depth_test/logs/smc_local_fabric_csr_depth_test.log
  sha256: 72b7ad2318c5b08e2f5df879315fa0d0f70f089602c8198b2242794fdfed143a
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

# Grade Report — smc_local_fabric_csr_depth_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): all 12
> SEP_IN SYS AXI local-fabric CSR reset-value reads completed OKAY with scoreboard
> `rdata == PeakRDL REG_DEFAULT` — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `ecdc234f…`)

| Item | Prior (log `ecdc234f…`, PASS) | This audit (log `72b7ad23…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 matrix | all F/E/S/O + Phase-S L1 ✅ clean; L2 — not evaluated | **unchanged** — same structural clean |
| Kept log | `ecdc234f42aa29e7e05a5549c690b8caa0a2d15585bdf6b42a2bb4e290bbaa45` | `72b7ad2318c5b08e2f5df879315fa0d0f70f089602c8198b2242794fdfed143a` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
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
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to PeakRDL `*_REG_DEFAULT`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` / `resp_ok`, driver timeout `AssertionError`, and final `assert self.accesses == 12` are reachable FAIL-ON paths; non-zero goldens (`0x40000000`, `0x1f000000`, `0x3000`, `0x60`) defeat always-zero tautology |
| E1 skip-to-pass | ✅ clean — strict `csr_read` (no `allow_timeout` / skip-on-missing-handle) |
| E2 empty phase | ✅ clean — 12 real SYS AXI reads across base_config / mailbox / alias / filter / UART+log_engine / zeroer windows |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (log checks #1–#12) |
| Phase-S obligations — L1 | ✅ clean — addresses + expecteds from generated `smc_reg.py`; exact expecteds on every read; timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094556__verilator__smc_local_fabric_csr_depth_test/smc_local_fabric_csr_depth_test/logs/smc_local_fabric_csr_depth_test.log`
  sha256 `72b7ad2318c5b08e2f5df879315fa0d0f70f089602c8198b2242794fdfed143a`
  (verified via `manifest.py hash-file` / `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.accesses == len(LOCAL_FABRIC_READS)` (12) reached;
  value proof is SYS AXI scoreboard `got == exp` on every read (12/12 logged)
- AXI monitor: `12 R beats, 0 B resps; R-resp tally OKAY=12; 0 errors`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_local_fabric_csr_depth_test.py` starts
  `smc_local_fabric_csr_depth_test_seq` on `sys_axi_agent.sequencer`
- Seq: `LOCAL_FABRIC_READS` (12 tuples) → `csr_read(name, addr, expected, length)` for each
- Addressing / goldens: imported symbols from `hw/sys/smc/regs/gen/py/smc_reg.py`
  (`SMC_*_REG_ADDR` + `*_REG_DEFAULT`); auditor spot-check matched log addrs/values
  (e.g. GLOBAL_BASE `0xc0010000`→`0x40000000`, CLOCK_GATE `0xc0010018`→`0x1f000000`,
  FILTER_CONFIG `0xc0016000`→`0x3000`, UART0_LSR `0xc0006114`→`0x60`)
- Driver FAIL-ON: `smc_sys_axi_agent.py:160-163` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied)
- Scoreboard value check: `smc_scoreboard.py:179-194` asserts `resp_ok` and `rdata` vs
  `expected` when set (all twelve reads set expected); env connects
  `sys_axi_agent.ap` → scoreboard
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not
  used as CSR golden substitution on this proof path (policy §6 standing preload)
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>72b7ad23…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| GLOBAL_BASE RD | 293 | `0xc0010000` rdata=`0x40000000` exp match | `LOCAL_FABRIC_READS[0]` |
| CLOCK_GATE_CONTROL RD | 300 | `0xc0010018` rdata=`0x1f000000` exp match | seq |
| MAILBOX0_OUT_ERROR_FLAGS RD | 307 | `0xc0018018` rdata=`0x0` exp match | seq (avoids live STATUS.empty) |
| ALIAS0_START / ATTRS RD | 314 / 321 | `0xc0012000` / `0xc0012010` → `0x0` | seq |
| OUTBOUND0 FILTER/START RD | 328 / 335 | `0xc0016000`→`0x3000`, `0xc0016008`→`0x0` | seq |
| UART0_LOG_ENGINE_CTRL / LSR / LOG_ENGINE0 | 342 / 349 / 356 | `0xc0006000`→`0`, `0xc0006114`→`0x60`, `0xc0006200`→`0` (len=4) | seq |
| ZEROER DEST/SIZE RD | 363 / 370 | `0xc0038200` / `0xc0038208` → `0x0` | seq |
| AXI monitor | 372 | `12 R beats; OKAY=12; 0 errors` | monitor |
| cocotb result | 378–380 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether these twelve reset-value reads prove the SPEC local-fabric decode/route properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
