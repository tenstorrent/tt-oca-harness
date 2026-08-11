---
schema: dv-quality/v1
artifact: testcase-grade
testcase: smc_efuse_map_read_test
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
- path: hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_efuse_map_read_test/smc_efuse_map_read_test/logs/smc_efuse_map_read_test.log
  sha256: 58a469aa7fff9ff4bf454c2f42ce3b0d75659362b40ead74fc0437b5ffdb58e5
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
  tag: '[EXACT-EXPECTATION]'
  severity: Major
  artifact_ref: hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_map_read_test_seq.py:20-22
  observed: >
    `EFUSE_MAP_BIRA` and `EFUSE_MAP_RESERVED_0` still pass `expected=None`, so
    `smc_scoreboard._check_sys_axi` only asserts AXI OKAY and never compares
    `rdata`. Kept log L302–L314 shows BIRA `0xc0007048` → `rdata=0xff13`
    (matches `assets/smc_efuse_default.hex` word at BIRA offset) and RESERVED_0
    `0xc0007afc` → `rdata=0xbadcab1e` (error-slave signature) with
    `exp=None ok=True`. LOCKS lo/hi do compare exact hex goldens; the two
    remaining probes are OKAY-only / activity alone, not an exact map-read
    contract.
  closure_condition: >
    Pass independently derived exact `expected` values for BIRA and RESERVED_0
    from the same hex (or SPEC/RDL) into `item.expected` / `csr_read(...,
    expected=...)`, or document and keep `expected=None` only where no
    independent golden exists; do not treat OKAY completion alone as value
    proof for those probes.
  waived_by: null
waivers: []
recommendation: NOT-READY
---

# Grade Report — smc_efuse_map_read_test (standalone Layer 1)

**VERDICT: 0/0 PROVEN — NOT READY** (mode NO-CHECKBOX, no_contract_reason STANDALONE-REQUEST)

| Mode | Entry gate | Checkers | Findings | Recommendation |
|---|---|---|---|---|
| `NO-CHECKBOX` | — NOT-EVALUATED | 0/0 PROVEN | 🟠 1 Major | ⛔ NOT-READY |

> No approved checkbox card or parent plan record governs this testcase
> (`STANDALONE-REQUEST`). Layer 1 findings are the entire scope of this report.
> `NOT-READY` records the **absence of a closure claim, not a defect**. Kept
> log is a sim **PASS** (seed 1, verilator 5.050): four frontdoor SMC_EFUSE_MAP
> reads completed (LOCKS value-checked; BIRA/RESERVED OKAY-only) — Layer 2
> entry is still not evaluated in this mode.

## DELTA (re-audit vs prior grade `0/0 NOT-READY` on log `ed02bc86…`)

| Item | Prior (log `ed02bc86…`, FAIL) | This audit (log `58a469aa…`, PASS) |
|---|---|---|
| Verdict | 0/0 PROVEN — NOT READY | 0/0 PROVEN — NOT READY |
| Findings | 🔴 1 Blocking · 🟠 1 Major | 🟠 1 Major |
| Prior FIND-001 `[ADDRESS-FROM-AUTHORITATIVE-MAP]` | open Blocking — hand `0xC000_Bxxx` literals timed out | **closed** — `EFUSE_MAP_READS` uses `smc_addr` / `smc_indexed_addr`; kept log hits PeakRDL map `0xC0007000` / `7048` / `7afc` with AXI OKAY |
| Prior FIND-002 `[EXACT-EXPECTATION]` | open Major — BIRA/RESERVED `expected=None` | **still open** as FIND-001 Major — same two probes still OKAY-only |
| Kept log | `ed02bc862a8734e66c584c371e47aed9bbfaa24429d812f996f10888eed33a0e` (FAIL) | `58a469aa7fff9ff4bf454c2f42ce3b0d75659362b40ead74fc0437b5ffdb58e5` (PASS) |
| Repo rev | `2ecc7b227e3926b253c65b5aac21239eec24ba5f` | `c10b6d63e0b3377f8e2fa38c138e2ea72cae92c7` |
| Waivers carried | none signed (`waivers: []`) | none (nothing to drop; no signed entries) |

## Your to-do — 1 item (🟠 1 Major)

| # | Sev | Item |
|---|---|---|
| 1 | 🟠 Major | FIND-001 `[EXACT-EXPECTATION]` — BIRA/RESERVED `expected=None` |

<details>
<summary>1. 🟠 Major — FIND-001 <code>[EXACT-EXPECTATION]</code> — BIRA/RESERVED are OKAY-only</summary>

- **Where:** `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_map_read_test_seq.py:20-22`
- **Observed:** BIRA and RESERVED_0 still call `csr_read` with `expected=None`, so the
  scoreboard never compares `rdata`. Kept log: BIRA `0xff13` (hex-aligned) and
  RESERVED_0 `0xbadcab1e` both pass on OKAY alone.
- **Closure:** wire independently derived expecteds from
  `assets/smc_efuse_default.hex` (or SPEC) into `expected=` for those probes so wrong
  data fails; document any probe that must remain response-class-only.

</details>

**Then:** owner remediates FIND-001 (exact BIRA/RESERVED expectations), re-keeps a
PASS log at seed 1, and re-invokes `/dv_test_audit smc_efuse_map_read_test`.
Do not invent a card here (`STANDALONE-REQUEST`).

## All checkers

| Checker | Grade | Proof class | Covers | Findings |
|---|---|---|---|---|
| — | — | — | — | no card checkers (MODE=NO-CHECKBOX) |

### Layer 1 structural rule set

