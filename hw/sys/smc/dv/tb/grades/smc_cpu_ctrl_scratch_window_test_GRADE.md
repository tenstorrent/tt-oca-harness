---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_cpu_ctrl_scratch_window_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094558__verilator__smc_cpu_ctrl_scratch_window_test/smc_cpu_ctrl_scratch_window_test/logs/smc_cpu_ctrl_scratch_window_test.log
  sha256: a06f8bd2f97e5aad19a73660687caa60f9f4f52cb8436d8554e319a3ee6ffefa
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
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_ctrl_scratch_window_test_seq.py:10-14
  observed: >
    Proof-path CPU_CTRL scratch addresses in `SCRATCH_WRITES` are hand-copied
    numeric literals (`CPU_CTRL_SCRATCH_0=0xC003_9080`,
    `CPU_CTRL_SCRATCH_7=0xC003_90B8`, `CPU_CTRL_SCRATCH_15=0xC003_90F8`) with a
    comment documenting the old base move. Generated PeakRDL already exposes
    matching symbols: `smc_addr.h`
    `SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(idx)` via
    `smc_addr_map.smc_indexed_addr`, and `smc_reg.py`
    `SMC_CPU_CTRL_SCRATCH_{0,7,15}__REG_ADDR` (already imported by sibling
    `smc_cpu_vip_utils` / `smc_cpu_to_sep_axi_test_seq`). Literals currently
    match those macros (latent-rot class, not false-identity).
  closure_condition: >
    Import every `SCRATCH_WRITES` address from `smc_addr_map.smc_indexed_addr(
    "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", idx)` or the matching `smc_reg`
    `SMC_CPU_CTRL_SCRATCH_*__REG_ADDR` symbols, and stop maintaining a parallel
    numeric table as the addressing source of truth.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_cpu_ctrl_scratch_window_test (standalone Layer 1 re-audit)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase. Layer 1 findings
> are the entire scope of this report. `NOT-READY` records the **absence of a closure
> claim, not a defect**. Kept log is a sim **PASS** (seed 1, verilator 5.050): first /
> middle / last CPU scratch write/readback/restore completed OKAY with exact pattern
> compares — Layer 2 entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `10e3bf9a…`)

| Item | Prior (log `10e3bf9a…`, PASS) | This audit (log `a06f8bd2…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🟠 1 Major FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | 🟠 1 Major FIND-001 (same tag / same scope) |
| FIND-001 | open — hand-copied `0xC003_9080` / `0xC003_90B8` / `0xC003_90F8` in `SCRATCH_WRITES` | **still open / unchanged** — seq sha256 still `a38fa391…`; literals still match generated map (latent rot) |
| Kept log | `10e3bf9ad028acebed33f07e332e5a42eb5eb02bb237c6a0b9bdc40e5193139d` PASS seed=1 | `a06f8bd2f97e5aad19a73660687caa60f9f4f52cb8436d8554e319a3ee6ffefa` PASS seed=1; SYS AXI checks #1–#15 |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`; nothing to drop) | none |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` — hand-copied CPU_CTRL scratch addresses |

<details>
<summary>1. 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` at seq `SCRATCH_WRITES`</summary>

Hand-copied `0xC003_9080` / `0xC003_90B8` / `0xC003_90F8` on the SEP_IN SYS AXI proof
path. Generated map exists (`SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR(idx)` via
`smc_addr_map.smc_indexed_addr`, and `SMC_CPU_CTRL_SCRATCH_{0,7,15}__REG_ADDR` in
`smc_reg.py`). Values currently match → Major (latent rot), not Blocking false-identity.

**Close when:** every `SCRATCH_WRITES` address is imported from generated map symbols;
parallel numeric constants are not the addressing source of truth.

</details>

