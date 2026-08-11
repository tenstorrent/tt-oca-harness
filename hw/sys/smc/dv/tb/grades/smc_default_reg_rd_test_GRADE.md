---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_default_reg_rd_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_default_reg_rd_test/smc_default_reg_rd_test/logs/smc_default_reg_rd_test.log
  sha256: 277064a2146cf2c88cf32b44d5a9b966ee8dd26b908a8b19bca651f4fa09d816
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_default_reg_rd_test_seq.py:17-23
  observed: >
    Absolute region bases now come from `smc_addr(...)` (prior absolute
    `0xC000_28xx` / `0xC000_290x` literals are gone), but three proof-path
    addresses still add hand-copied field strides: `SCRATCH_COLD_1` uses
    `SCRATCH_COLD_BASE + 0x4`, `CHIP_CONFIG_VERSION_HI` uses
    `CHIP_CONFIG_BASE + 0x4`, and `CHIP_CONFIG_CHIP_ID` uses
    `CHIP_CONFIG_BASE + 0x8`. Generated PeakRDL already exports
    `SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR(idx)`,
    `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_{LO,HI}_BASE_ADDR`, and
    `SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_CHIP_ID_BASE_ADDR`. `catalog_entry`
    only cross-checks the same hand arithmetic in
    `smc_csr_field_catalog.CSR_FIELD_CATALOG`. Values currently match the
    generated macros (latent-rot class, not false-identity).
  closure_condition: >
    Address every `READABLE_REGS` entry via generated symbols only —
    `smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", i)`
    (and warm scratch idx 0), plus `smc_addr` for
    `CHIP_CONFIG_{VERSION_LO,VERSION_HI,CHIP_ID}_BASE_ADDR` — and stop using
    hand `+ 0x4` / `+ 0x8` (or a parallel hand catalog) as the addressing
    source of truth on this proof path.
  waived_by: null
- id: FIND-002
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_default_reg_rd_test_seq.py:21-23
  observed: >
    Three of six SYS AXI reads still pass `expected=None`
    (`CHIP_CONFIG_VERSION_LO/HI`, `CHIP_CONFIG_CHIP_ID`), so
    `smc_scoreboard._check_sys_axi` only asserts AXI OKAY and never compares
    `rdata`. The same-tree catalog already declares exact RO static expecteds
    for `CHIP_CONFIG_VERSION_LO=0x0001_00A0` and `CHIP_CONFIG_VERSION_HI=0`,
    and the kept log shows VERSION_LO `rdata=0x100a0` (L314) — yet the
    sequence discards those catalog expecteds and never wires them into
    `item.expected`. OKAY-only / activity alone is not an exact
    register-default contract. Scratch reads do check `expected=0`.
  closure_condition: >
    For every `READABLE_REGS` entry whose catalog/`SmcCsrField.expected` is
    non-null (at least VERSION_LO/HI), pass that exact value as
    `item.expected` so the scoreboard `got == exp` path can fail on wrong
    reset/static data; keep `expected=None` only where no independent golden
    exists and document that limit.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_default_reg_rd_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 2 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): all six
> frontdoor SYS AXI reads completed OKAY, including warm-domain `SCRATCH_COLD_WARM_0`
> — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `06ecbeba…`)

