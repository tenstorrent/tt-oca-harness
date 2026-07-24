<!-- SPDX-License-Identifier: Apache-2.0 -->
# SEP OSS DV Testbench Audit Report

**Date**: 2026-06-29
**Auditor**: Claude Code (5-agent parallel audit, then synthesis)
**Scope**: Full SEP OSS DV environment — `hw/sys/sep/dv/` — 38 runnable cocotb tests (+ `sep_base_test.py` base), 28 seq_lib, 19 env (agents/scoreboards/goldens), 9 shims, 8 testlists, `sep_sim_cfg.toml`, `tb/tb_top.sv`, docs/VPLANs. Audited against `AGENTS.md` (§1–12), `hw/sep/doc/*.adoc` (spec golden), and `hw/sep/` RTL.
**Flow**: cocotb/PyUVM on Verilator (NOT OCAH SV-UVM) — categories adapted to that layout.

---

## Executive Summary

| Category | Issues | Critical | Notes |
|----------|--------|----------|-------|
| 1. Backdoor Access Inventory | 1 | 0 | All forces/probes on the §7 accepted list; 1 LOW (ESRC force lacks explicit release, plusarg-scoped) |
| 2. Permission / Access Matrix | 9 gaps | 0 | 8/17 cells covered; all 9 gaps map to **planned** Phase-2 reps or accepted/infra-gated deltas |
| 3. Message Severity | 0 | 0 | Clean — zero warnings; all checkers raise/assert |
| 4. Randomization | 0 | 0 | All 5 randomized reps use seeded config-object SSOT + reseed=3 |
| 5. Corner Cases | 2 | 0 | 1 planned (CPU-3 scratch), 1 accepted (counter-wrap); OTP-retry IS covered |
| 6. Status Cleanup | ~20 | 0 | **Systemic**: Phase/VPLAN-ID/TOP-20-seq markers in comments + runtime logs (§6 violation) |
| 7. Dead Code | 5 | 0 | 4 deliberately-ported golden accessors + 1 cosmetic f-string |
| 8. Conventions | 1 | 0 | Strong; only planning-IDs in log strings (overlaps Cat 6) |
| 9. Coverage Alignment | 1 | 0 | Phase-1 31/31 proven; 7 Phase-2 reps VCS-green, **Verilator merge-gate pending** |
| 10. Regression Readiness | 1 | 0 | Clean; 1 cosmetic TOML blank-line nit |
| 11. Documentation | 1 | 0 | PHASE2.md prose says "none implemented" while 7 reps are coded+enrolled |
| 12. RTL Evidence | 1 | 0 | 7 exact RTL matches; 1 MED (feat_ctrl strap observed only via frontdoor) |
| 13. Assertion Opportunities | ~8 | 0 | **No SVA/bind in OSS env** (Verilator not passed `--assert`; OT-style RTL SVA not Verilator-parseable → DISABLE_ASSERT); high-value bind candidates |
| 14. Port/IO Coverage | 2 | 0 | DFT `test_en_i`/`scan_rst_ni` hardcoded → scan path unexercised (documented/justified) |
| 15. Scoreboard Completeness | ~3 | 0 | Strong; CHK5 crypto-sinks observe-only; sep_scoreboard blind to m_axi path |
| 16. Test Overlap | 2 | 0 | Well-factored; 2 narrow accidental subsets + KAT 4× copy-paste (refactor candidate) |
| **Total** | **~45** | **0** | |

**Overall Verdict**: **PASS WITH ISSUES** — the environment is fundamentally sound. Backdoor policy, message severity, randomization, conventions, and regression readiness are all clean. There are **no critical correctness or policy violations**. The actionable work is: one systemic hygiene cleanup (Cat 6 status markers), one credit-gate item (Cat 9 Verilator regression for the 7 Phase-2 reps), and a set of high-value assertion opportunities (Cat 13). Most coverage "gaps" are already tracked as planned Phase-2 reps.

---

## 1. Backdoor Access Inventory

Every WRITE backdoor and XMR READ probe was cross-checked against the **authoritative AGENTS.md §7 accepted list**. Result: **nothing off-list.**

