---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_gpio_strap_sanity_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094622__verilator__smc_gpio_strap_sanity_test/smc_gpio_strap_sanity_test/logs/smc_gpio_strap_sanity_test.log
  sha256: f6747d3f1f42ed84b1af991b9eebd5361d77a2801bf550634740b11ebbd4425d
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_active_test_seq.py:10
  observed: >-
    GPIO0 `DATA_CTRL` and mailbox IRQEN addresses are now imported via
    `smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)` and
    `smc_addr("SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_0_IRQEN_BASE_ADDR")`; kept
    log writes/reads `0xc0003000` / `0xc0018038` (PeakRDL). Field encode on the
    proof path remains the hand-shifted literal
    `GPIO_INPUT_ACTIVE_LOW_IRQ = (2 << 4) | (1 << 16) | (1 << 18) | (1 << 20)`
    instead of symbols from generated `hw/ip/gpio/regs/gen/c/gpio_intf.h`
    (`GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_*` / `INTERFACE_ENABLE_*` /
    `INTERRUPT_ENABLE_*` / `INTERRUPT_TYPE_*`). Numeric value currently matches
    the header (`0x150020`), so identity is correct today, but RDL regen can
    silently rot the active-low IRQ program word.
  closure_condition: >-
    Import DATA_CTRL field masks/bit positions from generated `gpio_intf.h`
    (or an `smc_addr_map` helper that loads those symbols) and build
    `GPIO_INPUT_ACTIVE_LOW_IRQ` from them; re-keep a PASS log.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_active_test_seq.py:25
  observed: >-
    Sequence labels the mailbox access `MAILBOX_IRQEN_AS_IRQ_PROXY` and
    documents an IRQ-control decode precheck, but calls
    `csr_read(..., MAILBOX_IRQEN, length=8)` with `expected=None`. Kept log
    L305–L306 shows SEP_IN read `0xc0018038 -> 0x0` OKAY and scoreboard check
    #2 `exp=None ok=True`. Only `assert self.accesses == 2` gates completion —
    bus activity alone, no exact IRQEN value/transition contract.
  closure_condition: >-
    State an exact expected value (or documented reset/decode contract) on the
    mailbox IRQEN read and fail on mismatch; or drop the proxy claim and keep
    the GPIO VIP polarity path as the sole proof without a value-free CSR
    "decode" step.
  waived_by: null
- id: FIND-003
  tag: '[NO-BLIND-DELAY-SYNC]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_vip_utils.py:14-26
  observed: >-
    `check_gpio0_active_low_irq` (invoked by this test at
    `smc_gpio_strap_sanity_test.py:22`) uses fixed `ClockCycles(..., 24)` after
    each pad drive, then samples `tb_gpio_irq_any`, with no bounded predicate
    wait that fails on expiry. The settle stands in for IRQ assertion /
    deassertion completion; under a slower path the same delay would sample too
    early and pass/fail by luck.
  closure_condition: >-
    Replace settle-then-sample with a bounded wait for the expected
    `tb_gpio_irq_any` level (and the complementary deassert) that raises on
    timeout with last-state diagnostics; keep a fixed delay only if that latency
    itself is the SPEC quantity under test.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_gpio_strap_sanity_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 3 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect** in the test by itself. Kept log is a sim **PASS** (seed 1): GPIO0
> `DATA_CTRL` write and VIP toggle succeed — Layer 2 entry is still not evaluated
> in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `acc27320…`)

