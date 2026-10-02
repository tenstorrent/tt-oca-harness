# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# SMU VC SpyGlass RDC waivers for the flat SMU run (SMC, DTP and SEP elaborated).
# Child-block waivers are replayed from hw/sys/{smc,dtp,sep}/rdc under their
# instance prefix and are not repeated here.

# =====================================================================================================================
# SMU RDC waivers (flat run)
# =====================================================================================================================

waive_violation -add {SMU_SETUP_RESET_ASSERT_MISSING_sep_wdt_loop} \
    -comment {PRIMARY and its WDT-clock sync RST_WDT_N reach the SMC WDT reset synchronizer through the SEP watchdog request flop and the smu.sv inversion, arriving as "deasserted". Both consumers of the WDT reset (SMC warm reset, SEP CPU reset) are AND-ed with a PRIMARY-derived reset and so assert under PRIMARY on their own path.} \
    -filter {((ReasonInfoList:ReasonInfo:ReasonCode == "WRONG_ASSERT_VALUE") OR (ReasonInfoList:ReasonInfo:ReasonCode == "BLOCKED_ASSERT_VALUE")) AND (SeqObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_sync/u_rst_wdt_smc_sync/*") AND ((ResetInfoList:ResetInfo:ResetName == "PRIMARY_RESET_N") OR (ResetInfoList:ResetInfo:ResetName == "PRIMARY_RESET_N_SMC_CLK") OR (ResetInfoList:ResetInfo:ResetName == "RST_WDT_N"))} \
    -app { rdc } -tag { SETUP_RESET_ASSERT_MISSING } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# =====================================================================================
# RDC_CORRUPT WAIVERS
# These can only see the flop directly affected by an async-reset metastability event
# Downstream fanout may be affected and MUST BE AUDITED / RESOLVED
# =====================================================================================

waive_violation -add {SMU_RDC_CORRUPT_sep_fabric_to_smc_debug_bus} \
    -comment {SEP flops (SEP_CPU_RESET_N / SEP_RESET_N / PRIMARY / KM_COLD) tapped onto the SMC external debug-bus observation sync (u_ext_debug_bus_sync3, unreset, SMUCLK->SMUCLK). Single-bit observation lanes resolve to old/new within the chain while SEP is itself resetting; the only consumer is the DFD (trace capture, debug-armed CLA), no functional consumer.} \
    -filter {(SrcObject =~ "gen_sep.*") AND (DestObject =~ "u_smc/u_smc_base/u_ext_debug_bus_sync3/u_sync3[*]/d0nt_wrap_sync/Q") AND (RdcDestResets:DestResetInfo:ResetName == "'no-reset'") AND (ReasonInfoList:ReasonInfo:ReasonCode == "NFF_BEYOND_UDS")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_RDC_CORRUPT_jtag_dtp_stap_to_smc_dtm} \
    -comment {DTP SMC-STAP flops (trst_n_combined / tlr_reset / stap_smc_dbg_rst) into the SMC cluster DTM TAP (IDCODE CaptureChain, TAP state machine) on JTAG_TCK: TRST is chain-wide and also async-resets the DTM (JTAG_RESET = ~host trst_n), the other sources are TCK-flopped resets; 1149.1 chain bits are reloaded at Capture-DR.} \
    -filter {((RdcSourceResets:ResetName == "trst_n_combined") OR (RdcSourceResets:ResetName == "tlr_reset") OR (RdcSourceResets:ResetName == "stap_smc_dbg_rst")) AND (SrcObject =~ "u_dtp/u_jtag_intf_unit/gen_stap_smc_dbg.u_stap_smc_dbg/*") AND (DestObject =~ "u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/dtm/*") AND (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_RDC_CORRUPT_jtag_smc_dtm_to_dtp_stap} \
    -comment {SMC cluster DTM tdoReg (JTAG_RESET = the STAP host trst_n inverted in smu.sv) into the DTP SMC-STAP SIB scan_data (reset-less, JTAG_TCK): the same chain-wide TRST resets the STAP and its SIB at the same instant, and scan_data is reloaded at Capture-DR before any shift-out (same pattern as ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_stap_scan_data).} \
    -filter {(RdcSourceResets:ResetName == "JTAG_RESET") AND (SrcObject =~ "u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/dtm/*") AND (DestObject =~ "u_dtp/u_jtag_intf_unit/gen_stap_smc_dbg.u_stap_smc_dbg/*") AND (RdcDestResets:DestResetInfo:ResetName == "'no-reset'") AND (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# DTP jtag2axi -> SMC cluster fabric: cross-block twin of SMC_CPU_RDC_CORRUPT_CLUSTER_CONTAINED_SOURCE_RESET.
waive_violation -add {SMU_RDC_CORRUPT_dtp_jtag2axi_primary_into_smc_cluster} \
    -comment {DTP jtag2axi clearable-CDC controller state (PRIMARY) reaching the SMC cluster MMIO-port AXI buffer queue pointers through fabric arbitration; PRIMARY also drives the cluster reset, so the destination is reset on the same event. Same disposition as SMC_CPU_RDC_CORRUPT_CLUSTER_CONTAINED_SOURCE_RESET for a source outside u_smc.} \
    -filter {((RdcSourceResets:ResetName == "PRIMARY_RESET_N") OR (RdcSourceResets:ResetName == "PRIMARY_RESET_N_SMC_CLK")) AND (RdcDestResets:DestResetInfo:ResetName == "'no-reset'") AND (SrcObject =~ "u_dtp/u_jtag_intf_unit/u_jtag_ptap/*jtag2axi*/*") AND (DestObject =~ "u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 17-09-2026 18:15:09 }

# =============================================================================
# Warning-class dispositions
# =============================================================================

waive_violation -add {SMU_SETUP_CLOCK_UNUSED_BOUNDARY_CLKS} \
    -comment {Output-port memory-interface clocks (SMUCLK_ROM / SMUCLK_RAM* / SMUCLK_{I,D}CACHE_* / SEPCLK_PKA_*) and the SPICLK base of the GPIO SPI clocks clock no internal sequentials by construction. } \
    -filter {(Clock:ClkName =~ "SMUCLK_*") OR (Clock:ClkName =~ "SEPCLK_*") OR (Clock:ClkName == "SPICLK")} \
    -app { rdc } -tag { SETUP_CLOCK_UNUSED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Reset-tree edges that cross a block boundary, so neither block's RESET_OVERLAP class waiver owns them.
waive_violation -add {SMU_SETUP_RESET_OVERLAP_CROSS_BLOCK_TREE} \
    -comment {DTP trst_n_combined is passed through the PTAP TAP controller and the SMC STAP to smc_cpu_jtag_reset_i, where smu.sv inverts it into the active-high JTAG_RESET. SEP RST_WDT_N resets the watchdog request flop whose inverted output is a WARM_RESET_N AND-tree input. One declared reset reaching the root of another is the reset tree by construction.} \
    -filter {((SrcRstInfo:ResetName == "trst_n_combined") AND (DesRstInfo:ResetName == "JTAG_RESET")) OR ((SrcRstInfo:ResetName == "RST_WDT_N") AND (DesRstInfo:ResetName == "WARM_RESET_N"))} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { nbetik } -timestamp { 17-09-2026 00:00:00 }
