<!-- SPDX-License-Identifier: Apache-2.0 -->
# SMU OSS Skill-1 Feature List + Checkbox Mapping (P1/P2/P3/P4)

> **Status:** Draft for designer approval (aidv Skill 1).  
> **Pinned scope:** SEP=0 P1+P2+P3+P4 (`SMU_VPLAN.md`; Appendix A / SEP=1 OUT).  
> **SPEC refs:** `SMU_SPEC.md` Features 1/3/4/6/7 + IF matrix in VPLAN §4 + P3 §7 + P4.  
> **Does not claim:** designer sign-off until `[DESIGN-APPROVAL]` is recorded.

FEATURE-IDs reuse VPLAN `IF-*` atoms (stable). Each feature maps to one or more
CHK-* checkers. Each check logs a token via `SmuScoreboard` (auto from the check
name, or the explicit `evidence=` argument); tokens appear in the log as
`EVIDENCE: <TOKEN>` lines.

---

## Legend

| Field | Meaning |
|-------|---------|
| FEATURE-ID | Stable IF-* from VPLAN |
| SPEC-REF | `SMU_SPEC.md` / VPLAN section |
| MILESTONE | P1 or P2 |
| CHK-* | Per-step checkbox; PASS only with its check token in the log |
| Primary test | Owning testcase (supersets OK) |

---

## Feature inventory (P1+P2 in-scope)

### Clocks / resets

```text
FEATURE-ID: IF-CLK-01   SPEC-REF: SPEC Interfaces/Clocks · VPLAN §4.1   MILESTONE: P1
INTENT: smu/ref/periph clocks advance; bring-up completes
- [ ] CHK-CLK-BRINGUP     EXPECT: reset_done after cold/primary rise   TOKEN: CLK_BRINGUP_OK
  Primary: smu_base_test bring-up (all tests)
```

```text
FEATURE-ID: IF-RST-01   SPEC-REF: SPEC Interfaces/Resets · VPLAN §4.1   MILESTONE: P1
INTENT: cold/powergood/primary_* release and stay high
- [ ] CHK-RST-COLD-STABLE EXPECT: rst_cold_stable_ref_clk_no == 1      TOKEN: RST_COLD_STABLE_1
- [ ] CHK-RST-PRIMARY     EXPECT: rst_primary_smc_clk_no == 1          TOKEN: RST_PRIMARY_SMC_1
  Primary: smc_reset_ctrl_test, smu_smc_smoke_test
```

```text
FEATURE-ID: IF-RST-03   SPEC-REF: SPEC Feature 3 · VPLAN §4.1          MILESTONE: P2
INTENT: IC_RESET TDR overrides SMC fuse/warm/cool/cold mutually exclusive
- [ ] CHK-IC-DEFAULT      EXPECT: IC_RESET default all-ones            TOKEN: IC_RESET_DEFAULT
- [ ] CHK-IC-DOMAIN       EXPECT: one domain ovrd=1; others 0          TOKEN: IC_RESET_DOMAIN_EXCL
  Primary: smu_jtag_reset_override_test, smu_ic_reset_smc_multi_domain_test
```

```text
FEATURE-ID: IF-PWR-01   SPEC-REF: SPEC Interfaces/Power · VPLAN §4.1  MILESTONE: P1
INTENT: powergood assert precedes cold release
- [ ] CHK-PWR-SEQUENCE    EXPECT: bring-up order powergood then cold   TOKEN: PWR_SEQUENCE_OK
  Primary: smu_base_test bring-up
```

### SMN AXI fabric

```text
FEATURE-ID: IF-AXI-01..08  SPEC-REF: SPEC Feature 4 · VPLAN §4.2      MILESTONE: P1/P2
INTENT: SEP=0 SMN subordinate/manager, filter, ID-width, ATOP, remap, DECERR
- [ ] CHK-AXI-SMOKE-DECERR EXPECT: unfiltered SMN DECERR               TOKEN: AXI_SMOKE_DECERR
- [ ] CHK-AXI-FILTER-OKAY  EXPECT: after program, window OKAY+data     TOKEN: AXI_FILTER_OKAY
- [ ] CHK-AXI-ID-WIDTH     EXPECT: ID conversion path completes        TOKEN: AXI_ID_WIDTH_OK
- [ ] CHK-AXI-ATOP         EXPECT: ATOP rejected                       TOKEN: AXI_ATOP_REJECT
- [ ] CHK-AXI-REMAP        EXPECT: GLOBAL_BASE remap observed          TOKEN: AXI_GLOBAL_BASE
  Primary: smoke, sys_in_filter_program, id_width, atomic, global_base_remap, crossbar_error
```