| Item | Prior (log `acc27320…`, FAIL) | This audit (log `f6747d3f…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 3 Major |
| Prior FIND-001 address | open Blocking — `0xC0004000` = AVSBus, not GPIO0 | **closed** — `smc_indexed_addr(...)` → `0xc0003000`; log L280–L293 write OKAY |
| Field encodes | bundled under prior Blocking FIND-001 | **open** as FIND-001 Major — still hand-shifted vs `gpio_intf.h` |
| Prior FIND-001 mailbox addr | noted as correct-but-unsourced hand literal | **closed** — `smc_addr("…MAILBOX_0_IRQEN…")`; residual value-free read filed as FIND-002 `[EXACT-EXPECTATION]` |
| Prior FIND-002 settle | open Major `[NO-BLIND-DELAY-SYNC]` | **still open** as FIND-003 Major — VIP `ClockCycles(..., 24)` unchanged |
| Kept log | FAIL `GPIO0 active-low drive did not assert IRQ` | PASS seed=1; VIP success L308; protocol VIP `passed=True` L309–L310 |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 3 items (🟠 3 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand-shifted DATA_CTRL field encodes |
| 2 | 🟠 Major | FIND-002 `[EXACT-EXPECTATION]` — mailbox IRQEN proxy read with `expected=None` |
| 3 | 🟠 Major | FIND-003 `[NO-BLIND-DELAY-SYNC]` — fixed 24-cycle settle in VIP helper before IRQ sample |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> at field encode literal</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_active_test_seq.py:10`
- **Observed:** Address identity is fixed. `GPIO_INPUT_ACTIVE_LOW_IRQ` is still
  hand-shifted; it currently equals `gpio_intf.h` field packs (`0x150020`) but
  is not imported from the generated map.
- **Closure:** Build the program word from `GPIO_INTF__DATA_CTRL__*` symbols in
  `hw/ip/gpio/regs/gen/c/gpio_intf.h` (or an `smc_addr_map` loader); re-keep PASS log.

</details>

<details>
<summary>2. 🟠 Major — FIND-002 <code>[EXACT-EXPECTATION]</code> at mailbox IRQEN proxy</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_active_test_seq.py:25`
- **Observed:** `MAILBOX_IRQEN_AS_IRQ_PROXY` read has no exact expected value;
  scoreboard #2 `exp=None` / rdata `0x0`. Decode-precheck claim is activity-only.
- **Closure:** Add exact expected (or drop the proxy decode claim); fail on mismatch.

</details>

<details>
<summary>3. 🟠 Major — FIND-003 <code>[NO-BLIND-DELAY-SYNC]</code> at VIP settle</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_vip_utils.py:14-26`
  (called from `smc_gpio_strap_sanity_test.py:22`)
- **Observed:** Fixed 24 `ClockCycles` then IRQ sample — completion sync by
  magic cycle count, not a TIMEOUT-failing predicate wait.
- **Closure:** Bounded wait for expected `tb_gpio_irq_any` level with fail-on-expiry
  and last-state diagnostics.

</details>

**Then:** owner imports field symbols (FIND-001), adds an exact mailbox expectation or
drops the proxy claim (FIND-002), replaces the blind settle (FIND-003), re-keeps a
PASS log, and re-invokes `/dv_test_audit smc_gpio_strap_sanity_test`. Do not invent a
card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN AXI CSR write + top-level `tb_gpio_ext_drive_*` pad inject; samples `tb_gpio_irq_any`; no force/deposit of IRQ success |
| F2 can't-fail checker | ✅ clean — VIP polarity / clear asserts raise; prior kept FAIL proved the pad-low path; this PASS reaches VIP success + protocol VIP record |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI write/read completed then VIP asserts ran |
| E2 empty phase | ✅ clean — real CSR program + mailbox read + VIP drive/sample (deassert/assert/deassert) |
| S1 silent fail | ✅ clean — mismatch raises `AssertionError`; no swallow-to-pass |
| O1 checker disabled | ✅ clean — no scoreboard/VIP disable on this path |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 · FIND-002 · FIND-003; else X-aware `is_resolvable` on first IRQ sample; seed logged; enrolled in `vplan_triplets.toml` (pulled by `all.toml`); ROM/efuse preload is post-PASS bring-up trailer not proof path |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_gpio_strap_sanity_test.py`
  sha256 `19584f87c26ca5a260b7633274d638e7f161b44969f8012e0afd69bc1a24f786`
- Sequence (discovered): `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_irq_active_test_seq.py`
  sha256 `0b1218a21bfedaa23d0aeb0d56f7a028ad62542d61b4cab48bd0a1c81091f4f0`
- VIP helper (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_gpio_vip_utils.py`
  sha256 `861c361465b3bd584686df11d612484ea813f3397551fffc8499da87e4a92f3b`
  (`check_gpio0_active_low_irq`)
- Log: `hw/sys/smc/dv/build/runs/20260806_094622__verilator__smc_gpio_strap_sanity_test/smc_gpio_strap_sanity_test/logs/smc_gpio_strap_sanity_test.log`
  sha256 `f6747d3f1f42ed84b1af991b9eebd5361d77a2801bf550634740b11ebbd4425d`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L318–L320:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: program GPIO0 for active-low level IRQ; read mailbox IRQEN as
  decode proxy; drive `tb_gpio_ext_drive_value` 1→0→1; observe `tb_gpio_irq_any`.
- AXI write (L280–L293): `0xc0003000 <- 0x150020` OKAY (GPIO0 DATA_CTRL).
- AXI read (L295–L306): `0xc0018038 -> 0x0` OKAY, scoreboard `exp=None`.
- VIP success (L308): `GPIO0 active-low IRQ VIP toggled external pad`; protocol VIP
  L309–L310 `csr_accesses=2 … passed=True`.
- Addressing: `GPIO0_DATA_CTRL` / `MAILBOX_IRQEN` via `smc_addr_map` → PeakRDL
  `smc_addr.h` (prior Blocking address finding closed).
- Field encodes: still local shifts (FIND-001); value matches `gpio_intf.h` today.
- Settle: VIP helper fixed 24 cycles then sample (FIND-003).
- Enrollment: `hw/sys/smc/dv/testlists/vplan_triplets.toml` (included by `all.toml`).
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load;
  not used as golden on this proof path.
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log (DeprecationWarnings only).
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX); sim PASS would satisfy
  policy §5 entry facts if a card existed.
- Provenance: legacy (`test_author.run_id: unknown`)

</details>

<details>
<summary>Stimulus / pass cites (kept log <code>f6747d3f…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–278 | clocks/reset; agents ready | `smc_base_test` |
| AXI write "GPIO0_INPUT_ACTIVE_LOW_IRQ" | 280–293 | `0xc0003000 <- 0x150020` OKAY | seq `:23-24` |
| AXI read "MAILBOX_IRQEN_AS_IRQ_PROXY" | 295–306 | `0xc0018038 -> 0x0` OKAY, `exp=None` | seq `:25` |
| VIP toggle | 308 | pad drive success log | vip `:10-29` |
| protocol VIP | 309–310 | `passed=True`, `csr_accesses=2` | test `:23-28` |
| cocotb result | 314–320 | `PASS` / `PASS=1 FAIL=0` | — |

</details>

## Not concluded

- Whether a GPIO0 active-low external-IRQ VIP under the name “strap sanity” proves the
  SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
