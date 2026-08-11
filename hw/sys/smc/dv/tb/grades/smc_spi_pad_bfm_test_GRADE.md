---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_spi_pad_bfm_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094609__verilator__smc_spi_pad_bfm_test/smc_spi_pad_bfm_test/logs/smc_spi_pad_bfm_test.log
  sha256: 86467d3e9241c0f589e270e11f3cd907ae168941afa63d65ff92d65a8be905b7
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
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/tests/smc_spi_pad_bfm_test.py:26-29
  observed: >-
    After the sequence returns, the test builds VIP golden with
    `exp = seq.expected_bytes if hasattr(...) else bytes([0x20, 0xBA, 0x18])`
    and `obs = seq.observed_bytes if hasattr(...) else exp`. The sequence
    always defines both attributes in `__init__`, so the `else` arms never
    run; the `else exp` arm would copy expected into observed and make the
    scoreboard byte compare unable to fail. That dead fallback resembles an
    active always-pass golden gate on the only VIP evidence path.
  closure_condition: >-
    Drop the `hasattr` / hardcoded / `else exp` fallbacks; require
    `seq.expected_bytes` and `seq.observed_bytes` from the sequence (or fail
    if missing) so the scoreboard golden can only pass on pad-sampled bytes.
  waived_by: null
- id: FIND-002
  tag: '[NO-DUMMY-DEAD-CODE]'
  severity: Minor
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_spi_pad_bfm_test_seq.py:68,152
  observed: >-
    Sequence sets `self.preload_ok = True` after the READ-preload assert, but
    nothing reads `preload_ok` (VIP recording carries only JEDEC
    `observed_bytes`). The live `assert bytes(rd) == _PRELOAD` is real; the
    unused flag looks like a second completion marker that is never gated.
  closure_condition: >-
    Remove `preload_ok`, or feed preload bytes into the VIP/scoreboard golden
    (or an explicit second evidence record) so the flag is either gone or on a
    fail-capable path.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_spi_pad_bfm_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major · 🟡 1 Minor | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> JEDEC `0x20BA18` + preload READ `deadbeef` + VIP golden=obs=`20ba18` — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `d49c937a…`)