**Then:** owner remediates FIND-001 and re-invokes `/dv_test_audit` after a kept PASS log.
Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem`; scoreboard compares DUT `rdata` to TB-programmed pattern; no force/deposit on CSR path |
| F2 can't-fail checker | ✅ clean — scoreboard `got == exp` on write/readback and restore reads is reachable; driver timeout and `assert accesses == 15` can fail |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; AXI path must complete or raise |
| E2 empty phase | ✅ clean — real save/write/readback/restore sequence for SCRATCH_0/7/15 (15 accesses logged) |
| S1 silent fail | ✅ clean — mismatch/timeout/`resp_ok` raise; sequence access-count assert |
| O1 checker disabled | ✅ clean — scoreboard SYS AXI path active (log checks #1–#15) |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]`; timeouts fail; seed logged; enrolled in `batch_d.toml` / `all.toml`; exact pattern expecteds on readbacks; ROM/efuse preload is post-PASS bring-up trailer not CSR golden |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_cpu_ctrl_scratch_window_test.py`
  sha256 `a9fc91a255155aeaec32d982f45e4a984601c94e4d434b8c99fdf2b9dee2bdc2`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_cpu_ctrl_scratch_window_test_seq.py`
  sha256 `a38fa391644160a479102d292d0bfb2a0a8467145b172cf521ff4f274f70522e`
- Helpers on proof path: `SmcCsrSeq.csr_read` / `csr_write_readback` / `csr_restore`;
  `smc_scoreboard._check_sys_axi`; `check_cpu_bfm_observability` (powergood/reset sample)
- Log: `hw/sys/smc/dv/build/runs/20260806_094558__verilator__smc_cpu_ctrl_scratch_window_test/smc_cpu_ctrl_scratch_window_test/logs/smc_cpu_ctrl_scratch_window_test.log`
  sha256 `a06f8bd2f97e5aad19a73660687caa60f9f4f52cb8436d8554e319a3ee6ffefa`
  (verified via `manifest.py hash-file`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`; cocotb summary L409–L411:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: for each of SCRATCH_0/7/15 — save-read → write pattern → readback with
  `expected=pattern` → restore prior value with readback; final `assert accesses == 15`
- Exact value compares in log: check #3 `0xc0a00000`, #6 `0xc0a00007`, #9 `0xc0a00015`,
  restore readbacks #11/#13/#15 `exp=0x0` (saved reset zeros)
- Protocol VIP: `csr_accesses=15 timeouts=0 passed=True` (L400–L401)
- AXI monitor trailer: `9 R beats, 6 B resps; R-resp tally OKAY=9; 0 errors` (L403)
- CPU BFM observability: `powergood=1 rst_primary=1 rst_wdt=1` (L399)
- Enrollment: `hw/sys/smc/dv/testlists/batch_d.toml`, `all.toml`
- Bring-up trailer: efuse/ROM hex preload after cocotb PASS; not used as CSR golden
- No unexplained `ERROR`/`FATAL`/`Traceback` in the kept log
- Entry gate / Layer 2 not evaluated (MODE=NO-CHECKBOX)
- Provenance: legacy (`test_author.run_id: unknown`); auditor
  `run_id: cursor/grok/4.5-reaudit-20260806`

</details>

<details>
<summary>Stimulus / sample cites (kept log <code>a06f8bd2…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| SCRATCH_0 save/W/R | 282–313 | read `0x0` → write `0xc0a00000` → readback match | seq `:25-28` |
| SCRATCH_7 save/W/R | 317–334 | read `0x0` → write `0xc0a00007` → readback match | seq `:25-28` |
| SCRATCH_15 save/W/R | 338–355 | read `0x0` → write `0xc0a00015` → readback match | seq `:25-28` |
| restore 15/7/0 | 359–397 | write/read zeros; checks #11/#13/#15 `exp=0x0` | seq `:30-31` |
| depth gate + VIP | 399–405 | `accesses==15`; protocol VIP CPU item `passed=True` | seq `:33`; test `:25-31` |

</details>

## Not concluded

- Whether this test proves the SPEC-required properties for CPU_CTRL scratch depth (`O2`) —
  Skill 3 / an approved card would decide intent match; this audit has no standing.
- Whether the test covers *all* required scratch-window scenarios — completeness has no
  meaning without a feature_list / approved plan allocation.
- Any closure / `EVIDENCE-CLOSED` claim — `STANDALONE-REQUEST` Layer 1 cannot assert one.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none carried forward (no prior signed waivers) | — |
