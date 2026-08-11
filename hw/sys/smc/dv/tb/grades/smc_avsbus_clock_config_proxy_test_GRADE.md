---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_avsbus_clock_config_proxy_test
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
- path: hw/sys/smc/dv/build/runs/20260806_095335__verilator__smc_avsbus_clock_config_proxy_test/smc_avsbus_clock_config_proxy_test/logs/smc_avsbus_clock_config_proxy_test.log
  sha256: a810afc5716ac3150170d3b984e4d3e5c0c4fe07ae0ca3dda90a257151db2cd0
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
  tag: '[ADDRESS-FROM-AUTHORITATIVE-MAP]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_clock_config_proxy_test_seq.py:10
  observed: >-
    CLOCK_GATE_CONTROL and AVS_CFG_0 / AVS_CFG_1 / AVS_CONFIG addresses are now
    sourced via smc_addr() (seq L9–L15). Kept log (sha a810afc5…) probes
    0xc0004050 / 4054 / 4058 and CLOCK_GATE at 0xc0010018 (L293–L342), matching
    smc_addr.h — prior Blocking false-identity on 0xc000805x is closed. Residual:
    AVS_CG_EN remains the hand-copied `1 << 10` while generated
    SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__AVS_CG_EN_bm (=0x400) exists and
    sibling CG bits are already imported via smc_addr_map._field_mask. Value
    currently matches the map (latent rot only, not a wrong-register probe).
  closure_condition: >-
    Import AVS_CG_EN from the generated field mask (e.g. smc_addr_map
    _field_mask on SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__AVS_CG_EN_bm); drop the
    parallel `1 << 10` literal; re-keep a PASS log that still shows map
    addresses on the proof path.
  waived_by: null
- id: FIND-002
  tag: '[NEGATIVE-NEEDS-POSITIVE-CONTROL]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_clock_config_proxy_test_seq.py:24-33
  observed: >-
    After setting AVS_CG_EN the sequence requires csr_short_timeout (50 ns) on
    the three AVS config addresses (assert item.timed_out). There is still no
    positive-control leg proving the same AVS_CFG_*/AVS_CONFIG windows complete
    with OKAY and an independently derived exact value when AVS_CG_EN is clear
    (or before the gate write). Kept log shows expected timeout at L317/L322/L327
    and AXI monitor trailer "3 R beats, 2 B resps; R-resp tally OKAY=3" (L348) —
    the three AR probes never complete in-window (no late OKAY on those ARIDs
    in this log), but a short abandoned wait with CG on remains indistinguishable
    from a permanently dead / always-slow window without the allow-path control.
  closure_condition: >-
    At authoritative AVS_CFG_*/AVS_CONFIG addresses: (1) with AVS_CG_EN=0, prove
    frontdoor read completes OKAY with independently derived exact data; (2) with
    AVS_CG_EN=1, prove the gated/negative outcome the SPEC requires (error,
    hang-with-bounded-fail, or documented wake latency) with FAIL-ON if the allow
    path still works. Do not treat a 50 ns abandoned wait alone as gated-config
    proof.
  waived_by: null
- id: FIND-003
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py:13-28
  observed: >-
    check_sideband_observability only asserts tb_avsbus_irq /
    tb_telemetry_irq_any / tb_avsbus_cur_state_debug are resolvable, then logs
    values. Kept log L344 shows avs_irq=0 telemetry_irq=0 avs_state=0x8 (IDLE
    one-hot is defined as AVS_STATE_IDLE in the same module) with no FAIL-ON
    compare. Resolvable/activity alone is not an exact IRQ/state contract for
    the claimed "bounded IRQ/state observability".
  closure_condition: >-
    Assert exact post-stimulus expectations for the sideband observables this
    test claims (at least avs_state vs the documented IDLE/active encoding, and
    IRQ levels vs the stimulus); fail on mismatch, not only on X/Z.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_avsbus_clock_config_proxy_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `1d6ab5b5…`)

| Prior id | Tag / grade | Status this round | Notes |
|---|---|---|---|
| FIND-001 | 🔴 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` (805x false identity) | CLOSED (false identity) | Seq + kept log now use `0xc0004050/54/58` and CLOCK_GATE `0xc0010018` via `smc_addr` / `smc_addr.h` |
| — | 🟠 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` residual bit | NEW as FIND-001 🟠 | `AVS_CG_EN = 1 << 10` still hand-copied; value matches `AVS_CG_EN_bm=0x400` (latent rot) |
| FIND-002 | 🔴 `[NEGATIVE-NEEDS-POSITIVE-CONTROL]` | OPEN — unchanged | Still CG-on short-timeout-only; no ungated exact OKAY control on AVS config windows |
| FIND-003 | 🟠 `[EXACT-EXPECTATION]` | OPEN — unchanged | Sideband helper still resolvable-only; L344 `avs_state=0x8` with no exact assert |
| waivers: [] | — | unchanged | Prior ledger empty; no signed `approved_by` to carry; none dropped |
| Kept log | `1d6ab5b5…` (094605 / 805x) | replaced | `a810afc5…` (095335; seed=1 PASS; model `2c815fa08277`) |
| repository_revision | `c10b6d63…` | unchanged | `c10b6d63…` |
| seq sha256 | `3fa114e7…` | updated | `9cbd12ac…` (all three AVS timeout addrs via `smc_addr`) |

