# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# SMU VC SpyGlass CDC waivers for the flat SMU run (SMC, DTP and SEP elaborated).
# Child-block waivers are replayed from hw/sys/{smc,dtp,sep}/cdc under their
# instance prefix and are not repeated here.

# =====================================================================================================================
# SMU CDC waivers (flat run)
# =====================================================================================================================

waive_violation -add {SMU_CDC_GLITCH_UNSYNC_smc_gpio_core2pad} \
    -comment {core2pad_o primary-output glitch from reconvergence of quasi-static GPIO/UART mode-control CSRs (interface_enable / uart_enable_sync / MCR.LINE_LOOPBACK) through the padring mux. Off-chip pad, no on-chip receiver; brief glitch during a mode/loopback change is tolerable. create_static does not clear it (proven in SMC). Mirrors SMC_CDC_GLITCH_UNSYNC_10758 / SMC_CDC_GLITCH_UNSYNC_13868.} \
    -filter {(GlitchDestInfo:DestObject =~ "core2pad_o*") AND (GlitchDestInfo:DestObjectType == "primary output") AND (ReasonInfoList:ReasonInfo:ReasonCode == "GLITCH_SOURCE_RECONVERGES") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_GLITCH_UNSYNC } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# DTP STAP trst_n outputs. jtag_stap_*_host_tap_ctrl_o.trst_n is driven from
