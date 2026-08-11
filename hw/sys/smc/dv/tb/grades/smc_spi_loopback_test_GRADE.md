---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_spi_loopback_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_spi_loopback_test/smc_spi_loopback_test/logs/smc_spi_loopback_test.log
  sha256: cd6baec10517a78f50b11fdc94e1326dee673a363c61848e3c0f2ef9be1c00d0
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
  tag: '[NO-ALWAYS-PASS-CHECKER]'
  severity: Blocking
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_spi_loopback_test_seq.py:79-127
  observed: >-
    The "library layer" still binds `OcahSpiFlash` to `_MockSignal` stand-ins,
    never calls `init_signals()`/`start()`, and asserts only VIP-private state:
    constructor arg `jedec_id=0x20BA18` vs `flash._jedec_id`,
    `set_jedec_id(0x1F4501)` vs the same attribute, `preload(payload)` vs
    `flash._mem`, and `SpiMode` enum smoke. None of these observes DUT pins,
    AXI, or any RTL net — the checks cannot fail on any RTL behavior. Kept log
    L268–L271 prints OcahSpiFlash `PASS` lines with zero DUT SPI activity before
    the CSR probes. (Test/seq prose correctly demotes this to library-only /
    non-pad proxy; the structural issue is that these asserts remain on the
    path required for the test to PASS.)
  closure_condition: >-
    Either remove the RTL-insensitive VIP self-asserts from the proof path
    (keep them as optional import smoke outside the DUT evidence), or replace
    them with a pad-/BFM-driven SPI transaction whose FAIL-ON path depends on
    DUT/BFM responses (as `smc_spi_pad_bfm_test` is intended to provide), with
    expected values independent of the VIP object's just-programmed fields.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_spi_loopback_test_seq.py:137-145
  observed: >-
    DUT-layer probes still call `csr_read_allow_error(name, addr)` with no
    `expected`, so `smc_scoreboard` records `exp=None` and only completes the
    access. Kept log L297–L331: five PeakRDL-correct OKAY reads return
    `0x0` / `0x220000` with `exp=None ok=True`; `assert_all_reachable(5)` only
    gates issued-access count / zero timeouts. Reachability/activity alone is
    not an exact CSR-value or exact-response contract for the named registers.
  closure_condition: >-
    Assert independent exact expecteds (reset / SPEC table or approved fixed
    vectors — not RTL-copied) via `csr_read(..., expected=...)` for these OKAY
    windows; reserve `allow_error` / `expect_error` helpers for intentional
    error-slave windows only.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_spi_loopback_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🔴 1 Blocking · 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): PeakRDL CSR
> probes OKAY×5 + library VIP self-test; `TESTS=1 PASS=1 FAIL=0 SKIP=0`. Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `ff24d80a…`)