## Your to-do — 3 items (🔴 1 Blocking · 🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-002 | 🔴 Blocking | `smc_avsbus_clock_config_proxy_test_seq.py:24-33` |
| 2 | finding | FIND-001 | 🟠 Major | `smc_avsbus_clock_config_proxy_test_seq.py:10` |
| 3 | finding | FIND-003 | 🟠 Major | `smc_sideband_vip_utils.py:13-28` |

<details>
<summary>1. FIND-002 — 🔴 Blocking <code>[NEGATIVE-NEEDS-POSITIVE-CONTROL]</code> — CG timeout without allow-path control</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_clock_config_proxy_test_seq.py:24-33`
- **Observed:** After AVS_CG_EN, `csr_short_timeout` requires `timed_out` with no prior/ungated exact OKAY read of the same AVS config windows. Log: TB timeout at 50 ns (L317+) and monitor OKAY=3 only for CLOCK_GATE R beats — still no allow-path proof.
- **Closure:** Prove allow path (CG off, exact data) and gated/negative path (CG on, SPEC outcome) at authoritative AVS addresses.

</details>

<details>
<summary>2. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — AVS_CG_EN bit still hand-copied</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_clock_config_proxy_test_seq.py:10`
- **Observed:** Probe addresses closed to the generated map in code and kept log. Residual `AVS_CG_EN = 1 << 10` parallels `SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__AVS_CG_EN_bm` (0x400) — latent rot, not false identity.
- **Closure:** Source the bit from the generated field mask; drop the literal.

</details>

<details>
<summary>3. FIND-003 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — sideband only checks resolvable</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py:13-28`
- **Observed:** Only `is_resolvable` asserts; log L344 `avs_irq=0 telemetry_irq=0 avs_state=0x8` with no exact compare (IDLE encoding known in-module as `AVS_STATE_IDLE`).
- **Closure:** FAIL-ON exact IRQ/state expectations for the claimed observability, not resolvable-only.

</details>

**Then:** owner remediates FIND-002 / FIND-001 / FIND-003 on the AVS clock/config proxy proof path, re-keeps a PASS log, and re-invokes `/dv_test_audit smc_avsbus_clock_config_proxy_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; CLOCK_GATE expected is TB-programmed value vs DUT `rdata`; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — `csr_read` expected compare, `assert item.timed_out`, and `assert accesses==8 and timeouts==3` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI / resolvable asserts raise |
| E2 empty phase | ✅ clean — real AXI CG R/W/R, three timeout probes, restore, sideband sample (8 SYS AXI checks + VIP item logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok`/`timed_out`/access-count raise; sideband resolvable asserts |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (checks #1–#8) and protocol VIP check #1 |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-002; 🟠 Major — FIND-001, FIND-003; timeouts fail the sequence when not timed out; seed logged; enrolled in `batch_d.toml` / `all.toml`; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_avsbus_clock_config_proxy_test.py`
  sha256 `1a15f877474125355ba0f8e5908807583291c0ca94b5f39263d0ce7955a42895`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_avsbus_clock_config_proxy_test_seq.py`
  sha256 `9cbd12ac5618c5b1ad0d03d594e5b8587bbb6bf34e3c75b56cea94c8812c7245`
- Sideband helper: `hw/sys/smc/dv/cocotb/seq_lib/smc_sideband_vip_utils.py` (`check_sideband_observability`)
- Scoreboard / driver (proof path): `smc_scoreboard._check_sys_axi`, `smc_sys_axi_agent._drive` / `_timed_event`
- Log: `hw/sys/smc/dv/build/runs/20260806_095335__verilator__smc_avsbus_clock_config_proxy_test/smc_avsbus_clock_config_proxy_test/logs/smc_avsbus_clock_config_proxy_test.log`
  sha256 `a810afc5716ac3150170d3b984e4d3e5c0c4fe07ae0ca3dda90a257151db2cd0` (computed from file; not the stale 094605 / `1d6ab5b5…` log)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- Cocotb summary: `TESTS=1 PASS=1 FAIL=0 SKIP=0` (L354–L356)
- Stimulus: enable `AVS_CG_EN` on CLOCK_GATE_CONTROL → three `csr_short_timeout` probes → restore CLOCK_GATE → `check_sideband_observability` → protocol VIP record (`accesses=8`, `timeouts=3`)
- Exact value compares in log: CLOCK_GATE enable readback `exp=0x1f000400` (check #3) and restore `exp=0x1f000000` (check #8); timeout probes have `exp=None` and scoreboard `ok=True` via `allow_timeout`
- Authoritative map (`smc_addr.h`): AVS_CFG_* / AVS_CONFIG at `0xC000405x`; kept-log probes match (`0xc0004050/54/58`)
- AXI monitor trailer: `3 R beats, 2 B resps; R-resp tally OKAY=3` (L348) — no late OKAY completions on the three timeout ARIDs in this log (contrast prior 805x log)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden on this proof path
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>a810afc5…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| CG save / enable | 293–313 | CLOCK_GATE `0x1f000000` → write `0x1f000400` → readback match @ `0xc0010018` | seq `:25-28` |
| AVS timeout probes | 315–328 | TB expected timeout @ `0xc0004050/54/58` after 50 ns | seq `:29-30` |
| CG restore | 330–342 | write/read `0x1f000000` | seq `:31-32` |
| Sideband obs | 344 | `avs_irq=0 telemetry_irq=0 avs_state=0x8` (resolvable only) | `check_sideband_observability` |
| VIP / result | 345–356 | proxy VIP `accesses=8 timeouts=3` · `PASS` | test `:25-32` |

</details>

## Not concluded

- Whether this proxy timeout/observability sequence proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