# the SMC power-on reset out to external-STAP TAP reset outputs. Primary output +
# power-on reset; same IEEE 1149.1 family as the DTP block pwr_on_rst->STAP trst signoff.
waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_stap_trst_out} \
    -comment {DTP STAP trst_n primary output (jtag_stap_*_host_tap_ctrl_o.trst_n) from the power-on reset; output + IEEE 1149.1 reset, mirrors DTP block pwr_on_rst->STAP trst signoff.} \
    -filter {(DestObject =~ "jtag_stap_*trst_n") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# The SMC powergood/primary reset (REFCLK, powergood_stretcher) async-deasserts
# into DTP JTAG-TAP flops (JTAG_TCK domain) inside u_jtag_intf_unit. This is the
# exact pattern the DTP block signed off (ocah_dtp_CDC_UNSYNC_ASYNCRESET_pwr_on_rst
# _to_jtag_flops): per IEEE 1149.1 Rule 4.6.1, TRST* assertion is async to TCK and
# at power-on TCK is quiescent, so the deassertion is safe by construction.
waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_dtp_jtag} \
    -comment {SMC power-on reset async deassertion into DTP JTAG-TCK flops (u_jtag_intf_unit); IEEE 1149.1: TRST async to TCK, TCK static at power-on -> safe. Mirrors DTP block ocah_dtp_CDC_UNSYNC_ASYNCRESET_pwr_on_rst_to_jtag_flops signoff.} \
    -filter {(DestObject =~ "u_dtp/u_jtag_intf_unit/*") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# External cross-trigger inputs (xtrig_ctp_*_din_i, ck_feedthru) are synchronized
# into SMUCLK and reconverge at the DTP cross-trigger handshake (busy_d). Gray-coded
# handshake (GRAY_CHECK_IGNORED_SEQ_CONV); the reconvergence is internal to the DTP
# cross-trigger network and was signed off in the DTP block run (20 RECONV_SEQ).
waive_violation -add {SMU_CDC_COHERENCY_RECONV_SEQ_dtp_xtrig} \
    -comment {DTP cross-trigger handshake reconvergence (u_cross_trigger_network, gray-coded sync); signed off in DTP block CDC run (RECONV_SEQ).} \
    -filter {(ConvergencePoint =~ "u_dtp/u_cross_trigger_network/*") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_COHERENCY_RECONV_SEQ } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_GLITCH_CTRL_smc_cpu_dm} \
    -comment {SMC CPU Chipyard Rocket tlDM async DM/JTAG boundary (3sync chains); signed off in SMC block run (SMC_CPU_CDC_GLITCH_CTRL_*).} \
    -filter {(GlitchDestInfo:DestObject =~ "u_smc/u_smc_cpu_wrapper/*") AND ((ContainerInstance == "smu") OR (ContainerInstance =~ "u_smc*"))} \
    -app { cdc } -tag { CDC_GLITCH_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_GLITCH_CTRL_dtp} \
    -comment {DTP-internal glitch control (u_jtag_ptap / u_clock_stop_ctrl); signed off in DTP block CDC run (CDC_GLITCH_CTRL).} \
    -filter {(GlitchDestInfo:DestObject =~ "u_dtp/*") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_GLITCH_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# DTP clock-stop syncs: xtrig_clk_stop_req / SMC CLA halt -> DTP clock-stop
# and CLA-clock-stop 2-flop syncs (u_clk_stop_sync, u_cla_clock_stop_sync). Sync
# present; DTP cross-trigger / debug clock-stop control, signed off in DTP block.
waive_violation -add {SMU_CDC_UNSYNC_CTRL_dtp_clock_stop} \
    -comment {DTP clock-stop / CLA-clock-stop control syncs (u_clk_stop_sync, u_cla_clock_stop_sync) from xtrig_clk_stop_req / SMC CLA halt; recognized sync, DTP debug clock-stop path signed off in DTP block.} \
    -filter {(DestObject =~ "u_dtp/*clock_stop*") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_cpu_sep_jtag} \
    -comment {SMC power-on reset (REFCLK powergood stretcher) async assertion/deassertion into SMC CPU tlDM/dtm and SEP EL2 DMI JTAG-TCK flops via the DTP PTAP trst AND-gate; IEEE 1149.1: TRST async to TCK, TCK static at power-on -> safe. Extends SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_dtp_jtag to the CPU/SEP TCK domains that only connect flat.} \
    -filter {(SrcObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND (DestClockInfoList:DestClockInfo:ClockName =~ "JTAG*") AND ((DestObject =~ "u_smc/u_smc_cpu_wrapper/*") OR (DestObject =~ "gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/*"))} \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_smc_porst_to_jtag_tck} \
    -comment {SMC power-on reset (REFCLK powergood stretcher) used-as-data into JTAG-TCK-domain debug logic through the DTP PTAP trst AND-gate / Chipyard dmiReset reset-bypass network (trace-verified: no functional datapath). IEEE 1149.1: TRST async to TCK, TCK static at power-on -> safe. Same family as SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_dtp_jtag.} \
    -filter {(SrcObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND (DestClockInfoList:DestClockInfo:ClockName =~ "JTAG*")} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_CTRL_smc_cpu_dm} \
    -comment {SMC CPU Chipyard Rocket tlDM async DM/JTAG boundary (AsyncQueue 3sync chains, reset-bypass structures); control sources are the JTAG/debug reset network (PTAP trst, powergood stretcher, debug_reset_n CSR). Signed off in SMC block run (SMC_CPU_* DM family); IEEE 1149.1 for the TCK-domain legs.} \
    -filter {(DestObject =~ "u_smc/u_smc_cpu_wrapper/*u_digital_top/tlDM/*") AND ((SrcClockInfoList:SrcClockInfo:ClockName == "JTAG_TCK") OR (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK") OR (SrcObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") OR (SrcObject =~ "u_smc/u_smc_cpu_wrapper/u_smc_cpu_ctrl_wrap/reset_ctrl_reg_value_n0_scan.debug_reset_n*"))} \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_smc_cpu_dm} \
    -comment {SMC CPU Chipyard Rocket tlDM async DM/JTAG boundary: dmInner->dmOuter AsyncQueue legs whose qualifier check is defeated by the reset-network fan-in (see SMU_CDC_UNSYNC_CTRL_smc_cpu_dm); recognized 3sync structure, signed off in SMC block run.} \
    -filter {(DestObject =~ "u_smc/u_smc_cpu_wrapper/*u_digital_top/tlDM/*") AND ((SrcClockInfoList:SrcClockInfo:ClockName == "JTAG_TCK") OR (DestClockInfoList:DestClockInfo:ClockName == "JTAG_TCK") OR (SrcObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") OR (SrcObject =~ "u_smc/u_smc_cpu_wrapper/u_smc_cpu_ctrl_wrap/reset_ctrl_reg_value_n0_scan.debug_reset_n*"))} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_sep_dbg} \
    -comment {SMC power-on reset (REFCLK powergood stretcher = DBG_RSTB_I at SMU) async deassertion into the SEP VeeR debug-reset-domain registers and the DMI jtag-to-core synchronizers; powergood low => all clocks absent (signed-off SMC sequence), release precedes clock start and RST_NI still holds all functional sources -> no edge to race.} \
    -filter {(SrcObject =~ "u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND ((DestObject =~ "gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/veer/dbg/*") OR (DestObject =~ "gen_sep.u_sep/u_sep_cpu/u_mpc_reset_run_req_sync/*") OR (DestObject =~ "gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/i_dmi_jtag_to_core_sync/*"))} \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_sep_spi_miso} \
    -comment {SEP SPI-host MISO readback: external slave launches pad2core_i data from the SEP-generated SCK (SPICLK/SPICLK_OUT_GPIO derive from the controller's own SMUCLK bit timing); the SMUCLK shift-register capture is source-synchronous and closed by IO timing, not an async crossing. Flat-only (SEP block sees the SEPCLK-timed rsp port).} \
    -filter {(SrcObject =~ "pad2core_i*") AND (DestObject =~ "gen_sep.u_sep/u_sep_io/u_sep_ot_spi_wrap/*") AND ((SrcClockInfoList:SrcClockInfo:ClockName =~ "SPICLK*") OR (SrcClockInfoList:SrcClockInfo:ClockName == "ck_feedthru"))} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_COHERENCY_MULTI_SYNC_debug_observation} \
    -comment {ext_trng_irq_i / the SEP WDT reset request synced on its functional path and again by the SMC external debug-bus observation sync (u_ext_debug_bus_sync3, DFD capture-only); single-bit independent lanes with no coherency requirement.} \
    -filter {(NoConvNoSrcControlPathList:NoConvControlPathInfo:SyncOutput =~ "u_smc/u_smc_base/u_ext_debug_bus_sync3/*") AND (ContainerInstance == "smu")} \
    -app { cdc } -tag { CDC_COHERENCY_MULTI_SYNC } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Same source set as SEP_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_5975; the flat run reports the convergence at the
# VeeR LSU address adder (lsu_lsc_ctl/lsadder rs1 operand) instead of the tlu mstatus enable. DMI rden/wren syncs
# (JTAG_TCK -> SMUCLK) and PIC gateway syncs (ck_feedthru -> SMUCLK) are independent single-bit events that reach the
# operand only through architectural state; arrival order is functionally arbitrary.
waive_violation -add {SMU_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_sep_dmi_pic} \
    -comment {Independent DMI op-bit and PIC gateway synchronizer outputs converge at the VeeR LSU address adder rs1 operand through architectural state; independent events, arrival order arbitrary (same disposition as SEP_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_5975).} \
    -filter {(ConvergencePoint =~ "gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/veer/*") AND (ReasonInfoList:ReasonInfo:ReasonCode == "ASYNC_SRC_CONV") AND (ConvControlPathList:ConvergingControlPath:SyncOutput =~ "gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/i_dmi_jtag_to_core_sync/*")} \
    -app { cdc } -tag { CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ } -user { nbetik } -timestamp { 17-09-2026 11:44:06 }

# =============================================================================
# Warning-class dispositions
# =============================================================================

waive_violation -add {SMU_SETUP_CLOCK_UNUSED_BOUNDARY_CLKS} \
    -comment {Output-port memory-interface clocks (SMUCLK_ROM / SMUCLK_RAM* / SMUCLK_{I,D}CACHE_* / SEPCLK_PKA_*) and the SPICLK base of the GPIO SPI clocks clock no internal sequentials by construction. SEP_WDT_CLK clocks only the SEP watchdog, which the no-SEP configuration does not elaborate.} \
    -filter {(Clock:ClkName =~ "SMUCLK_*") OR (Clock:ClkName =~ "SEPCLK_*") OR (Clock:ClkName == "SPICLK") OR (Clock:ClkName == "SEP_WDT_CLK")} \
    -app { cdc } -tag { SETUP_CLOCK_UNUSED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Reset-tree edges that cross a block boundary, so neither block's RESET_OVERLAP class waiver owns them.
waive_violation -add {SMU_SETUP_RESET_OVERLAP_CROSS_BLOCK_TREE} \
    -comment {DTP trst_n_combined is passed through the PTAP TAP controller and the SMC STAP to smc_cpu_jtag_reset_i, where smu.sv inverts it into the active-high JTAG_RESET. SEP RST_WDT_N resets the watchdog request flop whose inverted output is a WARM_RESET_N AND-tree input. One declared reset reaching the root of another is the reset tree by construction.} \
    -filter {((SrcRstInfo:ResetName == "trst_n_combined") AND (DesRstInfo:ResetName == "JTAG_RESET")) OR ((SrcRstInfo:ResetName == "RST_WDT_N") AND (DesRstInfo:ResetName == "WARM_RESET_N"))} \
    -app { cdc } -tag { SETUP_RESET_OVERLAP } -user { nbetik } -timestamp { 17-09-2026 00:00:00 }
waive_violation -add {SMU_SETUP_OUTPUT_MULTICLOCK_DRIVER_avs_pad} -comment {core2pad_o[50] is the AVS clock-output pad: its pad-function mux selects between the SMUCLK GPIO data register and the AVS divider clock, so the port is in the fan-out of both domains by design. The select is a quasi-static DATA_CTRL field; the SMC block run times the pad on the AVS GPIO clocks.} -filter {(PortName == "core2pad_o[50]") AND (ClockedInstanceList:ClockedInstance:InstanceName =~ "u_smc/u_smc_peripherals/u_smc_padring/gen_gpio_intf[50].u_gpio_interface/u_gpio_intf_reg/field_storage*") AND (ClockedInstanceList:ClockedInstance:ClockName =~ "u_smc/u_smc_peripherals/u_avsbus_controller/u_clk_div/clk_o")} -app { cdc } -tag { SETUP_OUTPUT_MULTICLOCK_DRIVER } -user { nbetik } -timestamp { 02-10-2026 12:45:00 }
