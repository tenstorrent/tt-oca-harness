# DV Audit — `sep_boot_rom_lsu_read_test` (test height)

**CANNOT SIGN OFF ON THIS TEST ALONE** — the source is honest and the firmware's
value checks are real, but no artifact of this run records a source revision, so
policy 1.7 freshness cannot be judged. Verdict `NO-EVIDENCE`.

**1 test · 0 blocked · 0 accepted · 1 NO-EVIDENCE (no MUST-FIX found)**
Findings: 0 MUST-FIX · 1 GOOD-TO-HAVE · 3 OBSERVATION
Policy `/home/yenhenglai/.claude-ai/skills/dv_audit/references/dv_policy.md`
@ SHA-256 `37cf7610c45aa272d2b6275e229ebadc38294e03f00ff3199389fbbca4b90210` · 2026-09-04

*This audit asks whether the green result lies. It does not assess whether the
plan is complete — a behaviour with no test is a plan matter, not a finding here.*

## Claim (rung 1 — VPLAN entry)

> "LSU reads of the Boot ROM match the loaded image; stores to ROM are ignored."
> — `docs/SEP_VPLAN.adoc:428`, row `sep_boot_rom_lsu_read_test` (run mode `cpu`,
> VIP `ocah_axi_vip, CPU FW`)

## The line that decides pass/fail

The proof path crosses three languages and ends in the CPU's own load/store unit:

1. `fw/tests/rom_lsu_read_test/rom_lsu_read_test.c:123` — `return errors;`
   `errors` is incremented only inside a failing value comparison (lines 68, 87, 108).
2. `fw/startup/crt0.s:166-183` — `snez a0, a0` then `sw` of `TEST_MAGIC_PASS`
   (`0xCAFEBABE`) or `TEST_MAGIC_FAIL` (`0xDEADBEEF`) to the `0x8000_0000` mailbox.
   The default trap handler (`crt0.s:195+`) fails the test, so a trapped store
   cannot become a pass.
3. `cocotb/env/sep_boot_scoreboard.py:61-94` — `check_phase` asserts the error
   list is empty; `fw_pass` false, `fw_done` unset, missing trace monitor, fewer
   than 16 distinct fetch PCs, or a missing console banner are each an error
   (disposition **D3**). The test sets the banner to a real string
   (`cocotb/tests/cpu/sep_boot_rom_lsu_read_test.py:60`), so the banner leg ran.

Nothing on this path swallows a failure: `run_phase` awaits `run_scenario()`
bare (**D1**), and the boot poll is a bounded loop whose fall-through is an
error, not a pass (**D4**).

## Where the expected values come from

Traceable to the committed image, not to the design (policy 2.2 satisfied):

| Expected | Source outside the design |
|---|---|
| `0x89abcdef`/`0x01234567` … `0xa5a5a5a5` (`.c:59-63`) | `cocotb/tests/mem_rom_test_rom.hex:1-5`, words 0..4 (little-endian halves) |
| `0xbaadf00d`/`0x0badc0de` (`.c:87`) | same hex, `@00001fff` record — the top 64-bit word |

The image is loaded at t=0 by `tb/tb_top.sv:1012-1014`
(`$readmemh(img, SEP_IPI.u_sep_boot_rom.mem)`) from
`+sep_boot_rom_hex=mem_rom_test_rom.hex` (`testlists/memory.toml:71`). The run log
confirms the load actually happened: `[tb_backdoor_mem] boot ROM image loaded
(mem_rom_test_rom.hex)` (log line 67). A missing image would leave the default
fill and every compare would fail, so this backdoor cannot manufacture a pass —
and it is the "time-0 program-image load" the policy excludes from 1.6 by name.
`ROM_BASE`/`ROM_SIZE` come from generated symbols (`.c:36-38`), not literals.

## The seven MUST-FIX classes

| Class | Result |
|---|---|
| 1.1 fabricated verdict | **excluded** — `errors` is only ever incremented inside a failing compare; the `PASS:` console line (`.c:121`) is gated on `errors == 0` and is not itself the verdict, and each per-check PASS line sits in the else arm of its own compare |
| 1.2 a check that cannot fail | **excluded** — all four compares are DUT loads against image literals. The write-ignored leg deliberately compares against the literal `0x89abcdefu`, not against the earlier DUT read `orig` (`.c:104-108`), so a path stuck at a stable value fails |
| 1.3 a mismatch that does not fail | **excluded** — every mismatch does `errors++`; there is no `try`, no demotion, no bounded wait treated as proof. A trap fails via `crt0.s` |
| 1.4 nothing was observed | **excluded** — stimulus count is a compile-time array of 10 loads plus 2 boundary loads plus store/re-read; the log carries all three checker PASS lines and 3650 retired instructions / 147 distinct PCs (log line 138). The scoreboard's >=16-PC + `fw_done` + `fw_pass` requirement is the minimum-activity guard the fact row reported missing in the Python leaf |
| 1.5 the wrong thing was proven | **excluded** — the claim's two halves map one-to-one onto CHK-ROM-READ/CHK-ROM-BOUNDARY (reads match the loaded image) and CHK-ROM-WRITE-IGNORED (store returns normally, content unchanged). No numeric register literals; ROM offsets are byte offsets from a symbolic base |
| 1.6 the testbench supplied the answer | **excluded** — the only backdoors are the t=0 ROM image and the t=0 TCM image load, both explicitly carved out. `+skip_fuse_sense` is declared in the VPLAN run-mode column and the testlist, and no fuse-derived state gates the ROM data read or is the state the checked mechanism should have produced (see O2) |
| 1.7 evidence not from this test at this commit | **not evaluated** — enrollment is sound (`testlists/memory.toml:57-71`, group member `testlists/all.toml:113,170`) and the log's plusargs match the testlist exactly (log line 7). But no artifact records a source revision (**D6**): `result.json` carries only build fingerprint `c07fb8d96992` and a seed. Per the skill's stated method this is `NO-EVIDENCE`, not a finding |