### DTP JTAG / debug

```text
FEATURE-ID: IF-JTAG-01   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P1
INTENT: PTAP IDCODE/BYPASS
- [ ] CHK-JTAG-IDCODE     EXPECT: IDCODE matches TAP                   TOKEN: JTAG_IDCODE_OK
  Primary: smu_dtp_jtag_smoke_test
```

```text
FEATURE-ID: IF-JTAG-02   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P2
INTENT: Fabric JTAG2AXI SIZE/WSTRB + error path
- [ ] CHK-J2A-RW-MATRIX   EXPECT: SIZE/WSTRB readback match            TOKEN: J2A_RW_MATRIX_OK
- [ ] CHK-J2A-DECERR      EXPECT: unmapped DECERR + poison             TOKEN: J2A_DECERR_POISON
- [ ] CHK-J2A-RECOVERY    EXPECT: VERSION_LO SUCCESS after error       TOKEN: J2A_RECOVERY_OK
  Primary: smu_dtp_jtag2axi_smc_rw_matrix_test, smu_dtp_jtag2axi_smc_error_path_test
```

```text
FEATURE-ID: IF-JTAG-03   SPEC-REF: SPEC Feature 7 · VPLAN §4.3         MILESTONE: P2
INTENT: feat_ctrl / security_disable gate polarities
- [ ] CHK-FEAT-NET-GOLDEN EXPECT: disable nets match jtag_ptap eqs     TOKEN: FEAT_NET_GOLDEN
- [ ] CHK-FEAT-FAB-ALLOW  EXPECT: SUCCESS + VERSION_LO                 TOKEN: FEAT_FAB_ALLOW
- [ ] CHK-FEAT-FAB-DENY   EXPECT: not SUCCESS+VERSION_LO               TOKEN: FEAT_FAB_DENY
- [ ] CHK-FEAT-OTP-ALLOW  EXPECT: OTP MAP write/read/shadow match      TOKEN: FEAT_OTP_ALLOW
- [ ] CHK-FEAT-OTP-DENY   EXPECT: gated write leaves shadow unchanged  TOKEN: FEAT_OTP_DENY
  Primary: smu_dtp_feat_ctrl_gate_matrix_test (+ P1 security/lifecycle)
```

```text
FEATURE-ID: IF-JTAG-04   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P2
INTENT: OTP JTAG2AXI complete MAP R/W + gated contrast; SEP=0 err_slv
- [ ] CHK-OTP-MAP-RW      EXPECT: RDATA == shadow == pattern           TOKEN: OTP_MAP_RW_OK
- [ ] CHK-OTP-GATED       EXPECT: gated write does not update map      TOKEN: OTP_GATED_NO_UPDATE
- [ ] CHK-OTP-SEP0-ERR    EXPECT: hier DECERR + 0xBADCAB1E             TOKEN: OTP_SEP0_ERR_SLV
  Primary: smu_dtp_otp_smc_complete_rw_test, smu_dtp_otp_sep0_err_slv_test
```

```text
FEATURE-ID: IF-JTAG-05   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P2
INTENT: boot-stall sticky across cold; TRST clears; re-assert sticky
- [ ] CHK-STALL-STICKY    EXPECT: stall survives cold (TRST high)      TOKEN: STALL_COLD_STICKY
- [ ] CHK-STALL-TRST      EXPECT: TRST clears stall; fuse rises        TOKEN: STALL_TRST_CLEAR
- [ ] CHK-STALL-REASSERT  EXPECT: re-assert does not re-gate fuse      TOKEN: STALL_REASSERT_STICKY
  Primary: smu_boot_stall_jtag_cold_reset_matrix_test
```

```text
FEATURE-ID: IF-JTAG-07   SPEC-REF: SPEC Feature 6 · VPLAN §4.3         MILESTONE: P2
INTENT: CLA clock-stop feedback loop
- [ ] CHK-CLA-LOOP        EXPECT: Force fb -> req[0] -> stop + TDR bit4 TOKEN: CLA_CLK_STOP_LOOP
  Primary: smu_dtp_clock_stop_smc_cla_loop_test
```

