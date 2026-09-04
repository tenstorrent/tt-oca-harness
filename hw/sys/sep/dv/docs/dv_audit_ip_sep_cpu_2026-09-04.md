# DV Audit — SEP `cpu` bucket

**Cannot sign off.** One test asserts a property nothing in it observes.
17 enumerated · 17 audited · 4 set aside by name (below) · 1 BLOCKED, 3 WEAK, 13 CLEAN, 0 ACCEPTED, 0 NO-EVIDENCE.
The one thing in the way: `sep_reset_wdt_sanity_test` claims per-IP reset isolation and never reads a neighbouring domain.

Policy: `~/.claude-ai/skills/dv_audit/references/dv_policy.md` v1.0, sha256 `37cf7610c45aa…` (not under git). Run audited: `build/runs/20260904_035853__verilator__all`. Date: 2026-09-04.

## Needs a decision

| Test | Verdict | The mechanism, in plain words |
|---|---|---|
| `sep_reset_wdt_sanity_test` | BLOCKED | The plan says pulsing one IP's reset bit leaves its neighbours untouched. The firmware reads only the register belonging to the IP it just reset, so a design that resets *every* crypto domain on any bit passes all seven rows — and prints "reset wire OK" seven times, which is what the log shows. |
| `sep_efuse_token_match_fault_pic_test` | WEAK | Proves the masked interrupt does not re-enter, but never shows the source was still asking to during the quiet window. Separately, the fault bit it reads is a hand-typed `0x00010000` where every other register reference in the file resolves by generated symbol. |
| `sep_mailbox_plic_test` | WEAK | Same quiet-window shape: the interrupt enable is cleared *before* the no-re-fire window opens, so that clause can pass on a design whose status latch never cleared. The falsifiable part of the claim — the handler ran exactly once — does hold. |
| `sep_warm_cold_reset_scratch_test` | WEAK | The one check whose passing value is zero reads the reset observable through a helper that turns unknown bits into zeros, so "reset asserted" and "signal is X" look identical. The warm/cold bank comparison independently corroborates that the reset really happened. |

The other 13 are CLEAN; their deciding lines and claims are in Appendix C.

## Findings

### F1 — Per-IP reset isolation is claimed and never observed — MUST-FIX

**Where:** `fw/tests/reset_wdt_sanity_test/reset_wdt_sanity_test.c:86-107` (`check_reset_wire`), called seven times at `:128-136`
**Claim it falsifies:** "Pulsing each per-IP bit, the shared TRNG bit included, returns that domain's probe register to its reset value **and leaves the neighbouring domains untouched**." (`docs/SEP_VPLAN.adoc:2006`, checker CHK-SWRST-WIRE; ladder rung 1)
**Why the pass means nothing for that clause:** `check_reset_wire` takes one `probe_addr`. It writes it, confirms the write, pulses one `SW_RESET_N` bit, and re-reads *the same address*. No other IP's probe is read at any point after any pulse. The seven rows run in sequence, and each row writes its own probe **after** the previous row's pulse, so collateral damage is always overwritten before it could be seen. An `SW_RESET_N` decode that drives every crypto domain's reset from any bit satisfies all seven rows identically. The log confirms the shape of the pass — seven "reset wire OK" lines, no neighbour read among them.
**Not delegated elsewhere:** `sep_crypto_per_ip_reset_isolation_test` does exist and does own this property, but the CHK-SWRST-WIRE row does not link it, so policy 2.1's "a test the claim explicitly links" does not apply — and that test is itself FAILing in this run (`AssertionError: in-window HMAC CFG write resp=2 timed_out=False, expected DECERR`). It is in the `crypto` bucket, outside this audit.
**What would make it real:** the smaller of two fixes. Either write a non-default value into one neighbour's probe before the pulse and assert it still holds afterwards — one extra read per row — or strike the "leaves the neighbouring domains untouched" conjunct from the checker row and link `sep_crypto_per_ip_reset_isolation_test` as the test that owns it.