## Findings

### F1 — The write-ignored leg has a read-side control but no write-side control

**GOOD-TO-HAVE** (policy 2.1) · `fw/tests/rom_lsu_read_test/rom_lsu_read_test.c:100-118`
**Claim leg:** "stores to ROM are ignored" (VPLAN `docs/SEP_VPLAN.adoc:428`).
**Why it is weaker than it reads:** the check is "content unchanged". A store
that never left the CPU, was dropped inside the LSU, or never reached the
`lsu_rom_axi` write channel at all produces the same green result. The positive
control that exists is read-side: CHK-ROM-READ proves the LSU→ROM path is alive
and pins that exact word against the image. Nothing observes a write beat
arriving at the ROM port, and no store on that port is ever observably honoured
(by design — the port is read-only), so no allow leg for the write direction is
possible in firmware alone.
**Escalation trigger (evaluated, does not fire):** the read leg on the same
address through the same port does show the stimulus reached the checked gate, and
the trace monitor reports 0 traps with the core reaching `_finish` (log line 141),
so the store returned normally. That keeps this out of 1.4.
**Fix:** assert on the AXI monitor for the `lsu_rom_axi` write channel — one
`AWVALID`/`WVALID` beat with `BRESP == OKAY` for the injected store — so the
"ignored" claim rests on an observed, acknowledged write rather than on absence.

### O1 — The golden is duplicated between the hex image and the C literals

**OBSERVATION** · `fw/.../rom_lsu_read_test.c:59-63,87,108` vs
`cocotb/tests/mem_rom_test_rom.hex`. Verified consistent today, word by word,
including the `@00001fff` boundary record. An edit to either file alone turns the
test red rather than green, so this rots loudly, not silently. Deriving the C
table from the hex at build time would remove the duplication.

### O2 — `+skip_fuse_sense` is a declared shortcut, in scope here

**OBSERVATION** · `testlists/memory.toml:71`; log line 37 records that no shadow
register preload accompanies it. It is named in the VPLAN run-mode column and in
the test docstring, and it supplies no state the ROM data-read or write-reject
mechanism is itself supposed to produce. Recorded so the reader can see it.

### O3 — No artifact of this run records a source revision

**OBSERVATION** (bucket-wide, disposition **D6**) · `result.json` metadata. This
is what holds the test at `NO-EVIDENCE`. The fix is upstream in the runner: have
each run stamp a git revision alongside the build fingerprint.

`orig` at `.c:100` is read and used only in the failure message. That is
deliberate and commented (`.c:104-107`); it is not a computed-but-uncompared
golden and is not filed as a finding.

## What I did not check

- **Whether the values in `mem_rom_test_rom.hex` are the *right* ones.** They are
  arbitrary patterns chosen for this test; judging correctness of a golden is
  design review, not this audit.
- **Whether `u_sep_boot_rom.mem` (the memory the t=0 `$readmemh` targets) is the
  same array the `lsu_rom_axi` port reads through.** The runtime PASS lines make
  it very likely, but I did not open the RTL/responder to confirm the hierarchy —
  and reading RTL to settle a golden is what policy 2.2 forbids.
- **Whether the store in CHK-ROM-WRITE-IGNORED reached the ROM AXI port.** That
  is F1 and it needs a monitor or a waveform, neither of which I may produce
  read-only.
- **The `results.xml` contents.** I took PASS from the cocotb summary lines and
  `result.json` `exit_code: 0`; I did not open the XML.
- **Policy 1.7 freshness**, per D6 — not evaluated, and not settled by timestamps.
- **Shared infrastructure** (`sep_boot_scoreboard.py`, `sep_base_test.py`,
  `sep_axi_reg_driver.py`) — cited from dispositions D1-D7, not re-audited.

<details>
<summary>Inputs</summary>

- Test: `cocotb/tests/cpu/sep_boot_rom_lsu_read_test.py` (72 lines, read whole)
- Firmware: `fw/tests/rom_lsu_read_test/rom_lsu_read_test.c` (124 lines, read whole);
  `fw/startup/crt0.s:150-200`
- Image: `cocotb/tests/mem_rom_test_rom.hex` (7 records); loader `tb/tb_top.sv:1007-1020`
- Claim: `docs/SEP_VPLAN.adoc:425-428` (rung 1); also `:532` lists this test under a PROVEN row
- Enrollment: `testlists/memory.toml:57-71`; `testlists/all.toml:113,170`
- Helpers on the proof path (dispositions, not re-audited):
  `cocotb/env/sep_boot_scoreboard.py:61-94` (D3), `cocotb/tests/sep_base_test.py:477-590` (D1/D4/D5)
- Log: `build/runs/20260904_065716__vcs__all/sep_boot_rom_lsu_read_test/seed_1209326642/attempt_0/logs/sep_boot_rom_lsu_read_test.log`
  via `log_facts.py` plus one targeted grep. `result.json` at the sibling path:
  `exit_code 0`, `duration 68.4 s`, `failure_buckets []`.
- Approval records searched for: none found beside the test, in the VPLAN row, or
  in the testlist entry. None needed — no MUST-FIX was filed.
- The `log_facts.py` "claims PASS but an assertion failure is logged" lead is the
  known false positive at log line 24 (disposition **D7**) and is not reported.

Enumerated 1 / audited 1 / skipped 0.
</details>