**WRITES (2 real backdoors + frontdoor port drives):**
- `tb/tb_top.sv:808` — ESRC raw-noise `force ...dcor.noise_i` (12 lanes, re-issued per posedge under `+esrc_noise_force`). On §7 list. **LOW: no explicit `release`** (plusarg-scoped per-run, so no cross-phase leak).
- `shims/cpu/sep_cpu_stub.sv:150` — CPU-LSU splice `assign lsu_axi_req = sep_uvm_top.lsu_req_drive` (single driver, NOT a force; the recent refactor). On §7 list.
- All Python `.value =` writes (`sep_base_test.py`, drbg scoreboard `esrc_noise_ext_i`, etc.) target **real DUT ports** — frontdoor, not internal-net pokes.

**READS:** ~25 continuous `assign <port>_o = u_dut.<net>` XMR probes — every one maps to an accepted §7 entry (run_ack, cpu_reset_n, internal_interrupts, efuse_shadow, scratch_cold, entropy CHK1-5 datapath, AXIS1, crypto EDN sinks, lsu_axi_resp readback). `uvm_hdl_*` grep hits are all in comments describing OCAH's backdoor for contrast — no live calls.

**Verdict**: clean. 1 LOW. No undocumented/unauthorized backdoor, no force-leak.

## 2. Permission / Access Matrix

8 of 17 spec access-control cells COVERED (~47%), several **stronger than OCAH** (exact 64-bit feat_ctrl golden; value-checked DECERR with `allow_timeout=False`).

COVERED: inbound-filter global skip (PROD deny / PROD_DBG allow), per-entry rule matrix (read_allowed/write_allowed directional), DEMOTE_1, feat_ctrl LC decode, RMA token-gated advance, OTP program-fail retry, JTAG LC-gating (shadow deny / MMR allow).

GAPS (all map to planned reps or accepted deltas — **no unplanned test needed**):
- DEMOTE_2/PROD_DBG_CHIPLET, DEMOTE_LOCK woset, per-field eFuse locks, secure_tm final gate → **planned EFL-1/2/3**.
- locked_field_access IRQ → **planned TD-4**.
- Outbound filter, AP/STEE remap datapath → **infra-gated** (DV cannot drive yet, VPLAN-documented).
- SEC_DIS override, lc_sigint_err fail-closed → **accepted gate-level/SVA-scope deltas**.

## 3. Message Severity

**Clean — 0 issues.** Zero `logger.warning`/`uvm_warning` anywhere in `cocotb/`. Every failure signal `raise`s or accumulates into an `errors[]` list asserted in `check_phase`/`report()` (verified: sep_scoreboard, sep_axi_monitor, sep_boot_scoreboard, sep_drbg_scoreboard strict mode, sep_efuse_backdoor_check). No warn-and-return patterns hiding failures.

## 4. Randomization Coverage

**Clean — 0 issues.** All 5 `reseed=3` reps (FAB-1, FAB-3, RST-1, PIO-1, TD-2) seed a dedicated config-object SSOT from `self.random_seed()` and walk required cells deterministically — fully §9-compliant (directed-first→upgrade). Directed/RAND-NONE tests (TD-3, FAB-2, KATs, smoke/FW) correctly omit reseed. (Optional: `sep_efuse_image_test` could set reseed>1 to broaden image coverage.)

## 5. Corner Case Discovery

Corner-case dimensions broadly COVERED (reset cold/warm/per-IP, WDT reset-path isolation, DECERR read+write, NMI on D-bus error, RW1C across INTR_STATE/mailbox/DMA/WDT, FIFO/watermark/aperture boundaries, both run-modes, real-sense vs skip, full interrupt fan-in + PIC delivery).