### F2 — Two "the masked interrupt does not re-enter" checks open their quiet window after removing the stimulus — GOOD-TO-HAVE (one defect, two instances)

**Where:**
- `fw/tests/mailbox_plic_test/mailbox_plic_test.c:86` clears `IRQEN`, and the quiet window runs afterwards at `:184-191`
- `fw/tests/token_match_fault_pic_test/token_match_fault_pic_test.c:100-111`, where the window compares only `g_isr_count` and samples nothing showing source 40 still asserted

**Claims:** "The routine runs exactly once … and the interrupt does not re-fire afterwards" (CHK-NOSTORM) and "masks `meie[40]` so the **level-high** line does not re-enter" (CHK-PIC-MASK). Both rung 1.
**Why the pass is weaker than it reads:** each claim attributes the silence to the mask. In both tests the silence is observed in a window where the request may no longer be present — in the mailbox case because `IRQEN` was cleared first, in the eFuse case because nothing re-reads the sticky fault or the pending bit while masked. On a design whose status latch never cleared, or whose request dropped by itself, both windows stay quiet and both checks pass. What keeps this out of MUST-FIX is that the load-bearing half of each claim is checked elsewhere in the same test and does fail on a real defect: `g_isr_count != 1` at `mailbox_plic_test.c:176`, and the claim-id compare at `token_match_fault_pic_test.c:86`.
**Trigger:** whether the source line is in fact still asserted during each quiet window — i.e. whether clearing `IRQEN` alone deasserts `axil_mailbox.outbound_interrupt_o[0]` independently of `IRQS`, and whether the collapse-driven fault request stays high with `meie[40]` masked. **Not evaluated** — both need the request-path RTL or a waveform, neither of which is an input to this audit. If either line does drop on its own, that clause becomes policy 1.4 for that test.
**What would make it real:** move the `IRQEN` clear to after the mailbox test's quiet window (its own comment already calls the clear a "belt, harmless once IRQS is 0"), and re-read `TOKEN_MATCH_FAULT` or the source-40 pending bit inside the eFuse test's window, asserting the source is still up while masked.

### F3 — Every "expected zero" check that reads a DUT signal through the shared `rd()` helper cannot tell zero from unknown — GOOD-TO-HAVE

**Where:** the helper is `cocotb/tests/sep_base_test.py:85-97`, which resolves unknown bits to zero per bit and says so in its own docstring: "Callers that must distinguish 'unknown' from 'zero' cannot use this." The instance that matters in this bucket is `cocotb/tests/cpu/sep_warm_cold_reset_scratch_test.py:84-89` (`_check_reset_obs`), called at `:150-152` with `expected=0`.
**Claim:** "A warm reset source drops the CPU reset observable (assert then release)." (CHK-WARM-RST, rung 1)
**Why it is only a GOOD-TO-HAVE:** the asserted-low sample is the one check whose *passing* value is exactly what `rd()` returns for an X, so `PASS: CHK-WARM-RST asserted sep_cpu_reset_n == 0` prints either way. The baseline and released samples expect 1 and are immune. And the warm reset is independently corroborated in the same test: all eight warm registers went from distinct non-zero patterns to zero while all eight cold registers held theirs, which cannot happen without a real warm reset.
**Trigger:** whether `sep_cpu_reset_n_o` can be X during the `wdt_rst_ni_i`-low window. **Evaluated for the sibling test and excluded there** — in `sep_cpu_dbg_reset_independence_test` the same shape is safe because the observable is an AND gate with a hard 0 driven on one input, which cannot produce X. **Not evaluated for the warm/cold test,** whose reset path is longer.
**What would make it real:** read the raw bit string for the asserted case and require `"0"`, rather than comparing an X-resolved integer against zero. Both tests would benefit; only the warm/cold one currently needs it.