```text
FEATURE-ID: IF-JTAG-08   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P2
INTENT: abs DTP CSR hole + hier CTN CONFIG
- [ ] CHK-DTP-ABS-HOLE    EXPECT: abs DECERR + AXIL idle               TOKEN: DTP_ABS_HOLE
- [ ] CHK-DTP-HIER-CTN    EXPECT: relative CONFIG OKAY + readback      TOKEN: DTP_HIER_CTN_OK
  Primary: smu_dtp_csr_access_test
```

```text
FEATURE-ID: IF-JTAG-09   SPEC-REF: SPEC Feature 3 · VPLAN §4.3         MILESTONE: P2
INTENT: both-direction SMC fabric + DTP CTN
- [ ] CHK-XDOM-A          EXPECT: VERSION_LO SUCCESS                   TOKEN: XDOM_VERSION_OK
- [ ] CHK-XDOM-B          EXPECT: CTN CONFIG hier R/W                  TOKEN: XDOM_CTN_OK
  Primary: smu_fabric_smc_dtp_cross_domain_test
```

### Cross-trigger

```text
FEATURE-ID: IF-XT-02   SPEC-REF: SPEC Feature 6 · VPLAN §4.4           MILESTONE: P2
INTENT: CTM four-phase on [9:2]; SMC [1:0] idle
- [ ] CHK-XT-DEST-4PH     EXPECT: legal dest req/ack order             TOKEN: XT_DEST_4PHASE
- [ ] CHK-XT-SRC-4PH      EXPECT: legal src req/ack order              TOKEN: XT_SRC_4PHASE
  Primary: smu_xtrig_ctm_four_phase_test
```

```text
FEATURE-ID: IF-XT-03   SPEC-REF: SPEC Feature 6 · VPLAN §4.4           MILESTONE: P2
INTENT: SMC CLA glue [1:0]; src_ack[1:0]==0 hardwire
- [ ] CHK-XT-SMC-GLUE     EXPECT: Force src_req <-> ss_i; ss_o <-> dst TOKEN: XT_SMC_GLUE
- [ ] CHK-XT-ACK-HARDWIRE EXPECT: src_ack[1:0] == 0                   TOKEN: XT_ACK_HARDWIRE_0
  Primary: smu_dtp_xtrigger_smc_cla_test
```

### SMC local

```text
FEATURE-ID: IF-SMC-09   SPEC-REF: SPEC Feature 1 · VPLAN §4.5          MILESTONE: P2
INTENT: WDT first timeout WDOGIP0; warm scratch domain split
- [ ] CHK-WDT-IP0         EXPECT: WDOGIP0 sets after enable+CMP        TOKEN: WDT_WDOGIP0
- [ ] CHK-WDT-SCRATCH     EXPECT: cold sticky; cold_warm cleared       TOKEN: WDT_SCRATCH_DOMAIN
  Primary: smc_wdt_timeout_irq_test, smc_reset_unit_wdt_scratch_test
```

```text
FEATURE-ID: IF-CFG-01/02  SPEC-REF: SPEC SEP=0 · VPLAN §4.6            MILESTONE: P1/P2
INTENT: SEP=0 apertures; SEP-OTP err_slv
- [ ] CHK-NO-SEP          EXPECT: SEP apertures tied off               TOKEN: NO_SEP_CFG
- [ ] CHK-SEP0-ERR-SLV    EXPECT: hier DECERR + poison                 TOKEN: OTP_SEP0_ERR_SLV
  Primary: smu_no_sep_configuration_test, smu_dtp_otp_sep0_err_slv_test
```

---

## Bidirectional coverage (summary)

| FEATURE-ID | Milestone | Primary test(s) | Status |
|------------|-----------|-----------------|--------|
| IF-CLK-01 / IF-PWR-01 | P1 | bring-up | enrolled |
| IF-RST-01 | P1 | smc_reset_ctrl | enrolled |
| IF-RST-03 | P2 | ic_reset multi-domain | enrolled |
| IF-AXI-01..08 | P1/P2 | fabric + filter | enrolled |
| IF-JTAG-01..09 | P1/P2 | dtp stream | enrolled |
| IF-XT-02/03/05 | P2 | xtrig / CLA | enrolled |
| IF-SMC-09 | P2 | wdt_timeout / scratch | enrolled |
| IF-CFG-01/02 | P1/P2 | no_sep / err_slv | enrolled |
| IF-RST-04 / IF-XT-04 | N/A | BLOCKED | OUT |
| SEP=1 / interop features | OUT | deferred.toml | OUT |