| Item | Prior (log `d49c937a…`, PASS) | This audit (log `86467d3e…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major · 🟡 1 Minor | 🟠 1 Major · 🟡 1 Minor |
| Prior FIND-001 VIP `else exp` fallback | open Major `[NO-DUMMY-DEAD-CODE]` | **still open** as FIND-001 Major — `smc_spi_pad_bfm_test.py:26-29` unchanged (sha256 `7a69ccc0…`) |
| Prior FIND-002 unused `preload_ok` | open Minor `[NO-DUMMY-DEAD-CODE]` | **still open** as FIND-002 Minor — `smc_spi_pad_bfm_test_seq.py:68,152` unchanged (sha256 `2b6cc6f0…`) |
| New findings | — | none |
| Sim result | `TESTS=1 PASS=1 FAIL=0 SKIP=0` | same PASS shape; JEDEC OK / preload READ OK / VIP golden=obs=`20ba18` |
| Kept log | `d49c937aa15f5adbb974f0d8aa5c50dfdfd89be00714d432d49fe222559f3bc7` | `86467d3e9241c0f589e270e11f3cd907ae168941afa63d65ff92d65a8be905b7` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Auditor run_id | `cursor/grok/4.5` | `cursor/grok/4.5-reaudit-20260806` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 1 Major · 🟡 1 Minor)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_spi_pad_bfm_test.py:26-29` |
| 2 | finding | FIND-002 | 🟡 Minor | `smc_spi_pad_bfm_test_seq.py:68,152` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[NO-DUMMY-DEAD-CODE]</code> — VIP obs fallback copies expected</summary>

- **Where:** `hw/sys/smc/dv/cocotb/tests/smc_spi_pad_bfm_test.py:26-29`
- **Observed:** Dead `hasattr` fallbacks include `obs = … else exp`, which would fabricate a scoreboard match if attributes were absent; live path uses sequence fields, but the arm still reads as an always-pass golden gate.
- **Closure:** Require sequence `expected_bytes` / `observed_bytes` (fail if missing); delete hardcoded JEDEC and `else exp`.

</details>

<details>
<summary>2. FIND-002 — 🟡 Minor <code>[NO-DUMMY-DEAD-CODE]</code> — unused <code>preload_ok</code> flag</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_spi_pad_bfm_test_seq.py:68,152`
- **Observed:** `preload_ok` is set after a real READ-preload assert but never consumed; VIP evidence only carries JEDEC bytes.
- **Closure:** Drop the flag, or record preload bytes on a fail-capable VIP/scoreboard path.

</details>

**Then:** owner remediates FIND-001/FIND-002 hygiene (or leaves as enrolled pad/BFM smoke under STANDALONE-REQUEST), re-keeps a PASS log if code changes, and re-invokes `/dv_test_audit smc_spi_pad_bfm_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — TB host drives `tb_spi_*`; BFM MISO via `tb_spi_miso_ext` → pad0 → `tb_spi_rxd`; no Force/deposit on proof path; ROM/efuse `$readmemh` is post-PASS trailer |
| F2 can't-fail checker | ✅ clean — JEDEC / READ-preload `assert` and scoreboard byte compare can fail on wrong pad data; dead VIP fallback is FIND-001 (not live F2) |
| E1 skip-to-pass | ✅ clean — missing VIP / pads `assert` fail; import failure sets flag then asserts, does not pass |
| E2 empty phase | ✅ clean — JEDEC 0x9F + READ 0x03 preload exercised end-to-end through pads |
| S1 silent fail | ✅ clean — mismatches raise `AssertionError` in sequence; scoreboard asserts golden bytes |
| O1 checker disabled | ✅ clean — protocol VIP analysis path active (log check #1 + FUNC_COV) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · 🟡 Minor — FIND-002; else pad observation via `spi_rxd`, seed logged, enrolled in `batch_d.toml`/`all.toml`, bit-bang `Timer` is SCLK generation (not handshake substitute), BFM is declared external partner for pad-bind intent, no unexplained skip |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_spi_pad_bfm_test.py`
  sha256 `7a69ccc056bda6dc8131662943e7f7a12f8f5eb0cbc67af4c37d7810b6ccea8a`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_spi_pad_bfm_test_seq.py`
  sha256 `2b6cc6f0f621bd7d0152e2a85c7ac1435002a2d1622fd8d61d3dafa2893e7863`
- Scoreboard (VIP evidence): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py` `_check_protocol_vip`
- Log: `hw/sys/smc/dv/build/runs/20260806_094609__verilator__smc_spi_pad_bfm_test/smc_spi_pad_bfm_test/logs/smc_spi_pad_bfm_test.log`
  sha256 `86467d3e9241c0f589e270e11f3cd907ae168941afa63d65ff92d65a8be905b7` (matches claimed)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: exit_code 0 · cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: enable SPI mux; host JEDEC 0x9F on `tb_spi_*`; OcahSepSpiFlash responds on `tb_spi_miso_ext`; READ 0x03 @0 after in-BFM preload `deadbeef`
- Observed in log: `SPI pad BFM JEDEC OK: 0x20BA18`; `SPI pad BFM preload READ OK: deadbeef`; VIP `golden=20ba18 obs=20ba18`; `FUNC_COV_VALUE bin=protocol_vip value=('uart_log', 'smc_spi_pad_bfm_test', 0)`
- Fail path (static): JEDEC mismatch / preload mismatch / missing pads or VIP → AssertionError; scoreboard byte mismatch if VIP golden diverges; no `CHK-*` tokens (none required without a card)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Intent (docstring): pad lift + flash BFM bind — not a DUT SPI-controller JEDEC proof
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>86467d3e…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| seed / start | 13–19 | seed 1; running `smc_spi_pad_bfm_test` | cocotb / test |
| JEDEC OK | 296 | `SPI pad BFM JEDEC OK: 0x20BA18` | seq `:123-131` |
| preload READ OK | 301 | `SPI pad BFM preload READ OK: deadbeef` | seq `:148-156` |
| VIP + scoreboard | 304–306 | golden=obs=`20ba18`; FUNC_COV protocol_vip | test `:30-41` / scoreboard |
| cocotb result | 309–315 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether pad-attached BFM JEDEC/READ proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