### F4 — Four plan entries disagree with the tests that satisfy them, and the tests are right — OBSERVATION, routed to the plan owner

**Where and what:**
- `docs/SEP_VPLAN.adoc` CHK-HOSTINTG and `testlists/cpu.toml:105` say interrupt aggregator "bit 40" and "bit 39"; the test uses 41 and 40 (`cocotb/tests/cpu/sep_dma_basic_test.py:65-66`), matching the shared constant `IRQ_DMA_HOST_PATH = 41` in `cocotb/seq_lib/sep_irq_aggregator_seq.py:49`. The log records `vec=0x21000000000` — bits 41 and 36 — so the code is the correct side.
- The `sep_efuse_token_match_fault_pic_test` entry says source 40 twice in its objective and procedure, then says "claim id is 39" in its CHK-PIC-CLAIM row; `testlists/cpu.toml:176` repeats 39. The firmware checks 40 and the interrupt fires, so 39 is stale.
- `docs/SEP_VPLAN.adoc:3252-3255` (`sep_cpu_dbg_reset_independence_test`) lists one procedure step and describes two checkers — the CHK-LIVE reset drop-and-restore is missing from the procedure.
- `sep_cpu_trace_diag_test` has **no plan entry at all** — no `[[…]]` anchor and no mention anywhere in the plan — while the other 16 have one. The audit fell to rung 2, the test's own docstring.

**Why none of these is a testcase finding:** in every case the DUT corroborates the test's number, and a wrong number would have produced a failure rather than a false pass. But a reader of the plan alone gets the wrong bit index, the wrong interrupt id, an incomplete procedure, and in one case no contract to read. The missing entry is the one worth acting on: a docstring claim is written by the test's own author, so policy 1.5 — proved the wrong thing — is structurally weaker for that test than for the other 16.
**What would fix it:** correct the three numbers and the procedure list; add a `[[sep_cpu_trace_diag_test]]` entry with its four checker contracts, reviewed by someone other than the test's author.

### F5 — Firmware image identity is not recorded in any log — OBSERVATION

**Where:** absence, across all 13 firmware-boot tests in this bucket. `boot_firmware()` (`cocotb/tests/sep_base_test.py:504-511`) copies `fw/build/tests/<name>/*.itcm.hex` into the run directory and logs "staged firmware TCM images", naming no revision or build identity for the image.
**Why it matters:** for these tests the substantive checking happens in the C, and the C that ran is the compiled image, not the source this audit read. Nothing ties the two. The same absence is what makes log freshness NO-EVIDENCE for all 17 (see Appendix A), and it is the single cheapest thing a human could add.
**What would fix it:** log the image's build identity — a hash, or the compiler's own output stamp — beside the "staged firmware TCM images" line, so a kept log names what it ran.

### F6 — Two smaller hand-transcription and staging items — OBSERVATION

- `fw/tests/token_match_fault_pic_test/token_match_fault_pic_test.c:28` defines `FAULT_SEC_DISABLE 0x00010000u` as a literal, used at `:93`, while every other register reference in that file resolves by generated symbol. Policy 2.3 — right today, silently rots at the next register-map regeneration. **Trigger** (is bit 16 in fact the wrong field, which would make it 1.5): **evaluated, and it does not fire** — the literal matches the generated mask `EFUSE_MMR_TOKEN_MATCH_FAULT_SECURE_DISABLE_TOKEN_FAULT_MASK = 32'h10000` at `hw/sys/sep/regs/gen/svh/sep_reg.svh:6420`. So the value is correct and this stays GOOD-TO-HAVE. It contributes to that test's WEAK verdict.
- `fw/tests/dma_hash_test/dma_hash_test.c:41-46` likewise hand-writes field *values* (`MUBI4_TRUE 0x6`, `OPCODE_SHA256 0x1`, and two more) where `dma_basic_test.c` uses generated symbols for the same fields.
- `tb/tb_top.sv:1015-1021` loads the boot ROM by CWD filename convention with no plusarg, so `sep_boot_rom_smoke_test` couples to its image implicitly where its two siblings pass `+sep_boot_rom_hex=` explicitly. Fail-safe rather than fake-pass: a missing file leaves the ROM zero-filled, which is an illegal instruction, and the test's four-PC check would fail.