Every in-scope FEATURE-ID above has ≥1 CHK and ≥1 enrolled test. Orphan CHKs: none in this draft.

---

## P3 corner / G4 deepeners (same IF atoms)

```text
FEATURE-ID: IF-JTAG-02+   SPEC-REF: VPLAN §7 H1/H2          MILESTONE: P3
INTENT: JTAG2AXI corners — WSTRB neighbor, b2b DECERR→OK, abort mid-BUSY
- [ ] CHK-J2A-WSTRB-NBR   EXPECT: partial merge; neighbor intact       TOKEN: J2A_WSTRB_NEIGHBOR
- [ ] CHK-J2A-B2B         EXPECT: DECERR then immediate SUCCESS        TOKEN: J2A_B2B_OK
- [ ] CHK-J2A-ABORT       EXPECT: IR/TRST mid-BUSY; VERSION recovers   TOKEN: J2A_ABORT_RECOVER
  Primary: wstrb_partial_sticky, back_to_back_error_ok, abort_mid_op
```

```text
FEATURE-ID: IF-JTAG-03+   SPEC-REF: VPLAN §7 H4            MILESTONE: P3
INTENT: feat_ctrl incomplete OTP bits; mid-BUSY gate flip
- [ ] CHK-FEAT-PARTIAL    EXPECT: incomplete set does not land MAP     TOKEN: FEAT_PARTIAL_DENY
- [ ] CHK-FEAT-MID-OP     EXPECT: not SUCCESS+good after mid gate      TOKEN: FEAT_MID_OP_GATE
  Primary: feat_ctrl_partial_bit_corner, feat_ctrl_flip_mid_jtag2axi
```

```text
FEATURE-ID: IF-RST-03+ / IF-JTAG-05+  SPEC-REF: VPLAN §7 H5  MILESTONE: P3
INTENT: dual IC_RESET pack; stall vs IC_RESET priority; WDT double pulse
- [ ] CHK-IC-DUAL         EXPECT: both packed ovrd; no bleed; DEFAULT  TOKEN: IC_RESET_DUAL_PACK
- [ ] CHK-STALL-VS-IC     EXPECT: IC_RESET does not clear stall        TOKEN: STALL_VS_IC_RESET
- [ ] CHK-WDT-DOUBLE      EXPECT: two pulses; cold sticky; warm clear  TOKEN: WDT_DOUBLE_PULSE
  Primary: ic_reset_dual_domain, boot_stall_vs_ic_reset, wdt_scratch_double_pulse
```

```text
FEATURE-ID: IF-XT-02+ / IF-JTAG-07+  SPEC-REF: VPLAN §7 H1c/H6  MILESTONE: P3
INTENT: illegal CTM phase; CLA stop || CTM; JTAG stop OR CLA fb
- [ ] CHK-XT-ILLEGAL      EXPECT: illegal order ignored; SMC[1:0]=0    TOKEN: XT_ILLEGAL_PHASE
- [ ] CHK-CLA-CTM-CONC    EXPECT: stop_clks held through CTM           TOKEN: CLA_CTM_CONCURRENT
- [ ] CHK-STOP-OR         EXPECT: stop_clks = JTAG|CLA fb              TOKEN: CLOCK_STOP_OR
  Primary: xtrig_ctm_illegal_phase, cla_and_xtrig_concurrent, clock_stop_jtag_vs_cla_fb
```

```text
FEATURE-ID: IF-AXI/JTAG G4  SPEC-REF: VPLAN §7 H3          MILESTONE: P3
INTENT: dual-agent races — coherent winner, no silent tear
- [ ] CHK-RACE-J2A-SMN    EXPECT: final in {PAT_J,PAT_S}; agents agree TOKEN: RACE_J2A_SMN
- [ ] CHK-RACE-OTP-FAB    EXPECT: shadow == last writer; paths agree   TOKEN: RACE_OTP_FABRIC
- [ ] CHK-RACE-CTN-J2A    EXPECT: CTN + VERSION/SCRATCH both correct   TOKEN: RACE_CTN_J2A
  Primary: jtag2axi_vs_smn_same_csr_race, otp_vs_fabric_map_race, hier_ctn_vs_jtag2axi_concurrent
```