| Item | Prior (log `ff24d80a…`, FAIL) | This audit (log `cd6baec1…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 2 Blocking · 🟠 1 Major | 🔴 1 Blocking · 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand literals / false identity / DECERR @ `0xC000E008` | **cleared** — `_PROBE_READS` uses `smc_addr` / `smc_indexed_addr`; log hits `0xC0006000` / `6200` / `4020` / `4030` / `A008` OKAY×5 |
| Prior FIND-002 `[NO-ALWAYS-PASS-CHECKER]` | open Blocking — OcahSpiFlash mock self-test | **still open** as FIND-001 Blocking — `_MockSignal` + VIP-private asserts unchanged |
| Prior FIND-003 `[EXACT-EXPECTATION]` | open Major — `csr_read_allow_error` / `exp=None` | **still open** as FIND-002 Major — still `exp=None` on all five probes |
| Kept log | FAIL seed=1 (axi_monitor DECERR) | PASS seed=1; monitor `OKAY=5; 0 errors` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 2 items (🔴 1 Blocking · 🟠 1 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🔴 Blocking | `smc_spi_loopback_test_seq.py:79-127` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_spi_loopback_test_seq.py:137-145` |

<details>
<summary>1. FIND-001 — 🔴 Blocking <code>[NO-ALWAYS-PASS-CHECKER]</code> — OcahSpiFlash mock self-test cannot fail on RTL</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_spi_loopback_test_seq.py:79-127`
- **Observed:** `_MockSignal` + VIP-private `_jedec_id` / `_mem` / `SpiMode` asserts never observe DUT SPI; log L268–L271 `PASS` with no pad traffic.
- **Closure:** Drop RTL-insensitive VIP asserts from the DUT proof path, or replace with pad/BFM-driven SPI checks whose FAIL-ON depends on DUT/BFM responses.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — CSR probes have <code>exp=None</code> / allow_error only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_spi_loopback_test_seq.py:137-145`
- **Observed:** `csr_read_allow_error` + `assert_all_reachable(5)`; scoreboard `exp=None` on five PeakRDL-correct OKAY reads (`0x0` / `0x220000`).
- **Closure:** Wire independent exact expecteds via `csr_read(..., expected=...)` for these OKAY windows; do not use `allow_error` as the only contract.

</details>

**Then:** owner remediates FIND-001 (DUT-sensitive SPI or demote VIP smoke off the proof path) + FIND-002 (exact CSR expects), re-keeps a PASS log, then re-invoke `/dv_test_audit smc_spi_loopback_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — no force/deposit on DUT nets; final cocotb result is PASS from executed sequence + scoreboard, not a fabricated verdict |
| F2 can't-fail checker | 🔴 Blocking — FIND-001 |
| E1 skip-to-pass | ✅ clean — missing `ocah_spi_vip` asserts; CSR probes always run; no missing-handle skip-to-pass |
| E2 empty phase | ✅ clean — VIP API calls + 5 real SEP_IN AXI reads execute (log OKAY×5) |
| S1 silent fail | ✅ clean — VIP asserts raise; scoreboard / axi_monitor fail on unexpected resp; `assert_all_reachable` gates access count |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard checks #1–#5 and axi_monitor active in kept log |
| Phase-S obligations — L1 | 🔴 Blocking — FIND-001; 🟠 Major — FIND-002; addresses now from `smc_addr_map` (prior ADDRESS finding cleared); seed logged; enrolled in `batch_d.toml` / `all.toml`; force-free on DUT; timeout not used on probe path; ROM/efuse `$readmemh` is post-PASS bring-up trailer |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_spi_loopback_test.py`
  sha256 `cb5ad329c069e2c33169a0d7e9cfd38c71b43469760551373e4aefeeb48e884b`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_spi_loopback_test_seq.py`
  sha256 `504f275f0177f6be1b2aa64c421ad77c9a64f4719e09063953cf316b4f21b0f2`
- Addr map: `hw/sys/smc/dv/cocotb/seq_lib/smc_addr_map.py`
  sha256 `cc43ce2029ebd0ceda50d06c3f9e7e8b7d04bcdd0b63510999ae7a85afd9c803`
- Helpers (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_csr_seq_utils.py`
  (`csr_read_allow_error`, `assert_all_reachable`);
  `hw/sys/smc/dv/cocotb/env/smc_axi_monitor.py`;
  `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094608__verilator__smc_spi_loopback_test/smc_spi_loopback_test/logs/smc_spi_loopback_test.log`
  sha256 `cd6baec10517a78f50b11fdc94e1326dee673a363c61848e3c0f2ef9be1c00d0`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`; cocotb summary L341–L343:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Addressing (resolved + logged): UART_LOG_ENGINE_CTRL `0xC0006000`,
  LOG_ENGINE_CTRL `0xC0006200`, AVS_NORMAL_STATUS `0xC0004020`,
  AVS_INTERRUPT `0xC0004030`, OCTS_STATUS `0xC000A008` — all PeakRDL via
  `smc_addr_map`; monitor L335 `OKAY=5; 0 errors`
- Library layer (L268–L271): OcahSpiFlash JEDEC / preload / SpiMode `PASS`
  (VIP-only; FIND-001)
- CSR probes (L297–L331): scoreboard SYS AXI checks #1–#5 with `exp=None`
  (FIND-002)
- Protocol VIP (L332–L334): `uart_log:smc_spi_loopback_test mode=proxy
  csr_accesses=0 … passed=True` — completion marker; not a DUT SPI proof token
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0
  image load; not used as SPI/CSR golden on this proof path
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`;
  `entry_status: NOT-EVALUATED`)
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>cd6baec1…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| VIP JEDEC/preload | 268–271 | OcahSpiFlash library `PASS` lines | seq `:91-127` |
| UART_LOG_ENGINE_CTRL | 284–299 | `0xc0006000` OKAY `rdata=0` `exp=None` | seq `:57-59` |
| LOG_ENGINE_CTRL | 300–307 | `0xc0006200` OKAY `rdata=0` | seq `:60-61` |
| AVS_NORMAL_STATUS | 308–315 | `0xc0004020` OKAY `rdata=0x220000` | seq `:62-63` |
| AVS_INTERRUPT | 316–323 | `0xc0004030` OKAY `rdata=0` | seq `:64-65` |
| OCTS_STATUS | 324–331 | `0xc000a008` OKAY `rdata=0` | seq `:66` |
| axi_monitor | 335 | `OKAY=5; 0 errors` | monitor |
| protocol VIP | 332–334 | `proxy` `csr_accesses=0` `passed=True` | test `:26-35` |
| cocotb result | 337–343 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether library VIP smoke plus unrelated CSR probes prove any SPEC SPI-loopback
  property a future card would require (O2) — Skill 3; the test itself demotes pad
  evidence to `smc_spi_pad_bfm_test`.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
