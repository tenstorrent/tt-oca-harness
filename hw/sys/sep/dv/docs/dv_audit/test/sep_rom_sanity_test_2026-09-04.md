# DV Audit — `sep_rom_sanity_test` (test height)

**NO-EVIDENCE** — no MUST-FIX and no GOOD-TO-HAVE in the source; the run cannot be bound to a
source revision, so the policy 1.7 freshness judgment is not evaluable (shared disposition D6).

**1 test · 0 blocked · 0 weak · 0 accepted · 0 clean · 1 no-evidence**
Policy `references/dv_policy.md` @ SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210` · log present (VCS, 2026-09-04) · 2026-09-04

*This audit asks whether the green result lies. It does not assess whether the plan is complete —
a behaviour with no test is a plan matter, not a finding here.*

## Verdict basis

**Deciding lines (three, in series — all must hold for a PASS):**
- `cocotb/tests/cpu/sep_rom_sanity_test.py:78` — `assert seen == 7` on the count of `[PASS] IFU`
  lines in the DUT-produced console.
- `fw/tests/rom_sanity_test/rom_sanity_test.c:59` — `return got == want ? 0 : 1`, the per-function
  compare inside `check()`; `main()` returns the error count, which `start.S` turns into the
  PASS/FAIL magic on the 0x8000_0000 mailbox.
- `cocotb/env/sep_boot_scoreboard.py:61-94` `check_phase` — banner, >=16 distinct fetch PCs,
  `fw_done`, `fw_pass` (shared disposition **D3**).

**Claim (rung 1, VPLAN entry `docs/SEP_VPLAN.adoc:146-149`):**
> "Proves the CPU fetch unit executes real code out of the boot ROM across the main RISC-V
> instruction formats."

**Steps vs claim.** The firmware, resident in ICCM, calls seven boot-ROM addresses through
function pointers (indirect JALR), so each body is fetched by the IFU from `0x1004_0000` and its
return value carries the result of the fetched instructions. The seven cover I-type, multi-
instruction sequential fetch, argument passthrough, U-type (`lui`+`addi`), J-type (`jal`), a
NOP sled, and R-type. That is the claim's property, exercised by the mechanism the claim names.
I decoded `cocotb/tests/rom_sanity_rom.hex` against the C's offset table: the words at 0x00,
0x08, 0x14, 0x1C, 0x28, 0x38, 0x50 are the encodings the comment documents (e.g. 0x1C =
`deadc537` `lui a0,0xdeadc` then `eef50513` `addi a0,a0,-0x111` -> 0xDEADBEEF), and every
golden follows from RISC-V ISA semantics, not from the design.

## The seven MUST-FIX classes

| Class | Result |
|---|---|
| 1.1 fabricated verdict | **excluded** — the `[PASS] `/`[FAIL] ` token is emitted from the ternary on `rom_sanity_test.c:52`, i.e. only after and according to the compare; `got` is the register value returned by ROM-fetched code, delivered to the host over the mailbox. The log's line 138 shows real observed values (`got=0xdeadbeef`, `got=0x0000004d`, …), not constants echoed from the expectation. |
| 1.2 a check that cannot fail | **excluded** — a stuck, mis-fetched, or zero-returning IFU yields a different `got`, `errors != 0`, the FAIL magic, and `[FAIL] IFU` lines that `seen == 7` does not count. Three independent ways to fail. |
| 1.3 a mismatch that does not fail | **excluded** — no `try`/`except` on the proof path (D1); the bounded boot poll is not a timeout-as-pass (D4); a firmware mismatch propagates via error count -> FAIL magic -> scoreboard assertion, and independently via the host-side count assertion. |
| 1.4 nothing observed | **excluded** — the host asserts an exact minimum-and-maximum activity count (7 of 7, `:78`) plus the `PASS: 7/7` summary (`:81`); the scoreboard requires >=16 distinct retired PCs and `fw_done` (D3/D4). The log records 4959 retired instructions across 210 distinct PCs and the full seven-line console. |
| 1.5 the wrong thing proven | **excluded** — see *Steps vs claim*. `ROM_BASE` comes from the generated symbol `OCH_SEP_TOP_SEP_BOOT_ROM_BASE_ADDR` (`rom_sanity_test.c:36`); the ICCM reset vector from `sym("SEP_ICCM_MEM_BASE_ADDR")`. No literal register address is on the proof path. |
| 1.6 the testbench supplied the answer | **excluded** — the ROM image is `$readmemh` into the DUT's own RTL macro `u_sep_boot_rom.mem` at t=0 (`tb/tb_top.sv:1006-1017`), which is the policy 1.6 carve-out for a time-0 program-image load: it supplies the *program*, and the DUT's fetch unit still has to fetch and execute it. Nothing forces or deposits a return value, `fw_done`, `fw_pass`, or any console byte. `+skip_fuse_sense` is on the run (see O1) but fuse sense does not produce instruction fetch, and no verdict here reads fuse-derived state. |
| 1.7 evidence not from this test at this commit | **partly not evaluated** — enrollment and execution are sound: the test is enrolled in `testlists/memory.toml:47-54` and listed in `testlists/all.toml` (lines 85 and 159), and `result.json` records a real 114 s VCS run with positive `results.xml` evidence (`1 testcase(s) passed`) under build fingerprint `c07fb8d96992`. What is missing is a source revision on the artifact, so "these sources at that build" cannot be established. Per shared disposition **D6** this is recorded, not filed as a MUST-FIX — and it is what holds the verdict at `NO-EVIDENCE`. |

## Findings

No MUST-FIX. No GOOD-TO-HAVE.

### O1 — the run skips real fuse sense, so nothing fuse- or lifecycle-gated about ROM fetch is under test

**OBSERVATION** · `testlists/memory.toml:54`, effect at `cocotb/tests/sep_base_test.py:196` and
log line 37 (`+skip_fuse_sense provided, but … +sep_shadow_reg_preload … was NOT found`).
The plusarg makes the RTL assert `sep_fuse_sense_done_o` about one cycle after reset (log line 89:
"SEP fuse sense done at cycle 1") instead of running the 256-word sense. That is a bring-up
precondition, not the checked mechanism, and the VPLAN claim says nothing about access control —
so this is not policy 1.6. Recorded only so a reader does not take this test as evidence that
boot-ROM fetch is permitted under real sensed fuse or lifecycle state.

### O2 — the seven ROM entry offsets are literals that must stay in step with the committed ROM image

**OBSERVATION** · `fw/tests/rom_sanity_test/rom_sanity_test.c:37-43` against
`cocotb/tests/rom_sanity_rom.hex`. Not policy 2.3: these are offsets into a hand-assembled test
image, not register-map addresses, and drift is self-detecting — a call landing on the wrong word
returns the wrong value and fails. Noted because the two files have to be edited together.

### O3 — the run artifacts record a build fingerprint but no source revision

**OBSERVATION** · `build/runs/20260904_065716__vcs__all/…/attempt_0/result.json` (fingerprint
`c07fb8d96992`, seed 1055739219, no git revision). Shared disposition **D6**; the fix is upstream,
in what the runner stamps onto a run, not in this test.

*Not reported, per shared disposition **D7**: `log_facts.py`'s "claims PASS but an assertion
failure is logged" resolves to log line 24, cocotb's "pytest not found" notice.*

## What I did not check

- **Policy 1.7 freshness proper.** No artifact names a source revision, so I could not confirm
  the audited sources are the ones that produced this log. Not settled by timestamps, per method.
- **Firmware image identity beyond plausibility.** `fw/build/tests/rom_sanity_test/*.itcm.hex`
  and the C source are both dated 2026-09-03 and the run is 2026-09-04, and the log's console text
  matches the current C's strings exactly — which is strong, but it is not a build stamp binding
  the hex to that source.
- **`log_facts.py`'s "no simulation time found" lead** beyond confirming the log carries real
  timestamps up to 228834.00 ns and a 114 s wall duration in `result.json`. I read it as a tool
  pattern miss, not a fact about the run.
- **Whether the boot-ROM read path has an access-control mechanism at all** (O1). Answering it
  needs the design, which is deliberately not an audit input.
- **The shared files under dispositions D1-D7**, which I cited rather than re-audited:
  `cocotb/env/sep_boot_scoreboard.py`, `cocotb/tests/sep_base_test.py` beyond the functions on
  this proof path (`boot_firmware`, `poll_boot`, `_wait_fuse_sense`, `rd`),
  `cocotb/seq_lib/sep_axi_reg_driver.py`.
- **Coverage of anything.** Out of scope by policy §6.

<details>
<summary>Inputs</summary>

Test `cocotb/tests/cpu/sep_rom_sanity_test.py` (86 lines) · firmware
`fw/tests/rom_sanity_test/rom_sanity_test.c` (83 lines) · ROM image
`cocotb/tests/rom_sanity_rom.hex` (11 words) · image load `tb/tb_top.sv:1006-1017` ·
scoreboard `cocotb/env/sep_boot_scoreboard.py` (D3) · base test `cocotb/tests/sep_base_test.py`
(D1, D4, D5) · claim `docs/SEP_VPLAN.adoc:146-149` (rung 1: VPLAN entry) · enrollment
`testlists/memory.toml:47-54`, `testlists/all.toml:85,159` · log + `result.json`
`build/runs/20260904_065716__vcs__all/sep_rom_sanity_test/seed_1055739219/attempt_0/` ·
approval records searched: `docs/` — none found, and none needed.

Enumerated 1 / audited 1 / skipped 0.
</details>

<details>
<summary>Policy gaps</summary>

None. Every judgment above was reachable with a rule in the policy as pinned.
</details>