| FEATURE-ID | Milestone | Primary test(s) | Status |
|------------|-----------|-----------------|--------|
| IF-JTAG-02+ corners | P3 | H1a/H1b/H2a | enrolled |
| IF-JTAG-03+ mid/partial | P3 | H4a/H4b | enrolled |
| IF-RST-03+ / stall / WDT | P3 | H5a/b/c | enrolled |
| IF-XT / CLA stress | P3 | H1c/H6a/b | enrolled |
| G4 dual-agent | P3 | H3a/b/c | enrolled |

---

## P4 deepen + glue remainder (SEP=0)

```text
FEATURE-ID: IF-SMC-11   SPEC-REF: VPLAN P4 D1              MILESTONE: P4
INTENT: Force secure_tm_i asserts is_secure_tm_blocked_o (no pin / LOCKS claim)
- [ ] CHK-STM-FORCE       EXPECT: blocked 0→1 when Force lands           EVIDENCE: SECURE_TM_FORCE
  Primary: smc_efuse_secure_tm_force_test
  Note: SMC LOCKS has no lock[3] SECURE_TM bit and is W1S — not evidence.
```

```text
FEATURE-ID: IF-SMC-09+  SPEC-REF: VPLAN P4 D2              MILESTONE: P4
INTENT: WDOGIP0 + isolate clamp mux contrast on first-timeout pin
- [ ] CHK-WDT-CLAMP       EXPECT: isolate∧raw→pin=0; ~isolate∧raw→pin=1 EVIDENCE: WDT_FIRST_CLAMP0
  Primary: smc_wdt_ip0_isolate_clamp_test
```

```text
FEATURE-ID: IF-GLUE-01  SPEC-REF: VPLAN P4 G1–G5           MILESTONE: P4
INTENT: SEP=0 glue — macro AXIL, OCTS, SS IC_RESET, EXTEST, ATB
- [ ] CHK-MACRO-ROUTE     EXPECT: PLL/PVT/ext active + DECERR poison   EVIDENCE: MACRO_DECERR_POISON
- [ ] CHK-OCTS-ADVANCE    EXPECT: TIMER_COUNT advances after START     EVIDENCE: OCTS_COUNT_ADVANCE
- [ ] CHK-IC-SS           EXPECT: SS cold0/warm0 ovrd exclusive        EVIDENCE: IC_RESET_SS_COLD_OVRD
- [ ] CHK-BSR-EXTEST      EXPECT: EXTEST DR loopback TDO match         EVIDENCE: BSR_EXTEST_TDO_MATCH
- [ ] CHK-TEL-ATB         EXPECT: atready/afvalid handshake            EVIDENCE: TEL_ATREADY_HS
  Primary: macro_axil, octs_timer, ic_reset_ss, bsr_extest, telemetry_atb
```

| FEATURE-ID | Milestone | Primary test(s) | Status |
|------------|-----------|-----------------|--------|
| IF-SMC-11 secure_tm Force | P4 | smc_efuse_secure_tm_force | enrolled |
| IF-SMC-09+ WDT clamp | P4 | smc_wdt_ip0_isolate_clamp | enrolled |
| IF-GLUE-01 | P4 | phase4_sep0 glue ×5 | enrolled |

---

## Designer approval

| Field | Value |
|-------|-------|
| SPEC revision | `SMU_SPEC.md` + `SMU_VPLAN.md` rev 2.25 (P4 honesty pass) |
| Approver | _pending_ |
| Date | _pending_ |
| Notes | AI-drafted; human must approve check semantics before sign-off |

---

## Revision

| Ver | Date | Note |
|-----|------|------|
| 0.1 | 2026-07-15 | Initial Skill-1 draft from VPLAN IF matrix + P2 contracts |
| 0.2 | 2026-07-17 | P3 H1–H6 corner/G4 CHK map; SEP=0 program closed pending designer approval |
| 0.3 | 2026-07-20 | P4 deepen + glue CHKs (`phase4_sep0`); designer approval still pending |
| 0.4 | 2026-07-20 | P4 honesty: IF-SMC-11 blocked_o; WDT Force-raw clamp; drop LOCKS vacuity |