## What I did not check

- **The triggers on F2 and F3.** Both turn on whether a signal was still asserted during a quiet window, which needs the request-path RTL or a waveform. Naming them is the honest result; three of the four WEAK verdicts rest on exactly these. (F6's field-layout trigger was evaluated and cleared, and the boot-ROM boundary address in `sep_boot_rom_lsu_read_test` was confirmed against the generated map at `hw/sys/sep/regs/gen/c/sep_addr.h:15-16` rather than inferred from its PASS line.)
- **Whether the goldens for the two hashing tests are right**, as opposed to independently sourced. Provenance was traced and is clean — `fw/tests/common/sha256.c` is a public-domain FIPS 180-2 implementation recomputed per run, not read off the design — but judging correctness is design review, not this audit.
- **Bus-level arbitration in `sep_dma_cpu_contention_test`.** Its mid-flight `BUSY && !DONE` sample proves both masters were active at once; it does not prove they contended at the SRAM slave. That needs a monitor.
- **Whether quiet windows are long enough** (256 nops in the mailbox test, 4096 in the PIC and eFuse tests) to catch a slow re-arm. A quiet window has no handshake to wait on, so policy 2.4 does not apply, but sufficiency would need a waveform.
- **Stimulus reach in `sep_dma_basic_test`:** all three seeds happened to draw the 16-byte length from `rng.choice((16, 32))`, so the 32-byte case did not run. A stimulus gap, which policy §4 explicitly excludes from being a finding.
- **The `sep_reset_wdt_sanity_test` yellow triggers.** Once a test is BLOCKED the skill says stop; its remaining unevaluated items are the 200-nop settling delays and the provenance of the `SW_RESET_N` reset-default golden.
- **Anything in the four set-aside ROM-firmware tests**, named in Appendix B.

Budget spent: 17 test sources and 13 firmware C files read on their proof paths, 6 shared-infrastructure files audited once in the parent, 17 logs summarized and 8 read in the windows that mattered, 4 verification-plan entries extracted plus the claim map over all 80 plan anchors, roughly 30 shell searches.

## Appendix A — inputs

| Input | Status |
|---|---|
| Test sources | `cocotb/tests/cpu/` (20 files) plus `cocotb/tests/efuse/sep_efuse_token_match_fault_pic_test.py` |
| Firmware on the proof path | `fw/tests/<name>/<name>.c`, `fw/drivers/`, `fw/include/`, `fw/startup/crt0.s` |
| Verification plan | `docs/SEP_VPLAN.adoc` — anchored entries for 16 of 17; none for `sep_cpu_trace_diag_test` |
| Testlists | `testlists/cpu.toml` (11 entries), plus `memory.toml`, `crypto.toml`, `system.toml` for the 9 tests filed under `cpu/` but catalogued elsewhere, and `all.toml` for group membership |
| Simulation logs | `build/runs/20260904_035853__verilator__all` — 17 of 17, all PASS; run totals 134 PASS / 4 FAIL |
| Approval records | **none exist anywhere under `hw/sys/sep/dv/`** — so nothing here is ACCEPTED, and any unapproved backdoor supplying checked state was filed red |

**Freshness (policy 1.7):** NO-EVIDENCE for all 17. No log names a revision or compile identity, which by the skill's stated method is missing provenance, not a demonstrated lie. What is positive: every test is enrolled in a scheduled group and this run executed it.

**Runs that disagree, and why they do not:** eight of these 17 report ERROR in the earlier `20260904_032049__verilator__all` run. Every one is the same infrastructure failure — `FileNotFoundError` on a `sep_uvm_top` binary under a build fingerprint that was never built — so those leaves never simulated. An ERROR that never ran is not a verdict, so this is not a two-runs-disagree finding. The later run was used throughout.

**Shared infrastructure, audited once in the parent, fail-closed:** `env/sep_boot_scoreboard.py:94` asserts and fails on fewer than 16 distinct fetch PCs, on firmware never signaling completion, on the FAIL magic, and on a missing console banner; `tb/sep_outbound_mbx.sv:114-142` requires the two-word `0xA5A55A5A` → `0xCAFEBABE` sequence; `fw/startup/crt0.s:166-176` converts a non-zero `main()` return into the FAIL magic and its default trap handler fails the test. No timeout anywhere on these paths is treated as a pass. All 17 tests in this bucket keep a real console banner; only the two set-aside ROM tests clear it.

**One scanner artifact, dismissed:** the log summarizer reports "claims PASS but an assertion failure is logged" on all 17. It is line 9 in each — cocotb noting that pytest is not installed for better `AssertionError` messages. Not a finding.

## Appendix B — enumeration

**Enumerated 17, audited 17.** The denominator is the union of three sources that disagree: `testlists/cpu.toml` (11 entries), the `cocotb/tests/cpu/` directory (20 files), and the plan's anchors. One `cpu.toml` entry lives under `tests/efuse/`; nine tests in the `cpu/` directory are catalogued in other testlists while still running in the `cpu` group. No test on disk is unenrolled, and no plan entry in this bucket links a test that does not exist.

**Set aside, 4, by agreement before the audit began:** `sep_rom_non_secure_boot_test`, `sep_rom_ot_dma_boot_test`, `sep_rom_ot_pio_boot_test`, `sep_rom_ot_secure_boot_test`. They are ROM-FW-owned, catalogued in `rom_fw.toml`, run only in the `rom_fw` group, and `testlists/all.toml:31-32` together with the plan's Known Limitations state that this plan does not grade them. They have no plan entry, so they would return UNAUDITABLE against a claim the package never made. **Three of the four are FAILing in this run** (`_ot_dma_`, `_ot_pio_`, `_ot_secure_`) — not fake passes, but their owner should know.

**Disagreements found outside this bucket, recorded because the enumeration surfaced them:** `sep_lcc_lc_state_transition_matrix_test` exists on disk, is in no testlist, and has no plan entry — the policy 1.7 shape of a test no regression will run. Three plan anchors have no test file (`sep_km_command_set_rand_test`, `sep_km_crc_pcpi_kat_test`, `sep_km_kpv_scrambler_test`); all three are declared parked on a dedicated Key Manager ROM image in the plan's own "Parked vehicle contracts" section, so they are not findings.

## Appendix C — the 13 clean verdicts, itemized

Each row carries the line that decides pass/fail and the claim it was judged against. For the firmware tests the substantive verdict is the C `return errors`, which `crt0.s` converts into the magic word that `env/sep_boot_scoreboard.py:94` asserts on.

| Test | Deciding line | Claim, and rung |
|---|---|---|
| `sep_hello_world_test` | `env/sep_boot_scoreboard.py:94` | "The core boots from tightly-coupled memory and reaches the firmware entry point, proven by console output that only executed code can produce." (1) |
| `sep_rom_sanity_test` | `cocotb/tests/cpu/sep_rom_sanity_test.py:78` | "All seven functions fetch and execute correctly, each returning its distinct expected value … a partial result is a failure." (1) |
| `sep_boot_rom_smoke_test` | `cocotb/tests/cpu/sep_boot_rom_smoke_test.py:63` | "All four boot-ROM fetch addresses are reached and retired on the core's retired-instruction trace. Instruction content is not compared here." (1) |
| `sep_boot_rom_lsu_read_test` | `fw/tests/rom_lsu_read_test/rom_lsu_read_test.c:123` | "Load-store reads of ten half-words across five distinct 64-bit ROM words match the loaded image, against hard-coded literals." (1) |
| `sep_cpu_trace_diag_test` | `cocotb/tests/cpu/sep_cpu_trace_diag_test.py:89` | "…takes exactly one breakpoint trap inside the innermost frame … then cross-checks the trace monitor's reconstruction against that ground truth." (**rung 2** — no plan entry; see F4) |
| `sep_cpu_dbg_reset_independence_test` | `cocotb/tests/cpu/sep_cpu_dbg_reset_independence_test.py:51` | "A real reset source drops the CPU reset observable and then restores it, so the observable is live rather than stuck at one." (1) |
| `sep_dma_basic_test` | `fw/tests/dma_basic_test/dma_basic_test.c:927` | "Secure-DMA control and copy breadth over the CPU LSU: documented reset values, the configuration lock … FIXED/INCR/WRAP against a per-mode golden … a fabric DECERR dest that raises `host_path_err`." (1) |
| `sep_dma_hash_test` | `fw/tests/dma_hash_test/dma_hash_test.c:299` | "…the copied data is identical to the source, and the hardware digest equals a software SHA-256 computed over the same bytes." (1) |
| `sep_dma_cpu_contention_test` | `fw/tests/dma_cpu_contention_test/dma_cpu_contention_test.c:90` | "The only test where the CPU and the DMA engine are genuinely competing masters on the SRAM at the same instant." (1) |
| `sep_hmac_kmac_cpu_crypto_smoke_test` | `fw/tests/hmac_kmac_smoke_test/hmac_kmac_smoke_test.c:54` | "Brings the HMAC and KMAC engines up over the real CPU-to-fabric path, as a complement to the sideload tests." (1) |
| `sep_cpu_ifu_lsu_alias_remap_matrix_test` | `fw/tests/cpu_alias_remap_test/cpu_alias_remap_test.c:158` | "A write through the alias window with a NON-reset base programmed lands at the physical address that base selects." (1) |
| `sep_nmi_sanity_test` | `fw/tests/nmi_sanity_test/nmi_sanity_test.c:186` | "…the vector register has the right default, accepts a new value, and refuses further writes once locked — and then a real watchdog bark delivers an actual non-maskable interrupt to that handler." (1) |
| `sep_pic_irq_source_map_delivery_test` | `fw/tests/pic_irq_source_map_test/pic_irq_source_map_test.c:473` | "Prove the PIC delivers a seeded subset of interrupt sources to the CPU with one-hot claim and RW1C clear." (1) |

### Why 13 clean is not a shrug

The two tests judged most likely to be defective, and what cleared each:

**`sep_dma_basic_test`** — the largest surface in the bucket, twelve checkers, and a testbench-driven inject pin on the proof path, which is the classic policy 1.6 shape. It cleared because the inject pin (`sep_dma_basic_test.py:156`) is a DUT input used as *stimulus*, while every checked value is produced downstream by the design: the host-path error legs anchor on `DMA_BUS_ERR_STATUS.host_path_err` and on the aggregator vector read from `sep_internal_interrupts_probe_o`, never on the inject request. Beyond that, each error leg uses an exclusive `ERROR_CODE` compare rather than a subset mask, both configuration locks carry a pre-lock positive control, the width check reads the width register back so its three iterations are distinguishable, and a transfer that finished too fast to observe BUSY is a hard failure rather than a skip.

**`sep_cpu_ifu_lsu_alias_remap_matrix_test`** — a base-address register whose operating value equals its reset value is the textbook unfalsifiable readback. It cleared because the firmware refuses that shortcut: it first probes the register with `0xE0000000`, a value distinct from the `0xD0000000` reset, then programs that non-reset base and writes through the alias, requiring the marker to appear at the physical address *that base* selects. A remapper hardwired at the reset base lands the marker somewhere else and fails. The instruction-fetch leg then calls a function through the alias and requires its return value, which an unremapped fetch cannot produce.