Residual gaps: **CPU-3 warm/cold scratch retention** (planned, #3220); **REFERENCE_COUNTER wrap** (accepted bare-SEP delta — sample-done tied low).
**Correction**: OTP program-failure injection+retry IS covered (`sep_efuse_lcc_lc_state_stitch_test` + `efuse_lcc.toml:42 +sep_efuse_prog_fail_count=1`) — not a gap.

## 6. Status Information Cleanup  ⚠️ (systemic — headline finding)

**~20 files** embed project status that §6 says belongs in docs/VPLAN/memory, not in `.py`/`.sv`/`.toml` infra — including **runtime log strings**:
- Phase/VPLAN-rep IDs in docstrings, comments, and `summary()` log lines: `"Phase-2 PIO-1"`, `"FAB-2 ... config"`, `"TD-2 fan-in config"`, `"RST-1 WDT config"`, `"E10 %s PASS"`, etc. (system-group tests + their seq_lib + sep_mbox_golden).
- TOP-20 roadmap sequence numbers used as identifiers: `"the #14 mirror"`, `"Distinct from #20"`, `"OTBN KAT #4 ... AES #11 / HMAC #12"`, `"TOP-20 #15"`, `"VPLAN initially assumed no_cpu; corrected"`.

**NOT findings (keep):** GitHub issue cross-refs `#2868`/`#2936` (§6 allows spec/issue cross-refs); OCAH edge IDs (E2/E4/E7-E12) as architectural provenance; `sep_cpu_stub.sv:91/97/103` FIXMEs (verbatim copies of the real `sep_cpu.sv` port comments — keep for fidelity). **Borderline:** `sep_sim_cfg.toml:53/84 FIXME(transition)` — move the "remove once upstream" rationale to docs.

Action: strip Phase-N / VPLAN-rep-ID / TOP-20-seq markers from infra comments AND runtime log strings; log what the code does, keep provenance in the VPLAN.

## 7. Dead Code

4 dead golden-model methods — `sep_ctr_drbg_golden.uninstantiate()`, `sep_noise_golden.get_state()`, `sep_decor_golden.set_bypass()`/`.get_sample_count()` — all deliberate ports of the OCAH C reference debug/replay API (benign-by-design). +1 cosmetic f-string-without-placeholder (`sep_entropy_golden.py:315`). **Verified clean**: no unused imports, no commented-out code blocks, all 38 testlist `module=` paths resolve, no orphan/dangling shims.

## 8. Consistency and Conventions

Strong. All 38 tests extend `sep_base_test` + `@pyuvm.test()`; **class name == testlist name == module basename** for all 38 (no mismatch); pyuvm-idiomatic pass/fail via `errors[]`+`check_phase`; config-first (no raw `os.environ` in tests); no helper duplication (bring-up/boot/entropy centralized in base). Only finding: planning-ID strings in runtime log output (overlaps Cat 6). 1 LOW.

## 9. Coverage Model Alignment

- **Phase-1**: 31/31 implemented + enrolled, all DONE with Verilator merge-gate evidence. 0 gaps.
- **Phase-2**: 7/26 reps implemented (FAB-1/2/3, RST-1, PIO-1, TD-2, TD-3), enrolled in `system.toml`+`all.toml`, **VCS-dev-green only**. 19 reps remain planned (CPU/MEM/DMA/EFL/KM/CRY/SPI/TD-1/TD-4, all with issue numbers).
- **No orphan tests, no untracked tests.**

**Actionable**: the 7 implemented Phase-2 reps are **not yet credited** — they were NOT in the last Verilator `all --regress` (`20260624_102154`, 31 tests). A kept Verilator regression (now `all`=38) is the pending credit gate. *(Note: the 2026-06-29 Verilator `all` run = 43/43 non-KM PASS, 5 KM blocked by #3266 — confirm it covers these 7.)*

## 10. Regression Readiness

Clean. 38/38 modules resolve; `all`(38)=`cpu`(13)+`no_cpu`(25) with no overlap/orphan; every no_cpu test sets `target=lsu_stub_all_live`; KAT timeouts adequate (7200s); **every bounded wait fail-checks on timeout** (FW `while(t-->0)`+FAIL, Python waiters wrapped in `assert await`, AXI/JTAG `with_timeout`→AssertionError) — §7-clean. 1 cosmetic: two abutting `[[tests]]` tables lack a blank separator (system.toml:153/203).

## 11. Documentation Alignment

1 MED stale-doc: `docs/SEP_OSS_VPLAN_PHASE2.md` prose summary (~lines 176/204) still says "26 total (STATUS=planned); NONE implemented yet / 19 remain planned" — but 7 reps are now coded + enrolled. The per-row mapping table IS current. README.md, AGENTS.md cross-refs, Phase-1 VPLAN all accurate. Reader-confusion only.

## 12. RTL Evidence Collection

7 behavioral assumptions verified **exact** against `hw/sep/`: inbound_filter_skip = `feat_ctrl.sep_debug` (sep.sv:820); `sep_cpu_reset_n = sep_reset_n & wdt_rst_ni` (sep_reset_ctrl.sv:59); wdt_rst_ni / wdt_timer_rst_req_o real ports; internal-interrupt aggregate bit map (CSRNG[21:24]/EDN[25:26]); smn_inbound traverses filter. 0 mismatches.
1 MED: `feat_ctrl_o`/`lc_state_o`/`security_disable_o` left unconnected in tb_top — the filter-gating test observes feat_ctrl only via the **frontdoor FEAT_CTRL CSR mirror** + filter effect, not the strap (documented stronger-than-OCAH substitution; mitigated by value-checked read). `secure_tm_o` is tied off in RTL itself (sep.sv:739 TODO) — unexercisable at sep top.

## 13. Assertion Opportunities

**Structural finding**: `cocotb/assertions/` is empty; `tb_top.sv` has zero `assert property`/`bind`. **Why there's no SVA — it is NOT a flat "Verilator can't do assertions":** (a) the Verilator target is not passed `--assert` (only the Xcelium target gets `-assert`, `native-cocotb.toml`), so assertion eval is off; and (b) the RTL's OpenTitan-style concurrent SVA uses constructs Verilator cannot parse (`##[1:$]` unbounded ranges, prim_alert_sender / kmac sha3pad sequences), which is exactly why the build defines `SYNTHESIS`/`DISABLE_ASSERT` to gate them out (sep_sim_cfg.toml:217-219). Verilator DOES support a useful subset (immediate + bounded concurrent `assert property` + `bind`), so **new, Verilator-friendly bind SVA is feasible** — but it requires enabling `--assert` on the Verilator target and authoring around the unsupported operators (not free). **All current checking is Python transaction/sample-level, mostly one-shot per test.** The only always-on continuous checker is `sep_axi_monitor` (checks just 2 properties: not-all-X-on-OKAY, DECERR-tally).

High-value bind-SVA / continuous-checker candidates:

| Property | Bind target | Priority |
|---|---|---|
| AXI handshake stability (valid held till ready; no payload change while stalled) on s_axi/m_axi/j_axi | tb_top AXI channels | HIGH |
| Inbound-filter block-by-default: external m_axi in PROD MUST be DECERR, never OKAY | inbound-filter slave / m_axi resp | HIGH (security; cf. #2868 polarity hole) |
| Lock-stays-locked / REGWEN monotonicity (WDT/filter woset/eFuse) | guarded register banks | HIGH |
| RW1C semantics continuous (mailbox IRQS, WDT/CSRNG/EDN INTR_STATE) | IRQ/status banks | MED |
| fuse-sense-done rises once per reset, monotonic | sep_fuse_sense_done_o vs rst_ni | MED |
| **LC-state legality / W1S-monotonic / valid-transition** | LCC lc_state | MED |

**Provenance note (NOT a gap — corrected)**: `sep_lcc_golden.py` references `assertions/sep_lcc_state_checker.sv`. That file is an **OCAH SV-UVM file** (`dv/sep/tb/tb_uvm/assertions/sep_lcc_state_checker.sv`); the OSS `sep_lcc_golden.py` is its **faithful Python port** — correct provenance, same pattern as the AES/HMAC/DRBG goldens that reference OCAH C reference models. Not a missing file. The only (minor) residual: the Python golden validates LC states it *samples*, not the *continuous live* `lc_state` sequence — a Verilator-friendly bind could add always-on coverage, but it is optional, not a hole the docstring falsely claims to fill.

## 14. Port/IO Coverage

`sep` DUT (`tb_top.sv:373`): ~12 driven, ~6 observed, ~20 tied-constant/idle, ~13 ignored-output.
2 MED: **`test_en_i` tied `1'b0` + `scan_rst_ni` tied `1'b1`** → DFT/scan path entirely unexercised (documented & justified — driving `test_en_i` live makes the reset/clock tree input-combinational under Verilator → ~1000x slowdown). Functional JTAG-TAP (`jtag_tck/tms/tdi/trst_n`) also unexercised (the jtag/efuse test uses the `axil_sep_otp_jtag` AXI-Lite port instead). Remaining tie-offs (straps, SMC addr, ext-TRNG, ext-IRQs, DMI) are intentional within no_cpu scope. No sep boundary port is exercised exclusively by backdoor.

## 15. Scoreboard Completeness

Strong overall:
- `sep_scoreboard` — **active** (response + read-value compare, non-vacuity floor); **blind to the m_axi external-master path** (only scores s_axi); no auto write→readback.
- `sep_axi_monitor` ×2 — only always-on raw checker; covers ~2 of the standard AXI properties (R/B channels only; AW/W/AR unchecked; RisingEdge-sampled so sub-cycle pulses can be missed; SLVERR tallied but never fails).
- `sep_boot_scoreboard` — complete for boot-liveness (PC-advance + PASS magic + banner); correctness delegated to firmware self-test (by design).
- `sep_drbg_scoreboard` (CHK1-5) — strongest; bit-exact CHK1-4; **CHK5 crypto sinks default to observe-only** (multi-concurrent-sink bit-exact = NotImplementedError, needs OCAH arbiter trace).
- `sep_mbox_golden` — complete for reachable TX path (RX infeasible on bare-sep, waived); AES/HMAC goldens complete; KMAC by known-key cross-check.

Cross-cutting gaps: m_axi error-response classification (only inline in gating test), register-bank reset behavior, permission-violation reads (only inside the jtag/efuse mux test).

## 16. Test Overlap & Redundancy (review-only)

Well-factored — most commonality is intentional shared infra in `sep_base_test.py`. Genuine accidental redundancy is narrow:
1. `sep_axi_smoke_test` ⊆ `sep_address_map_test` — same regs, **same literal patterns in the same order** (strongest review candidate).
2. `sep_efuse_sense_test` shadow-data check ⊆ `sep_efuse_image_test` (sense distinguished only by lighter `build_env=False` path).
3. `sep_boot_rom_smoke_test` functionally ⊆ `sep_rom_sanity_test` (but cheap pre-fw bring-up has diagnostic value).

Refactor candidate (maintainability, not correctness): the **4 KM-sideload KAT bodies** are a ~4× copy-pasted 4-phase template differing only by `dest` const + `score_sinks` → a `SepCryptoKatBase` would help. All IRQ/WDT/inbound-filter/DMA cluster overlaps resolve to **intentional layering** along distinct axes (verified at sequence level). **No deletion recommended.**

---

## Action Items (Priority Order)

### Critical (Must Fix Before Sign-off)
- [ ] None — no correctness or policy violations found.

### High (Should Fix)
- [ ] **Cat 6**: Strip project-status markers (Phase-N, VPLAN-rep-IDs PIO/TD/FAB/RST, TOP-20 `#NN` sequence refs) from ~20 infra files — comments **and** runtime `summary()` log strings. Keep GitHub `#2868`/`#2936` cross-refs and the stub's verbatim RTL FIXMEs.
- [ ] **Cat 9**: Confirm/keep a Verilator `all --regress` PASS log that includes the 7 implemented Phase-2 reps (FAB-1/2/3, RST-1, PIO-1, TD-2, TD-3) to credit them (VCS-green only today). The 06-29 run (43/43 non-KM) likely covers this — verify and capture.
- [ ] **Cat 13**: If pursuing assertions, enable `--assert` on the Verilator target and add the two highest-value Verilator-friendly continuous checkers — inbound-filter block-by-default (security) and AXI handshake stability. (Optional: a Verilator-friendly LCC `lc_state` bind for continuous coverage — the OSS `sep_lcc_golden.py` already ports the OCAH SVA checker for sampled points.)

### Medium (Nice to Have)
- [ ] **Cat 11**: Update `SEP_OSS_VPLAN_PHASE2.md` prose summary (lines ~176/204) — 7 reps are implemented+enrolled, not "none."
- [ ] **Cat 16**: Either differentiate `sep_axi_smoke_test` from `sep_address_map_test` or document the intentional smoke subset; consider a `SepCryptoKatBase` to de-duplicate the 4 KM KAT bodies.
- [ ] **Cat 15**: Score the m_axi external-master path in a scoreboard (today only inline in the gating test); add register-bank reset-value checking.
- [ ] **Cat 12/14**: Note the DFT/scan (`test_en_i`/`scan_rst_ni`) and feat_ctrl-strap observation gaps as accepted scope deltas in the VPLAN (they're justified, just record them).

### Low (Future Improvement)
- [ ] **Cat 1**: Add an explicit `release` for the ESRC noise force (or document that the `+esrc_noise_force` plusarg scoping makes it unnecessary).
- [ ] **Cat 7**: Trim or comment the 4 dead golden-model accessors as "reference-API, intentionally unused"; fix the cosmetic f-string.
- [ ] **Cat 10**: Add a blank line between the abutting `[[tests]]` tables in `system.toml`.
- [ ] **Cat 6**: Move the `sep_sim_cfg.toml` `FIXME(transition)` rationale to docs.

---

*Audit method: 5 parallel read-only investigator agents (Cat 1/12/14, 2/5/9, 3/6/7/8, 4/10/11, 13/15/16), findings synthesized here. No files were modified during the audit.*
