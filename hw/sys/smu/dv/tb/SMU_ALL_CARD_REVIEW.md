# SMU_ALL Card Mechanics Review — P2 (AMENDMENT DIFF — cards artifact_revision 12)

**Your task:** approve card mechanics for the amended `SMU_ALL_008` record only. Cards 001–007 are citation bumps (plan_revision 12) with unchanged steps/checkers — keep prior approval.

## REVIEW-FOCUS

- **NEW on SMU_ALL_008 r12:** steps/checkers for SMC-BOOT.S1–S3, SEP-BOOT.S1–S2, SMC-AXI-LITE-SHIMS.S1–S2, DTP-IJTAG-SCAN.S1–S2, INT-FUSE-SENSE-BOOT, INT-XBAR-APERTURE-INTEROP.
- Interaction checkers list all joint features in `proves`.
- CHK-NONVAC / CHK-TIMEOUT-PATHS rebuilt for expanded step fence.
- No Force/deposit; 008 remains unimplemented / platform-blocked.

## SMU_ALL_001 — smu_wrapper_elaboration_sep_rtl_test (r12, approved)

- **OWNS:** SMU compose presence (SEP=1), SEP=1 elaboration (xbar + lc_state_o), SMU clk/rst port connectivity (non-powergood-POR)
- **Description triad:** producer=Initiating agent for SMU composition / SEP=1 elaboration / top ports at SMU… | transport=SMU integration boundary (SMC/SEP/DTP/xbar/mailbox/DTP contr… | consumer=(see OWNS)
- **Steps:** 8 · **Checkers:** 8

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMU-COMPOSE-BLOCKS.S1 |
| S3 | SMU-COMPOSE-BLOCKS.S2 |
| S4 | SMU-COMPOSE-BLOCKS.S3 |
| S5 | SMU-PORT-CLK-RST.S1 |
| S6 | SMU-PORT-CLK-RST.S3 |
| S7 | SMU-SEP-PARAM.S1 |
| S8 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMU-COMPOSE-BLOCKS-S1 | SMU-COMPOSE-BLOCKS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-COMPOSE-BLOCKS-S2 | SMU-COMPOSE-BLOCKS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-COMPOSE-BLOCKS-S3 | SMU-COMPOSE-BLOCKS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-PORT-CLK-RST-S1 | SMU-PORT-CLK-RST | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-PORT-CLK-RST-S3 | SMU-PORT-CLK-RST | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-SEP-PARAM-S1 | SMU-SEP-PARAM | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_002 — smu_axi_external_port_connectivity_test (r12, approved)

- **OWNS:** SEP=0 external SMN AXI inbound→SMC aperture via direct IW converters; SEP=0 elaboration (direct SMC↔external ID converters; non-OTP-error)
- **Description triad:** producer=Initiating agent for SMU SEP=0 external AXI inbound / no-SEP converters at SMU… | transport=SMU integration boundary (SMC/SEP/DTP/xbar as elaborated by … | consumer=(see OWNS)
- **Steps:** 4 · **Checkers:** 4

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMU-PORT-SMN-AXI.S1 |
| S3 | SMU-SEP-PARAM.S2 |
| S4 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMU-PORT-SMN-AXI-S1 | SMU-PORT-SMN-AXI | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-SEP-PARAM-S2 | SMU-SEP-PARAM | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_003 — smu_smc_smoke_test (r12, approved)

- **OWNS:** SMC dual-network AXI4-Lite LP subordinates and 64-bit data width (SMC-FAB-DUAL-NET.S2/S3); excludes fabric in-ports, decode apertures, and PWRGOOD leave-TLR owned by SMU_ALL_008 after Option-B re-home
- **Description triad:** producer=Initiating agent for SMC fabric dual-network (hierarchical) at SMU… | transport=SMU integration boundary (SMC fabric hierarchical observatio… | consumer=(see OWNS)
- **Steps:** 4 · **Checkers:** 4

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMC-FAB-DUAL-NET.S2 |
| S3 | SMC-FAB-DUAL-NET.S3 |
| S4 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMC-FAB-DUAL-NET-S2 | SMC-FAB-DUAL-NET | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-FAB-DUAL-NET-S3 | SMC-FAB-DUAL-NET | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_004 — smc_mailbox_int_test (r12, approved)

- **OWNS:** SMC external mailbox interrupt port width (32-bit); excludes LIVE channel traffic, filter-gated MMIO, and SEP-peer mailbox paths
- **Description triad:** producer=Initiating agent for SMC external mailbox IRQ width (SEP=0 passive) at SMU… | transport=SMU integration boundary (ext_mailbox_interrupts[31:0])… | consumer=(see OWNS)
- **Steps:** 3 · **Checkers:** 3

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMC-MBX-IRQ-EXT.S2 |
| S3 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMC-MBX-IRQ-EXT-S2 | SMC-MBX-IRQ-EXT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_005 — smu_dtp_jtag_smoke_test (r12, approved)

- **OWNS:** DTP PTAP IDCODE/BYPASS/TRST (DTP-JTAG-PTAP.S1/S2/S3); excludes JTAG2AXI/OTP/STAP paths gated by feat_ctrl or requiring SEP=1 / driveable wrapper JTAG
- **Description triad:** producer=Initiating agent for DTP PTAP JTAG (SEP=0) at SMU… | transport=SMU integration boundary (DTP PTAP JTAG)… | consumer=(see OWNS)
- **Steps:** 5 · **Checkers:** 5

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | DTP-JTAG-PTAP.S1 |
| S3 | DTP-JTAG-PTAP.S2 |
| S4 | DTP-JTAG-PTAP.S3 |
| S5 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-DTP-JTAG-PTAP-S1 | DTP-JTAG-PTAP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-JTAG-PTAP-S2 | DTP-JTAG-PTAP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-JTAG-PTAP-S3 | DTP-JTAG-PTAP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_006 — smu_clock_stop_coordination_test (r12, approved)

- **OWNS:** DTP boot-stall (S1/S2), IC-reset SMC+clear (S1/S3), clock-stop aggregation (S1/S2/S3); excludes feat-gate and feat_ctrl x JTAG2AXI interaction gated by feat_ctrl/SEP=1
- **Description triad:** producer=Initiating agent for DTP boot-stall/IC-reset/clkstop (SEP=0) at SMU… | transport=SMU integration boundary (DTP JTAG + xtrig)… | consumer=(see OWNS)
- **Steps:** 9 · **Checkers:** 9

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | DTP-BOOT-STALL.S1 |
| S3 | DTP-BOOT-STALL.S2 |
| S4 | DTP-IC-RESET.S1 |
| S5 | DTP-IC-RESET.S3 |
| S6 | DTP-CLKSTOP-AGG.S1 |
| S7 | DTP-CLKSTOP-AGG.S2 |
| S8 | DTP-CLKSTOP-AGG.S3 |
| S9 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-DTP-BOOT-STALL-S1 | DTP-BOOT-STALL | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-BOOT-STALL-S2 | DTP-BOOT-STALL | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-IC-RESET-S1 | DTP-IC-RESET | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-IC-RESET-S3 | DTP-IC-RESET | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-CLKSTOP-AGG-S1 | DTP-CLKSTOP-AGG | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-CLKSTOP-AGG-S2 | DTP-CLKSTOP-AGG | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-CLKSTOP-AGG-S3 | DTP-CLKSTOP-AGG | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_007 — smu_sep_smoke_test (r12, approved)

- **OWNS:** SMC primary reset export (SMC-RST-PRIMARY-EXPORT.S1/S2) and DTP CTM xtrig S2/S3; excludes SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias, CTM.S1, CTP, DTP CSR, and other #3582/harness-gated paths
- **Description triad:** producer=Initiating agent for SMC reset export / DTP CTM (SEP=0) at SMU… | transport=SMU integration boundary (reset export + CTM xtrig)… | consumer=(see OWNS)
- **Steps:** 6 · **Checkers:** 6

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMC-RST-PRIMARY-EXPORT.S1 |
| S3 | SMC-RST-PRIMARY-EXPORT.S2 |
| S4 | DTP-XTRIG-CTM.S2 |
| S5 | DTP-XTRIG-CTM.S3 |
| S6 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMC-RST-PRIMARY-EXPORT-S1 | SMC-RST-PRIMARY-EXPORT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-RST-PRIMARY-EXPORT-S2 | SMC-RST-PRIMARY-EXPORT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-XTRIG-CTM-S2 | DTP-XTRIG-CTM | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-XTRIG-CTM-S3 | DTP-XTRIG-CTM | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

## SMU_ALL_008 **CHANGED** — smu_axi_crossbar_error_handling_test (r12, candidate)

- **OWNS:** SMU 3x3 xbar connectivity matrix, SMN AXI outbound default, SEP aperture inbound (ext_in→sep_in), SMC fabric in-ports sys/jtag/sep (SMC-FAB-IN-PORTS.S1/S2/S3), SMC decode apertures (SMC-DECODE-APERTURE.S1/S3), SMC powergood PTAP leave-TLR (SMC-PWRGOOD-DTP-POR.S2), ID conversion (SEP path), unmapped DECERR (ext_in), SMC↔SEP mailbox peer outbound (SMC-MBX-CHANNELS.S1), SEP→SMC challenge IRQ (SMU-MBX-CHALLENGE.S2), SEP mailbox IRQ 1-core vector (SEP-MBX-IRQ-SMC.S2), SMC-local mailbox inbound/decode (SMC-MBX-CHANNELS.S2/S3) and external mailbox IRQ LIVE bits (SMC-MBX-IRQ-EXT.S1) gated on SYS_IN filter / feat_ctrl / JTAG2AXI; excludes SEP=0 SMC inbound owned by SMU_ALL_002, hierarchical dual-net owned by SMU_ALL_003, and passive EXT width DECODE owned by SMU_ALL_004; also DTP JTAG2AXI-to-SMC, OTP AXIL, and STAP SMC/SEP selection re-homed from SMU_ALL_005 (feat_ctrl / SEP=1 / wrapper JTAG blockers); also DTP feat-gate and feat_ctrl x DTP JTAG2AXI interaction re-homed from SMU_ALL_006; also SEP sysif/LC/SEC_DIS/mem/fuse/WDT/alias, CTM.S1, CTP, DTP CSR, FAB-OUT-SMN, INT-CLKSTOP, and related residual paths re-homed from SMU_ALL_007; also SMC-BOOT.S1/S2/S3, SEP-BOOT.S1/S2, SMC-AXI-LITE-SHIMS.S1/S2, DTP-IJTAG-SCAN.S1/S2, INT-FUSE-SENSE-BOOT, INT-XBAR-APERTURE-INTEROP re-homed from reverse_diff CONFIRMED-OMISSION amend (platform-gated; not new runnable mid-gate cards)
- **Description triad:** producer=Initiating agent for SMU AXI/SMN crossbar + SMC fabric + SEP-peer mailbox + boot… | transport=SMU integration boundary (SMC/SEP/DTP/xbar as elaborated by … | consumer=(see OWNS)
- **Steps:** 66 · **Checkers:** 66

| Step | derived_from |
|---|---|
| S1 | (setup/timeout) |
| S2 | SMU-PORT-SMN-AXI.S2 |
| S3 | SMU-PORT-SMN-AXI.S4 |
| S4 | SMC-FAB-IN-PORTS.S3 |
| S5 | SMU-XBAR-CONNECT.S1 |
| S6 | SMU-XBAR-CONNECT.S2 |
| S7 | SMU-XBAR-CONNECT.S3 |
| S8 | SMU-XBAR-ID-CONV.S2 |
| S9 | SMU-XBAR-UNMAPPED.S1 |
| S10 | SMU-XBAR-UNMAPPED.S2 |
| S11 | SMC-FAB-IN-PORTS.S1 |
| S12 | SMC-FAB-IN-PORTS.S2 |
| S13 | SMC-DECODE-APERTURE.S1 |
| S14 | SMC-DECODE-APERTURE.S3 |
| S15 | SMC-PWRGOOD-DTP-POR.S2 |
| S16 | SMC-MBX-CHANNELS.S1 |
| S17 | SMU-MBX-CHALLENGE.S2 |
| S18 | SEP-MBX-IRQ-SMC.S2 |
| S19 | SMC-MBX-CHANNELS.S2 |
| S20 | SMC-MBX-CHANNELS.S3 |
| S21 | SMC-MBX-IRQ-EXT.S1 |
| S22 | DTP-JTAG2AXI-SMC.S1 |
| S23 | DTP-JTAG2AXI-SMC.S2 |
| S24 | DTP-OTP-AXIL.S1 |
| S25 | DTP-OTP-AXIL.S2 |
| S26 | DTP-STAP-SMC-SEP.S1 |
| S27 | DTP-STAP-SMC-SEP.S2 |
| S28 | DTP-STAP-SMC-SEP.S3 |
| S29 | DTP-FEAT-GATE.S1 |
| S30 | DTP-FEAT-GATE.S2 |
| S31 | DTP-FEAT-GATE.S3 |
| S32 | INT-FEAT-CTRL-DTP-GATE |
| S33 | SEP-SYSIF-SMU-XBAR.S2 |
| S34 | SEP-SYSIF-SMU-XBAR.S3 |
| S35 | SEP-LC-FEAT-EXPORT.S1 |
| S36 | SEP-LC-FEAT-EXPORT.S2 |
| S37 | SEP-LC-FEAT-EXPORT.S3 |
| S38 | SEP-SEC-DIS.S1 |
| S39 | SEP-SEC-DIS.S2 |
| S40 | SMC-FAB-OUT-SMN.S1 |
| S41 | SMC-DTP-CSR.S1 |
| S42 | SMC-DTP-CSR.S2 |
| S43 | DTP-XTRIG-CTM.S1 |
| S44 | DTP-XTRIG-CTP.S1 |
| S45 | INT-CLKSTOP-SMC-CLA |
| S46 | SEP-MEM-BOUND-PASSTHROUGH.S1 |
| S47 | SEP-MEM-BOUND-PASSTHROUGH.S2 |
| S48 | SEP-FUSE-SENSE-HS.S1 |
| S49 | SEP-FUSE-SENSE-HS.S2 |
| S50 | SEP-WDT-RST-SMC.S1 |
| S51 | SEP-WDT-RST-SMC.S2 |
| S52 | INT-ALIAS-VS-XBAR-SMC |
| S53 | SMU-SEP-SMC-ALIAS.S1 |
| S54 | SMU-SEP-SMC-ALIAS.S3 |
| S55 | SMC-BOOT.S1 |
| S56 | SMC-BOOT.S2 |
| S57 | SMC-BOOT.S3 |
| S58 | SEP-BOOT.S1 |
| S59 | SEP-BOOT.S2 |
| S60 | SMC-AXI-LITE-SHIMS.S1 |
| S61 | SMC-AXI-LITE-SHIMS.S2 |
| S62 | DTP-IJTAG-SCAN.S1 |
| S63 | DTP-IJTAG-SCAN.S2 |
| S64 | INT-FUSE-SENSE-BOOT |
| S65 | INT-XBAR-APERTURE-INTEROP |
| S66 | (setup/timeout) |

| Checker | Proves | How it can fail |
|---|---|---|
| CHK-SMU-PORT-SMN-AXI-S2 | SMU-PORT-SMN-AXI | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-PORT-SMN-AXI-S4 | SMU-PORT-SMN-AXI | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-FAB-IN-PORTS-S3 | SMC-FAB-IN-PORTS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-CONNECT-S1 | SMU-XBAR-CONNECT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-CONNECT-S2 | SMU-XBAR-CONNECT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-CONNECT-S3 | SMU-XBAR-CONNECT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-ID-CONV-S2 | SMU-XBAR-ID-CONV | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-UNMAPPED-S1 | SMU-XBAR-UNMAPPED | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-XBAR-UNMAPPED-S2 | SMU-XBAR-UNMAPPED | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-FAB-IN-PORTS-S1 | SMC-FAB-IN-PORTS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-FAB-IN-PORTS-S2 | SMC-FAB-IN-PORTS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-DECODE-APERTURE-S1 | SMC-DECODE-APERTURE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-DECODE-APERTURE-S3 | SMC-DECODE-APERTURE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-PWRGOOD-DTP-POR-S2 | SMC-PWRGOOD-DTP-POR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-MBX-CHANNELS-S1 | SMC-MBX-CHANNELS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-MBX-CHALLENGE-S2 | SMU-MBX-CHALLENGE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-MBX-IRQ-SMC-S2 | SEP-MBX-IRQ-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-MBX-CHANNELS-S2 | SMC-MBX-CHANNELS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-MBX-CHANNELS-S3 | SMC-MBX-CHANNELS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-MBX-IRQ-EXT-S1 | SMC-MBX-IRQ-EXT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-JTAG2AXI-SMC-S1 | DTP-JTAG2AXI-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-JTAG2AXI-SMC-S2 | DTP-JTAG2AXI-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-OTP-AXIL-S1 | DTP-OTP-AXIL | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-OTP-AXIL-S2 | DTP-OTP-AXIL | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-STAP-SMC-SEP-S1 | DTP-STAP-SMC-SEP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-STAP-SMC-SEP-S2 | DTP-STAP-SMC-SEP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-STAP-SMC-SEP-S3 | DTP-STAP-SMC-SEP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-FEAT-GATE-S1 | DTP-FEAT-GATE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-FEAT-GATE-S2 | DTP-FEAT-GATE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-FEAT-GATE-S3 | DTP-FEAT-GATE | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-INT-FEAT-CTRL-DTP-GATE | SEP-LC-FEAT-EXPORT, DTP-FEAT-GATE, DTP-JTAG2AXI-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-SYSIF-SMU-XBAR-S2 | SEP-SYSIF-SMU-XBAR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-SYSIF-SMU-XBAR-S3 | SEP-SYSIF-SMU-XBAR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-LC-FEAT-EXPORT-S1 | SEP-LC-FEAT-EXPORT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-LC-FEAT-EXPORT-S2 | SEP-LC-FEAT-EXPORT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-LC-FEAT-EXPORT-S3 | SEP-LC-FEAT-EXPORT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-SEC-DIS-S1 | SEP-SEC-DIS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-SEC-DIS-S2 | SEP-SEC-DIS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-FAB-OUT-SMN-S1 | SMC-FAB-OUT-SMN | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-DTP-CSR-S1 | SMC-DTP-CSR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-DTP-CSR-S2 | SMC-DTP-CSR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-XTRIG-CTM-S1 | DTP-XTRIG-CTM | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-XTRIG-CTP-S1 | DTP-XTRIG-CTP | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-INT-CLKSTOP-SMC-CLA | DTP-CLKSTOP-AGG, SMC-DTP-CSR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-MEM-BOUND-PASSTHROUGH-S1 | SEP-MEM-BOUND-PASSTHROUGH | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-MEM-BOUND-PASSTHROUGH-S2 | SEP-MEM-BOUND-PASSTHROUGH | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-FUSE-SENSE-HS-S1 | SEP-FUSE-SENSE-HS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-FUSE-SENSE-HS-S2 | SEP-FUSE-SENSE-HS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-WDT-RST-SMC-S1 | SEP-WDT-RST-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-WDT-RST-SMC-S2 | SEP-WDT-RST-SMC | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-INT-ALIAS-VS-XBAR-SMC | SMU-SEP-SMC-ALIAS, SMU-XBAR-CONNECT, SEP-SYSIF-SMU-XBAR | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-SEP-SMC-ALIAS-S1 | SMU-SEP-SMC-ALIAS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMU-SEP-SMC-ALIAS-S3 | SMU-SEP-SMC-ALIAS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-BOOT-S1 | SMC-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-BOOT-S2 | SMC-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-BOOT-S3 | SMC-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-BOOT-S1 | SEP-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SEP-BOOT-S2 | SEP-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-AXI-LITE-SHIMS-S1 | SMC-AXI-LITE-SHIMS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-SMC-AXI-LITE-SHIMS-S2 | SMC-AXI-LITE-SHIMS | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-IJTAG-SCAN-S1 | DTP-IJTAG-SCAN | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-DTP-IJTAG-SCAN-S2 | DTP-IJTAG-SCAN | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-INT-FUSE-SENSE-BOOT | SEP-FUSE-SENSE-HS, SMC-BOOT, SEP-BOOT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-INT-XBAR-APERTURE-INTEROP | SMU-XBAR-APERTURE, SMU-MBX-CHALLENGE, SMU-XBAR-CONNECT | missing evidence; X/Z; wrong order; timeout without last-state; contradicts SPEC |
| CHK-NONVAC | (integrity) | pass with any term missing/out of order or progress substituted for PASS |
| CHK-TIMEOUT-PATHS | (integrity) | unbounded/ignored timeout or missing bound/path/diagnostic |

---
*Appendix: rendered from SMU_ALL_VPLAN_DETAIL.md @ candidate artifact_revision 12, content_sha256 3b8c7f8df7e5c18f8b94893a7df0efcd09be2653cb379d7cbcd35bdfa98e580a, plan_revision 12, run dv_vplan_gen-SMU_ALL-P2-20260805T074000+0800-amend-reverse-omission.*
