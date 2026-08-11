---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_axil_burst_idle_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_axil_burst_idle_test/smc_axil_burst_idle_test/logs/smc_axil_burst_idle_test.log
  sha256: a5f8951b87ede15af99486d9bb199048ddbd5b047a0a184f5ac96473fe1396ad
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

# Grade Report — smc_axil_burst_idle_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | none | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim PASS (seed 1); Layer 2 was not entered.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `b7bc9ace…`)

| Item | Prior (log `b7bc9ace…`, PASS) | This audit (log `a5f8951b…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | none | none |
| Layer 1 | F/E/S/O + Phase-S L1 clean | unchanged — same seq/agent/scoreboard/TB OR; eight SAMPLE idle asserts still fire |
| Kept log | `b7bc9ace85cb23889ed6873de4c3cf108b11a830b9e08a8131c4562bfb160cb5` | `a5f8951b87ede15af99486d9bb199048ddbd5b047a0a184f5ac96473fe1396ad` |
| Repo / auditor | rev `2ecc7b22…` · run_id `cursor/grok/4.5` | rev `c10b6d63…` · run_id `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 0 items (none)

| # | Sev | Item |
|---|---|---|
| — | — | none open |

**Then:** leave enrolled under `STANDALONE-REQUEST`, or allocate a real IP pin + card via
`/dv_vplan_gen` before any closure claim. Re-invoke `/dv_test_audit smc_axil_burst_idle_test`
only after material test/log changes. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — passive SAMPLE of `tb_axil_*_active` pins; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — seq + scoreboard `assert resolvable` and `any_master_active == 0` can fail on X/Z or spurious AXI-Lite activity; `check_phase` fails if zero SAMPLE items |
| E1 skip-to-pass | ✅ clean — unsupported `SmcAxilOp` raises; missing HDL handles raise; no skip-to-pass branch |
| E2 empty phase | ✅ clean — S2 dispatches eight SAMPLE items with 1-cycle gaps + asserts; S1 is SETUP restatement of base bring-up only |
| S1 silent fail | ✅ clean — seq / scoreboard mismatches raise `AssertionError` |
| O1 checker disabled | ✅ clean — `axil_agent.ap` connected; log shows Scoreboard AXIL sample #1–#8 |
| Phase-S obligations — L1 | ✅ clean — X-aware `resolvable`; force-free; CHK-NONVAC after idle asserts; seed logged; enrolled in `axil.toml` / `all.toml`; `ClockCycles` gaps are observation spacing (not handshake substitutes); ROM/efuse preload is post-PASS trailer; OR covers the three SMC-boundary AXI-Lite masters (`dtp`/`external`/`efuse`) matching `smc.sv` ports (this test does not claim pll/pvt) |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094547__verilator__smc_axil_burst_idle_test/smc_axil_burst_idle_test/logs/smc_axil_burst_idle_test.log`
  sha256 `a5f8951b87ede15af99486d9bb199048ddbd5b047a0a184f5ac96473fe1396ad`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `return_code: 0`, cocotb summary L316:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Test: `hw/sys/smc/dv/cocotb/tests/smc_axil_burst_idle_test.py`
  sha256 `e8c8af00b85be6c1b26ac8a2302f1578eac405a8570821ebc854f0069249c8de`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_axil_burst_idle_test_seq.py`
  sha256 `c1ac74e6622227afee2b59b0a64b6e7c63a9d5f633dfb6f1c11732bee9f73397`
- Driver: `smc_axil_agent.py:38-55` samples `tb_axil_dtp_csr_active` /
  `tb_axil_external_active` / `tb_axil_efuse_bank_active` /
  `tb_axil_any_master_active` with X/Z → `resolvable=False`
- Scoreboard: `smc_scoreboard.py:144-153` asserts resolvable + `any_master_active == 0`;
  `check_phase` requires `total > 0`
- Seq gate: after eight SAMPLE ops, asserts each `resolvable` and
  `any_master_active == 0`, then emits `CHK-NONVAC` (conditional) and
  `SMC_003 scenario PASS`
- TB ports: `tb_top.sv` OR-reduces DTP / external / efuse AXI-Lite `*_valid` into
  `tb_axil_*_active` / `tb_axil_any_master_active` (matches `smc.sv` boundary masters)
- Kept-log cites: SAMPLE #1–#8 at 4152–4194 ns (`any=0`); scoreboard #1–#8;
  CHK-NONVAC L306 (`values=[0, 0, 0, 0, 0, 0, 0, 0]`); scenario PASS L307;
  cocotb PASS L310–L316
- Enrollment: `hw/sys/smc/dv/testlists/axil.toml`, `all.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` — time-0 image load; not used as golden
  for these pin samples (policy §6 standing preload; off this proof path)
- No unexplained `ERROR`/`FATAL`/`Traceback`; only cocotb/library `DeprecationWarning`s
  and fuse-sense INFO
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>a5f8951b…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–268 | clocks + powergood + cold release | `smc_base_test` |
| S1/S2 markers | 268–269 | SETUP restatement; INSTRUMENTATION-ONLY 8× SAMPLE | seq `:25–29` |
| SAMPLE #1–#8 | 282–305 | each `resolvable=True, any=0`; scoreboard + FUNC_COV | seq loop / `_check_axil` |
| CHK-NONVAC | 306 | eight samples complete; values all 0 | seq `:42–46` |
| scenario PASS | 307 | `SMC_003 scenario PASS` | seq `:48` |
| cocotb result | 310–316 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether eight idle AXI-Lite observation samples prove the SPEC properties a future
  card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers from
  the passing log.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