| Rule | Result |
|---|---|
| F1 fabricated verdict / backdoor write | ✅ clean — frontdoor SEP_IN SYS AXI via `SmcSysAxiItem` / `SmcCsrSeq`; no force/deposit on CSR proof path; efuse/ROM hex is time-0 bring-up preload (policy §6 class), not a TB-written success flag |
| F2 can't-fail checker | ✅ clean — scoreboard `resp_ok` and `got == exp` (when `expected` set) are reachable FAIL-ON paths; LOCKS compares exercised this run; prior FAIL proved timeout sensitivity |
| E1 skip-to-pass | ✅ clean — no missing-handle skip-to-pass; `wait_fuse_sense_done` raises on miss; timeout is not demoted to pass |
| E2 empty phase | ✅ clean — sequence issues four real map CSR reads; scoreboard SYS AXI checks #1–#4 present |
| S1 silent fail | ✅ clean — AXI timeout / non-OKAY / value mismatch raise `AssertionError` in driver/scoreboard; no swallow-to-pass |
| O1 checker disabled | ✅ clean — SYS AXI scoreboard path active (checks #1–#4); protocol VIP `passed` is a non-asserted completion marker only |
| Phase-S obligations — L1 | 🟠 Major — FIND-001 `[EXACT-EXPECTATION]`; else addresses from `smc_addr_map` / PeakRDL `smc_addr.h`, force-free, seed logged, enrolled in `p1_coverage_gap.toml`, warm-domain wait present, no unconditional CHK token |
| Phase-S obligations — L2 (needs the card) | — not evaluated |

## Evidence appendix

<details>
<summary>Kept log + code proof-path notes</summary>

- Implementation: `hw/sys/smc/dv/cocotb/tests/smc_efuse_map_read_test.py`
- Sequence: `hw/sys/smc/dv/cocotb/seq_lib/smc_efuse_map_read_test_seq.py`
- Helpers: `smc_addr_map.smc_addr` / `smc_indexed_addr`, `smc_csr_seq_utils.SmcCsrSeq.csr_read`,
  `smc_base_test_seq.wait_fuse_sense_done`, `smc_sys_axi_agent` timed READ,
  `smc_scoreboard._check_sys_axi`
- Authoritative map: `hw/sys/smc/regs/gen/c/smc_addr.h` —
  `SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR=0xC0007000`,
  `…_BIRA_BASE_ADDR=0xC0007048`,
  `…_RESERVED_BASE_ADDR(0)=0xC0007AFC`
- Log: `hw/sys/smc/dv/build/runs/20260806_094637__verilator__smc_efuse_map_read_test/smc_efuse_map_read_test/logs/smc_efuse_map_read_test.log`
  sha256 `58a469aa7fff9ff4bf454c2f42ce3b0d75659362b40ead74fc0437b5ffdb58e5`
  (verified via `sha256sum`; matches invoker hint)
- Seed: 1 · simulator: verilator 5.050 2026-07-01 · model fingerprint `2c815fa08277`
- `result.json`: `status: PASS`, `exit_code: 0`, cocotb summary L325–L327:
  `TESTS=1 PASS=1 FAIL=0 SKIP=0`
- Stimulus: `wait_fuse_sense_done` then four map reads; LOCKS expecteds
  `0xA5A5_5A5A` / `0xDEAD_BEEF` match `assets/smc_efuse_default.hex` words 0/1
- Address / value cites (kept log):
  - LOCKS_LO `0xc0007000` → `0xa5a55a5a` exp match (L280–L293)
  - LOCKS_HI `0xc0007004` → `0xdeadbeef` exp match (L295–L300)
  - BIRA `0xc0007048` → `0xff13` exp=None (L302–L307)
  - RESERVED_0 `0xc0007afc` → `0xbadcab1e` exp=None (L309–L314)
- Monitor: SEP_IN `OKAY=4`; protocol VIP `csr_accesses=4 timeouts=0`
- Enrollment: `hw/sys/smc/dv/testlists/p1_coverage_gap.toml`
- Bring-up trailer: efuse hex + ROM `$readmemh` (time-0 image); LOCKS goldens from that hex
- Provenance: legacy (`test_author.run_id: unknown`)
- Entry gate / Layer 2 not evaluated (`MODE=NO-CHECKBOX`; `entry_status: NOT-EVALUATED`)

</details>

<details>
<summary>Stimulus cites (kept log <code>58a469aa…</code>)</summary>

| Step | Line (approx) | What the log shows | Impl |
|---|---|---|---|
| bring-up | 266–278 | powergood, cold release, AXI masters ready | `smc_base_test` |
| LOCKS_LO | 280–293 | Read `0xc0007000` → `0xa5a55a5a` exp match | seq + scoreboard |
| LOCKS_HI | 295–300 | Read `0xc0007004` → `0xdeadbeef` exp match | seq + scoreboard |
| BIRA | 302–307 | Read `0xc0007048` → `0xff13` exp=None | seq `expected=None` |
| RESERVED_0 | 309–314 | Read `0xc0007afc` → `0xbadcab1e` exp=None | seq `expected=None` |
| VIP / result | 316–327 | `csr_accesses=4` · `PASS` / `PASS=1 FAIL=0` | test + cocotb |
| trailer | 329–336 | fuse/ROM load + `Fuse sense done` (buffered stdout) | TB models |

</details>

## Not concluded

- Whether a value-checked map-read proves the SPEC properties a future card would require (O2) — Skill 3.
- Completeness against a feature_list — no inventory applies in STANDALONE-REQUEST.
- Any closure or PROVEN checker claim — MODE=NO-CHECKBOX forbids inventing checkers.

## Accepted waivers

| Finding | Rule | Where | Why | Approved by |
|---|---|---|---|---|
| — | — | — | none | — |
