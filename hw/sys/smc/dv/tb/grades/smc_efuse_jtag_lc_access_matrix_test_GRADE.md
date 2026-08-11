---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_jtag_lc_access_matrix_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094619__verilator__smc_efuse_jtag_lc_access_matrix_test/smc_efuse_jtag_lc_access_matrix_test/logs/smc_efuse_jtag_lc_access_matrix_test.log
  sha256: b40ba5325e8caa160d34ed9eb814291dff6f7451f277b0b51cd79c6194b96159
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
  tag: '[TIMEOUT-MUST-FAIL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:154-224
  observed: >-
    _read/_write catch SimTimeoutError and return (None, None) / None.
    _check_read/_check_write set blocked = (code == RESP_DECERR). On an
    expect_allow transaction, timeout yields code=None → blocked=False → no
    error is appended, so a hung allow-path AXI access can pass. expect_block
    timeouts do append an error (not blocked). Bounded wait therefore does not
    fail the allow legs. This PASS log did not exercise a hang
    (timeouts=0 in protocol VIP).
  closure_condition: >-
    Treat timeout (rdata/code None) as a hard failure on every matrix leg with
    last-state diagnostics; never equate a missing resp to "not blocked".
  waived_by: null
- id: FIND-002
  tag: '[INDEPENDENT-EXPECTED-MODEL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:11-19
  observed: >-
    Module docstring states the block/allow table is an "RTL-derived matrix";
    coded matrix tuples (:91-98) and _set_lc_state
    exp_prod/exp_raw/exp_sigint (:133-135) mirror smc_efuse_wrapper.sv
    is_prod_or_rma_sip / identity-exception / sigint decode. When the RTL
    policy expression is wrong, the golden is wrong the same way, so the
    compare cannot catch an RTL transcription error. No SPEC-formula or
    pre-approved independent vector table is cited as the expect source.
  closure_condition: >-
    Derive the lifecycle × address-class allow/block expecteds from an
    authoritative SPEC table (or approved fixed vector list) independent of the
    wrapper RTL; keep the RTL only as DUT under test, not as the golden source.
  waived_by: null
- id: FIND-003
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:174-224
  observed: >-
    Allow-path checks only assert resp != DECERR (OKAY or SLVERR both pass) and
    do not require an independently derived rdata for identity/non-ID allow
    reads. Kept log shows TEST_DEV NON_ID allow with resp=2 (SLVERR) and
    CHIPLET_ID/PACKAGE_ID allow with resp=0, both accepted; allow rdata remains
    0xBADCAB1E on the Verilator stub. Block path does exact-check DECERR +
    0xBADCAB1E. "Never DECERR" alone is not an exact allow contract for the
    claimed eFuse JTAG allow outcome.
  closure_condition: >-
    On allow legs, require the SPEC/silicon response (OKAY) and an independently
    derived rdata (or an approved stub contract with an exact allowed resp set
    named in the test); fail on any other resp/data.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_jtag_lc_access_matrix_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 2 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect** in the
> test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050); Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade on log `b40ba532…`)

| Item | Prior grade | This fresh re-audit |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY (confirmed) |
| Findings | 🔴 2 Blocking · 🟠 1 Major | 🔴 2 Blocking · 🟠 1 Major (same three tags) |
| FIND-001 `[TIMEOUT-MUST-FAIL]` | open | open — allow-path timeout → not-blocked |
| FIND-002 `[INDEPENDENT-EXPECTED-MODEL]` | open | open — docstring/matrix still RTL-derived |
| FIND-003 `[EXACT-EXPECTATION]` | open | open — allow = non-DECERR only |
| Prior `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | closed in prior round (`smc_addr`) | remains closed — PeakRDL symbols → `0xC0007000/7008/7028` |
| Test sha256 | `629d6fd2…` | `629d6fd209c8b1f91be5c8c5fb7ddbe1297e2cc5bb02e46d4c9dbe151a45e70c` |
| Kept log | `b40ba532…` PASS | same hash verified via `manifest.py hash-file` |
| Repo / model | `c10b6d63…` / `2c815fa08277` | unchanged |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 3 items (🔴 2 Blocking · 🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_efuse_jtag_lc_access_matrix_test.py:154-224` |
| 2 | finding | FIND-002 | 🔴 Blocking | `smc_efuse_jtag_lc_access_matrix_test.py:11-19` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_efuse_jtag_lc_access_matrix_test.py:174-224` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[TIMEOUT-MUST-FAIL]</code> — allow-path timeout treated as not-blocked</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:154-224`
- **Observed:** `with_timeout` expiry returns `None` resp; `blocked = (code == RESP_DECERR)` makes expect_allow legs silently pass on hang. Block legs still fail on timeout.
- **Closure:** Fail every matrix leg on timeout with diagnostics; never treat missing resp as allow.

</details>