| Item | Prior (log `06ecbeba…`, PASS) | This audit (log `277064a2…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 2 Major | 🟠 2 Major |
| Prior FIND-001 absolute CSR literals | open Major `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — full `0xC000_*` literals | **partially closed** — bases now via `smc_addr(...)`; **residual open** as FIND-001 Major — hand `+0x4/+0x8` strides remain vs indexed/per-reg symbols |
| Prior FIND-002 CHIP_CONFIG `expected=None` | open Major `[EXACT-EXPECTATION]` | **still open** as FIND-002 Major — VERSION_LO/HI/CHIP_ID still OKAY-only |
| Kept log | `06ecbeba14efc753bf330b7fad88516a1f8c1407057b4402978b1c20ebdd2baf` | `277064a2146cf2c88cf32b44d5a9b966ee8dd26b908a8b19bca651f4fa09d816` |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 2 items (🟠 2 Major)

| # | Kind | Id | Severity / grade | Where |
|---|---|---|---|---|
| 1 | finding | FIND-001 | 🟠 Major | `smc_default_reg_rd_test_seq.py:17-23` |
| 2 | finding | FIND-002 | 🟠 Major | `smc_default_reg_rd_test_seq.py:21-23` |

<details>
<summary>1. FIND-001 — 🟠 Major <code>[ADDRESS-FROM-AUTHORITATIVE-MAP]</code> — hand field strides</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_default_reg_rd_test_seq.py:17-23`
- **Observed:** Region bases use `smc_addr`, but `SCRATCH_COLD_1` / `VERSION_HI` / `CHIP_ID` still add hand `+0x4/+0x8`. Generated indexed/per-reg macros exist; catalog only mirrors the same arithmetic. Values match today → Major latent rot, not Blocking false-identity.
- **Closure:** every `READABLE_REGS` address from `smc_indexed_addr` / per-register `smc_addr` symbols; no hand strides or parallel numeric catalog as addressing truth.

</details>

<details>
<summary>2. FIND-002 — 🟠 Major <code>[EXACT-EXPECTATION]</code> — CHIP_CONFIG OKAY-only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_default_reg_rd_test_seq.py:21-23`
- **Observed:** `CHIP_CONFIG_VERSION_LO/HI` (and `CHIP_ID`) issue with `expected=None`, so the scoreboard never compares `rdata`. Catalog already has exact RO static expecteds for VERSION_LO/HI; kept log shows VERSION_LO `0x100a0` matching `0x0001_00A0` without that compare being enforced. Scratch reads check `expected=0` (good).
- **Closure:** wire non-null catalog/static expecteds into `item.expected` so `got == exp` can fail; OKAY-only only where no independent golden exists.

</details>

**Then:** owner remediates FIND-001/FIND-002 on the sequence (and matching catalog symbols if kept), re-keeps a PASS log, and re-invokes `/dv_test_audit`. Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to independently supplied `expected` when set; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` (scratch), non-OKAY `resp_ok`, driver timeout, and final `assert self.reads == len(READABLE_REGS)` are reachable FAIL-ON paths |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; `wait_fuse_sense_done` raises on miss |
| E2 empty phase | ✅ clean — six real SYS AXI reads executed (scoreboard checks #1–#6) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`, FIND-002 `[EXACT-EXPECTATION]`; timeouts fail; enrolled in `batch_b.toml` / `all.toml` / `vplan_triplets.toml`; no unconditional CHK token; warm-domain wait present |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Log: `hw/sys/smc/dv/build/runs/20260806_094550__verilator__smc_default_reg_rd_test/smc_default_reg_rd_test/logs/smc_default_reg_rd_test.log`
  sha256 `277064a2146cf2c88cf32b44d5a9b966ee8dd26b908a8b19bca651f4fa09d816`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L341:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Final assertion gate: seq `assert self.reads == len(READABLE_REGS)` (6) reached after
  six scoreboard SYS AXI checks; protocol VIP records `csr_accesses=6`
- Warm CSR note: `SCRATCH_COLD_WARM_0` @ `0xc0002880` completed OKAY with `rdata=0`
  (L307) — warm-domain hang class not present in this kept log
- Test: `hw/sys/smc/dv/cocotb/tests/smc_default_reg_rd_test.py`
  sha256 `bf268630eb23381b5298af8b68c8b3dcc8d599c0a6a28766cdbead69fad8bf46`
  starts `smc_default_reg_rd_test_seq` on `sys_axi_agent.sequencer`, then records protocol VIP
- Seq: `hw/sys/smc/dv/cocotb/seq_lib/smc_default_reg_rd_test_seq.py`
  sha256 `eeaa51dadbc4f733eab2a6549c0126d579c24b53831025e1bc8205aa1eca8d15`
  — `wait_fuse_sense_done` → catalog validate → 6× read; scratch expecteds `0`;
  CHIP_CONFIG expecteds `None`; bases via `smc_addr`, strides still hand `+0x4/+0x8`
- Addressing residual: seq L17–L23 / catalog twin at `smc_csr_field_catalog.py:26-41`;
  generated truth in `hw/sys/smc/regs/gen/c/smc_addr.h` (indexed scratch + per-reg CHIP_CONFIG)
- Driver FAIL-ON: `smc_sys_axi_agent.py` raises on unexpected AXI timeout
  (`[TIMEOUT-MUST-FAIL]` satisfied for this path)
- Scoreboard value check: `smc_scoreboard.py:188-194` asserts `rdata` vs `expected` only
  when `expected is not None` (FIND-002)
- Enrollment: `hw/sys/smc/dv/testlists/batch_b.toml`, `all.toml`, `vplan_triplets.toml`
- Bring-up trailer (post-PASS flush): efuse hex + ROM `$readmemh` — time-0 image load; not
  used as CSR golden substitution on this proof path
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)

</details>

## Not concluded

- Whether default RO/RW CSR reads prove the SPEC register properties (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
