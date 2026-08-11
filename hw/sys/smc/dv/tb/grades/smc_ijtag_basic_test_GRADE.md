---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_ijtag_basic_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094552__verilator__smc_ijtag_basic_test/smc_ijtag_basic_test/logs/smc_ijtag_basic_test.log
  sha256: bc0ee5a220c22cb31026f741cba9a34c793a0b2f25ef21137465ef687bc627d2
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_ijtag_basic_test_seq.py:18-20
  observed: >-
    Partial remediations still leave hand-derived offsets / non-register symbols
    on the proof path. `CHIP_CONFIG_VERSION_LO` is sourced from block base
    `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")` rather than the
    register symbol `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR`
    (same numeric value today). `SCRATCH_COLD_1` is
    `smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x4` with a
    hand-copied stride instead of
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)`.
    Sibling `smc_register_sanity_test_seq` already uses the indexed macro.
    Addresses currently match generated `smc_addr.h` (latent-rot class, not
    false-identity).
  closure_condition: >-
    Source both proof-path addresses from the register-level generated symbols:
    `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")` and
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)`.
    Drop block-base + hand-offset arithmetic as the addressing source of truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_ijtag_basic_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST` / active-regression L1 wave). Layer 1 findings are the entire
> scope of this report. `NOT-READY` records the **absence of a closure claim, not a
> defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050):
> `TESTS=1 PASS=1 FAIL=0 SKIP=0` with 5 SYS AXI scoreboard checks and CPU JTAG
> IDCODE/DTMCS MATCH; Layer 2 entry is still not evaluated under `STANDALONE-REQUEST`.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `bd819641…`)

| Item | Prior (log `bd819641…`, PASS) | This audit (log `bc0ee5a2…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major | 🟠 1 Major |
| FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open — numeric literals `0xC000_2900` / `0xC000_2804` | still open — `smc_addr` imported, but VERSION_LO uses block-base symbol and SCRATCH_COLD_1 keeps hand `+ 0x4` instead of `smc_indexed_addr(..., 1)` |
| Kept log | `bd819641ff412ed3569c3dba23d421a687f1685c3b63f0b1882d1d3dcc2125a3` | `bc0ee5a220c22cb31026f741cba9a34c793a0b2f25ef21137465ef687bc627d2` |
| repository_revision | `2ecc7b22…` | `c10b6d63…` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 items (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — residual block-base / hand `+0x4` on CSR addresses |

<details>
<summary>1. 🟠 Major FIND-001 — import register-level map symbols for VERSION_LO and SCRATCH_COLD_1</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_ijtag_basic_test_seq.py:18-20`
- **Observed:** Literals are gone, but `CHIP_CONFIG_VERSION_LO` still resolves via
  `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR`, and `SCRATCH_COLD_1` is
  `SCRATCH_COLD_BASE_ADDR + 0x4` rather than
  `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)`.
  Numerics match today (`0xc0002900` / `0xc0002804`) — Major latent-rot, not Blocking
  false-identity.
- **Closure:** Use
  `smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")` and
  `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)`.

</details>

**Then:** owner may remediate FIND-001 and re-keep a PASS log, then re-invoke
`/dv_test_audit smc_ijtag_basic_test`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem` + pin-level CPU JTAG TAP drive; scoreboard compares DUT `rdata` to supplied `expected`; no force/deposit on proof path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` raises on mismatch; JTAG `read_idcode(check=True)` raises on IDCODE mismatch; DTMCS version assert and final `accesses == 5` are reachable fail paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip branch; CSR precheck and JTAG VIP always execute (seq docstring notes real iJTAG VIP is not yet integrated — that is scope/O2, not a skip-to-pass) |
| E2 empty phase | ✅ clean — 5 real AXI accesses (VERSION_LO read + scratch write/read/restore/read) then TAP reset + IDCODE + DTMCS |
| S1 silent fail | ✅ clean — AXI/JTAG mismatches raise; protocol VIP `passed` is a non-asserted completion marker only |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard value checks #1–#5 and protocol VIP record active in kept log |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`; else force-free, timeout fails on driver path, seed logged, enrolled in `batch_c.toml` / `all.toml` / `vplan_triplets.toml`, TDO resolvable + exact IDCODE/DTMCS version, no unconditional CHK token, ROM/efuse preload is post-PASS trailer not proof golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_ijtag_basic_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_ijtag_basic_test_seq.py`
- JTAG helper (proof path): `hw/sys/smc/dv/cocotb/seq_lib/smc_jtag_vip_utils.py` → `smc_jtag_protocol_vip.py`
- Scoreboard (proof path): `hw/sys/smc/dv/cocotb/env/smc_scoreboard.py`
- Log: `hw/sys/smc/dv/build/runs/20260806_094552__verilator__smc_ijtag_basic_test/smc_ijtag_basic_test/logs/smc_ijtag_basic_test.log`
  sha256 `bc0ee5a220c22cb31026f741cba9a34c793a0b2f25ef21137465ef687bc627d2` (matches claimed; verified via `sha256sum`)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L345:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: VERSION_LO reset read (`exp=0x100a0`) → SCRATCH_COLD_1 write `0x1a7a0001` / readback / restore-to-0 / readback → CPU JTAG TAP reset + IDCODE `0x10CA0555` MATCH + DTMCS version `0x1`
- Scoreboard (L293–L327): SYS AXI checks #1–#5 with value compares on reads; protocol VIP (L334–L335) records `csr_accesses=5` after JTAG MATCH
- Final seq gate: `assert self.accesses == 5` (`smc_ijtag_basic_test_seq.py:57`)
- JTAG FAIL-ON: `read_idcode(check=True)` raises `SmcJtagTapError` on mismatch; TDO `is_resolvable` assert; DTMCS `version == 0x1`
- Addressing: `smc_ijtag_basic_test_seq.py:18-20` via `smc_addr` + hand `+ 0x4`; generated truth in `hw/sys/smc/regs/gen/c/smc_addr.h` (numerics MATCH; register-level symbols not fully used — FIND-001)
- Enrollment: `hw/sys/smc/dv/testlists/batch_c.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not used as CSR/JTAG golden on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>bc0ee5a2…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| VERSION_LO RD | 292–293 | `rdata=0x100a0 exp=0x100a0 ok=True` | seq `:51-52` |
| SCRATCH wr/rd | 305–313 | write `0x1a7a0001`, readback MATCH | seq `:53-54` |
| SCRATCH restore | 319–327 | write `0x0`, readback `exp=0x0` | seq `:55-56` |
| CPU JTAG IDCODE | 330–331 | `IDCODE=0x10CA0555` MATCH | jtag utils `:54` |
| CPU JTAG DTMCS | 332–333 | `DTMCS=0x00005071` version 0x1 MATCH | jtag utils `:60-65` |
| protocol VIP | 334–335 | `jtag:smc_ijtag_basic_test` csr_accesses=5 | test `:24-30` |
| cocotb result | 339–345 | `PASS` / `TESTS=1 PASS=1 FAIL=0 SKIP=0` | — |

</details>

## Not concluded

- Whether CSR precheck plus CPU TAP IDCODE/DTMCS proves the SPEC iJTAG properties a future card would require (O2) — Skill 3; seq itself documents that a real JTAG/iJTAG transaction remains blocked on VIP integration.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