<details>
<summary>2. FIND-002 — 🔴 Blocking <code>[INDEPENDENT-EXPECTED-MODEL]</code> — matrix golden transcribed from RTL</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:11-19` (matrix `:91-98`, decode expecteds `:133-135`)
- **Observed:** Docstring admits an "RTL-derived matrix"; coded allow/block and `exp_prod` mirror `smc_efuse_wrapper` decode. RTL bug ⇒ same-way golden bug.
- **Closure:** Source expecteds from SPEC / approved independent vector table, not the wrapper RTL.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — allow path is only non-DECERR</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py:174-224`
- **Observed:** Allow accepts OKAY or SLVERR with no exact rdata; block path does exact DECERR+`0xBADCAB1E`. Log: TEST_DEV NON_ID `resp=2` and ID `resp=0` both pass as allow.
- **Closure:** Pin allow to exact resp (+ independent rdata or approved stub contract).

</details>

**Then:** owner remediates FIND-001/FIND-002/FIND-003, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_efuse_jtag_lc_access_matrix_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — product `tb_lc_state` + `ej_axi` AXI-Lite master; no Force/deposit on proof path; hierarchy probe is read-only |
| F2 can't-fail checker | ✅ clean — matrix mismatch appends `self.errors` and final `assert not self.errors` has a reachable FAIL-ON (allow timeout hole is FIND-001, not tautological compare) |
| E1 skip-to-pass | ✅ clean — optional LC decode probe unavailable does not mark pass; AXI matrix still scored (24 checks) and final gate executed |
| E2 empty phase | ✅ clean — 6 LC states × (3 reads + 1 write) coded; 24 AXI checks logged before PASS |
| S1 silent fail | 🔴 Blocking — FIND-001 (allow-path timeout → not-blocked); mismatch path itself raises via `self.errors` |
| O1 checker disabled | ✅ clean — matrix checker executed; final assertion gate reached; protocol VIP recorded `csr_accesses=24` |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001, FIND-002; 🟠 Major — FIND-003; addresses from PeakRDL `smc_addr.h` via `smc_addr`; seed logged; enrolled in `vplan_triplets.toml` / `all.toml`; negative PROD/RMA_SIP paired with TEST_DEV allow legs; LC decode white-box skipped (`u_smc` missing under `u_dut`); no unconditional CHK success token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation / sequence (inline `run_scenario`): `hw/sys/smc/dv/cocotb/tests/smc_efuse_jtag_lc_access_matrix_test.py`
  sha256 `629d6fd209c8b1f91be5c8c5fb7ddbe1297e2cc5bb02e46d4c9dbe151a45e70c`
- Address helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py`
  sha256 `cc43ce2029ebd0ceda50d06c3f9e7e8b7d04bcdd0b63510999ae7a85afd9c803`
- Base / VIP: `smc_base_test`, `OcahAxiLiteMaster` on `ej_axi`, `tb_lc_state`
- Log: `hw/sys/smc/dv/build/runs/20260806_094619__verilator__smc_efuse_jtag_lc_access_matrix_test/smc_efuse_jtag_lc_access_matrix_test/logs/smc_efuse_jtag_lc_access_matrix_test.log`
  sha256 `b40ba5325e8caa160d34ed9eb814291dff6f7451f277b0b51cd79c6194b96159`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L430–L432:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Addressing: `smc_addr(SMC_TOP_SMC_EFUSE_MAP_{LOCKS,CHIPLET_ID,PACKAGE_ID}_BASE_ADDR)` →
  `0xC0007000` / `7008` / `7028` (matches `smc_addr.h`)
- Stimulus: pack/drive `tb_lc_state` for TEST_DEV / PROD / RMA_SIP / RMA_CHIPLET /
  PROD_END / SIGINT → JTAG eFuse read NON_ID/CHIPLET_ID/PACKAGE_ID + write NON_ID
- Observed PASS matrix (resp discriminator): PROD/RMA_SIP NON_ID+write DECERR;
  PROD/RMA_SIP CHIPLET_ID/PACKAGE_ID OKAY (`resp=0`); SIGINT all DECERR; allow
  non-ID legs may be SLVERR (`resp=2`) on Verilator stub
- LC decode probe: `lc decode probe unavailable: … no child object named u_smc` (L326+)
- Protocol VIP / scoreboard: `csr_accesses=24` / `timeouts=0` / `passed=True` (L421–L422)
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml`, `all.toml`
- Bring-up trailer (post-PASS): fuse-sense / ROM hex plusarg — not used as matrix golden
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)
- Auditor: `cursor/grok/4.5-reaudit-20260806` (fresh L1 re-audit)

</details>

<details>
<summary>PASS cite (kept log <code>b40ba532…</code>)</summary>

| Step | Line | What the log shows | Impl |
|---|---|---|---|
| TEST_DEV allow | 337–354 | NON_ID `resp=2`, CHIPLET/PACKAGE `resp=0`, write `resp=2`; all `blocked=False` | `:102-105` |
| PROD NON_ID / write | 358, 367 | DECERR + `0xbadcab1e` (exp block) | `:102`, `:105` |
| PROD ID allow | 361–364 | CHIPLET/PACKAGE `resp=0`, `exp_block=False` | `:103-104` |
| RMA_SIP ID allow | 374–377 | same OKAY vs ALLOW | `:103-104` |
| SIGINT lockdown | 410–419 | all four DECERR as expected | `:102-105` |
| final gate / VIP | 421–432 | `assert not errors` passed; protocol VIP 24; `PASS` | `:110-111` |

</details>

## Not concluded

- Whether the matrix proves the SPEC JTAG eFuse lifecycle policy a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
