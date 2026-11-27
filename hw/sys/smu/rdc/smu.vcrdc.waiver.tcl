# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# SMU VC SpyGlass RDC waivers for the flat SMU run (SMC, DTP and SEP elaborated).
# Child-block waivers are replayed from hw/sys/{smc,dtp,sep}/rdc under their
# instance prefix and are not repeated here.

# --- hierarchy-reuse tokens -------------------------------------------------------
# ${PREFIX} re-anchors hierarchical filter fields at the parent instance path. A parent
# run that replays this block predefines PREFIX and apply_prefix before sourcing this
# file; in the block's own run PREFIX is "". ${BLOCKINST} is the containing instance of a
# block-top violation (the design name here, the instance path at the parent).
if { ![info exists PREFIX] } { set PREFIX "" }
if { [info procs apply_prefix] eq "" } {
    proc apply_prefix { filter } {
        set out [string map [list {${PREFIX}} $::PREFIX] $filter]
        if { $::PREFIX eq "" } {
            set bi $::env(DESIGN_NAME)
        } else {
            set bi [string trimright $::PREFIX "/."]
        }
        set out [string map [list {${BLOCKINST}} $bi] $out]
        return $out
    }
}
# ${MODPREFIX} is the module-name prefix of a design whose modules are renamed
# <prefix>_<name> ("" otherwise); apply_modprefix substitutes it in Module filters and
# is independent of apply_prefix, which a parent run may replace.
if { ![info exists ::MODPREFIX] } { set ::MODPREFIX "" }
if { [info procs apply_modprefix] eq "" } {
    proc apply_modprefix { filter } {
        return [string map [list {${MODPREFIX}} $::MODPREFIX] $filter]
    }
}
# ----------------------------------------------------------------------------------

# =====================================================================================================================
# SMU RDC waivers (flat run)
# =====================================================================================================================

waive_violation -add {SMU_SETUP_RESET_ASSERT_MISSING_sep_wdt_loop} \
    -comment {PRIMARY and the SEP watchdog timer resets (SEP_WDT_RESET_N and its WDT-clock sync RST_WDT_AON_CLK_N) reset the SEP watchdog request flop, whose output smu.sv inverts into rst_ext_wdt_ni. Asserting them clears that request, so they reach the reset pin of the SMC watchdog stretcher and synchronizer (wdt_reset_n) with the deasserted value by design: a watchdog request is cleared by the reset it causes, and the stretcher is reset only by the requests.} \
    -filter [apply_modprefix [apply_prefix {((ReasonInfoList:ReasonInfo:ReasonCode == "WRONG_ASSERT_VALUE") OR (ReasonInfoList:ReasonInfo:ReasonCode == "BLOCKED_ASSERT_VALUE")) AND ((SeqObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_sync/u_rst_wdt_smc_sync/*") OR (SeqObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_wdt_reset_stretcher_n0_scan/*")) AND ((ResetInfoList:ResetInfo:ResetName == "PRIMARY_RESET_N") OR (ResetInfoList:ResetInfo:ResetName == "PRIMARY_RESET_N_SMC_CLK") OR (ResetInfoList:ResetInfo:ResetName == "SEP_WDT_RESET_N") OR (ResetInfoList:ResetInfo:ResetName == "RST_WDT_AON_CLK_N"))}]] \
    -app { rdc } -tag { SETUP_RESET_ASSERT_MISSING } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# =====================================================================================
# RDC_CORRUPT WAIVERS
# These can only see the flop directly affected by an async-reset metastability event
# Downstream fanout may be affected and MUST BE AUDITED / RESOLVED
# =====================================================================================

waive_violation -add {SMU_RDC_CORRUPT_jtag_dtp_stap_to_smc_dtm} \
    -comment {DTP SMC-STAP flops (trst_n_combined / tlr_reset / stap_smc_dbg_rst) into the SMC cluster DTM TAP (IDCODE CaptureChain, TAP state machine) on JTAG_TCK: TRST is chain-wide and also async-resets the DTM (JTAG_RESET = ~host trst_n), the other sources are TCK-flopped resets; 1149.1 chain bits are reloaded at Capture-DR.} \
    -filter [apply_modprefix [apply_prefix {((RdcSourceResets:ResetName == "trst_n_combined") OR (RdcSourceResets:ResetName == "tlr_reset") OR (RdcSourceResets:ResetName == "stap_smc_dbg_rst")) AND (SrcObject =~ "${PREFIX}u_dtp/u_jtag_intf_unit/gen_stap_smc_dbg.u_stap_smc_dbg/*") AND (DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/dtm/*") AND (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK")}]] \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_RDC_CORRUPT_jtag_smc_dtm_to_dtp_stap} \
    -comment {SMC cluster DTM tdoReg (JTAG_RESET = the STAP host trst_n inverted in smu.sv) into the DTP SMC-STAP SIB scan_data (reset-less, JTAG_TCK): the same chain-wide TRST resets the STAP and its SIB at the same instant, and scan_data is reloaded at Capture-DR before any shift-out (same pattern as ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_stap_scan_data).} \
    -filter [apply_modprefix [apply_prefix {(RdcSourceResets:ResetName == "JTAG_RESET") AND (SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/dtm/*") AND (DestObject =~ "${PREFIX}u_dtp/u_jtag_intf_unit/gen_stap_smc_dbg.u_stap_smc_dbg/*") AND ((RdcDestResets:DestResetInfo:ResetName == "'no-reset'") OR (RdcDestResets:DestResetInfo:ResetName == "trst_n_combined") OR (RdcDestResets:DestResetInfo:ResetName == "stap_smc_dbg_rst")) AND (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK")}]] \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# =============================================================================
# Warning-class dispositions
# =============================================================================

waive_violation -add {SMU_SETUP_CLOCK_UNUSED_BOUNDARY_CLKS} \
    -comment {Output-port memory-interface clocks (SMUCLK_ROM / SMUCLK_RAM* / SMUCLK_{I,D}CACHE_* / SEPCLK_PKA_* / PERIPHERALCLK_I3C_*) and the SPICLK base of the GPIO SPI clocks clock no internal sequentials by construction. SEP_WDT_CLK clocks only the SEP watchdog, which the no-SEP configuration does not elaborate.} \
    -filter [apply_modprefix [apply_prefix {(Clock:ClkName =~ "SMUCLK_*") OR (Clock:ClkName =~ "SEPCLK_*") OR (Clock:ClkName =~ "PERIPHERALCLK_I3C_*") OR (Clock:ClkName == "SPICLK") OR (Clock:ClkName == "SEP_WDT_CLK")}]] \
    -app { rdc } -tag { SETUP_CLOCK_UNUSED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Reset-tree edges that cross a block boundary, so neither block's RESET_OVERLAP class waiver owns them.
waive_violation -add {SMU_SETUP_RESET_OVERLAP_CROSS_BLOCK_TREE} \
    -comment {DTP trst_n_combined is passed through the PTAP TAP controller and the SMC STAP to smc_cpu_jtag_reset_i, where smu.sv inverts it into the active-high JTAG_RESET. One declared reset reaching the root of another is the reset tree by construction.} \
    -filter [apply_modprefix [apply_prefix {(SrcRstInfo:ResetName == "trst_n_combined") AND (DesRstInfo:ResetName == "JTAG_RESET")}]] \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { nbetik } -timestamp { 17-09-2026 00:00:00 }
