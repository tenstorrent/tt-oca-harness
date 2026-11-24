# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# SMU VC SpyGlass CDC waivers for the flat SMU run (SMC, DTP and SEP elaborated).
# Child-block waivers are replayed from hw/sys/{smc,dtp,sep}/cdc under their
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
# SMU CDC waivers (flat run)
# =====================================================================================================================

waive_violation -add {SMU_CDC_GLITCH_UNSYNC_smc_gpio_core2pad} \
    -comment {core2pad_o primary-output reconvergence in which every source (-exact_match) is a pad-function select: GPIO DATA_CTRL.interface_enable / lsio_disable, DATA_CTRL_ENABLE.use_reg_core2pad, the synchronized UART enable, or the chiplet_is_primary_i strap. A glitch can occur only while software changes which function owns a pad, when that pad output is changing owner anyway; no on-chip logic receives these outputs.} \
    -filter [apply_modprefix [apply_prefix {(GlitchDestInfo:DestObject =~ "${PREFIX}core2pad_o*") AND (GlitchDestInfo:DestObjectType == "primary output") AND (ReasonInfoList:ReasonInfo:ReasonCode == "GLITCH_SOURCE_RECONVERGES") AND ((GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_padring/gen_gpio_intf[*].u_gpio_interface/u_gpio_intf_reg/field_storage.DATA_CTRL.interface_enable.value/Q") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_padring/gen_gpio_intf[*].u_gpio_interface/u_gpio_intf_reg/field_storage.DATA_CTRL.lsio_disable.value/Q") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_padring/gen_gpio_intf[*].u_gpio_interface/u_gpio_intf_reg/field_storage.DATA_CTRL_ENABLE.use_reg_core2pad.value/Q") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_peripherals_cdc/gen_sync3.u_uart_enable_sync/*") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject == "${PREFIX}chiplet_is_primary_i")) AND (ContainerInstance == "${BLOCKINST}")}]] \
    -exact_match {GlitchSrcInfoList:GlitchSrcInfo:SrcObject} -app { cdc } -tag { CDC_GLITCH_UNSYNC } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# DTP STAP trst_n outputs. jtag_stap_*_host_tap_ctrl_o.trst_n is driven from
# the SMC power-on reset out to external-STAP TAP reset outputs. Primary output +
# power-on reset; same IEEE 1149.1 family as the DTP block pwr_on_rst->STAP trst signoff.
waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_stap_trst_out} \
    -comment {DTP STAP trst_n primary output (jtag_stap_*_host_tap_ctrl_o.trst_n) from the power-on reset; output + IEEE 1149.1 reset, mirrors DTP block pwr_on_rst->STAP trst signoff.} \
    -filter [apply_modprefix [apply_prefix {(DestObject =~ "${PREFIX}jtag_stap_*trst_n") AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# The SMC powergood/primary reset (REFCLK, powergood_stretcher) async-deasserts
# into DTP JTAG-TAP flops (JTAG_TCK domain) inside u_jtag_intf_unit. This is the
# same pattern as ocah_dtp_CDC_UNSYNC_ASYNCRESET_pwr_on_rst_to_jtag_flops.
waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_dtp_jtag} \
    -comment {SMC power-on reset async deassertion into DTP JTAG-TCK flops (u_jtag_intf_unit). The TAP leaves Test-Logic-Reset only when TMS sequences it out (IEEE 1149.1 requires a TMS pull-up), and the other TCK-domain registers update only in TAP data-register states or on DMI requests issued from them, so on the edges around reset removal every destination's next state equals its reset value and the race cannot change state.} \
    -filter [apply_modprefix [apply_prefix {(DestObject =~ "${PREFIX}u_dtp/u_jtag_intf_unit/*") AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# External cross-trigger inputs (xtrig_ctp_*_din_i, ck_feedthru) are synchronized into
# SMUCLK and reconverge at each port's four-phase handshake busy flag (busy_d) and at the
# matrix source selectors (ct_src_comb).
waive_violation -add {SMU_CDC_COHERENCY_RECONV_SEQ_dtp_xtrig} \
    -comment {busy_d is the OR of a port's sender and receiver handshake FSM states, each advanced by its own synchronized req/ack input; a cycle of skew between the two only shifts when busy reads high. ct_src_comb registers the OR of the selected, separately synchronized trigger pulses from independent ports, which carry no coherency requirement.} \
    -filter [apply_modprefix [apply_prefix {((ConvergencePoint =~ "${PREFIX}u_dtp/u_cross_trigger_network/gen_ext_ctp[*].u_ctp/u_core/u_handshake_ctrl/busy_d") OR (ConvergencePoint =~ "${PREFIX}u_dtp/u_cross_trigger_network/u_ctm/gen_src_selectors[*].u_src_selector/ct_src_comb")) AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_COHERENCY_RECONV_SEQ } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_GLITCH_CTRL_smc_cpu_dm} \
    -comment {SMC CPU tlDM flops whose every glitch source (-exact_match) is a debug-domain reset input (the powergood stretcher, the RESET_CTRL debug_reset_n CSR, the STAP TRST port) or the far side's synchronized AsyncQueue valid bit. Rocket's AsyncQueue resets each side's valid synchronizers with its own reset OR'd with the far side's reset, and the JTAG-side registers take powergood through the TRST AND, so these inputs reach the crossing as asynchronous resets by design; a glitch on one can only reset the crossing or the debug domain, never raise a valid. Reported only in the flat SMU run.} \
    -filter [apply_modprefix [apply_prefix {(GlitchDestInfo:DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/*") AND ((GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu_ctrl_wrap/reset_ctrl_reg_value_n0_scan.debug_reset_n*") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject == "${PREFIX}jtag_ptap_client_tap_ctrl_i.trst_n") OR (GlitchSrcInfoList:GlitchSrcInfo:SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/*/io_out_source_valid_0/output_chain/u_prim_flop_3sync_r/q_ddd/Q"))}]] \
    -exact_match {GlitchSrcInfoList:GlitchSrcInfo:SrcObject} -app { cdc } -tag { CDC_GLITCH_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_GLITCH_CTRL_dtp} \
    -comment {DTP JTAG status capture of the cross-trigger clock-stop OR (u_cla_clock_stop_sync): its only consumer is the read-only DEBUG_CONTROL status bit, so a glitch can at worst return one wrong status read. Same disposition as ocah_dtp_CDC_GLITCH_CTRL_cla_clock_stop_sync.} \
    -filter [apply_modprefix [apply_prefix {(GlitchDestInfo:DestObject =~ "${PREFIX}u_dtp/u_jtag_intf_unit/u_jtag_ptap/u_jtag_debug_ctrl_reg/u_cla_clock_stop_sync/*") AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_GLITCH_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

# DTP clock-stop syncs: xtrig_clk_stop_req / SMC CLA halt -> DTP clock-stop
# and CLA-clock-stop 2-flop syncs (u_clk_stop_sync, u_cla_clock_stop_sync). Sync
# present; DTP cross-trigger / debug clock-stop control, signed off in DTP block.
waive_violation -add {SMU_CDC_UNSYNC_CTRL_dtp_clock_stop} \
    -comment {DTP clock-stop / CLA-clock-stop control syncs (u_clk_stop_sync, u_cla_clock_stop_sync) from xtrig_clk_stop_req / SMC CLA halt; recognized sync, DTP debug clock-stop path signed off in DTP block.} \
    -filter [apply_modprefix [apply_prefix {(DestObject =~ "${PREFIX}u_dtp/*clock_stop*") AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { nbetik } -timestamp { 27-08-2026 17:22:38 }

waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_cpu_sep_jtag} \
    -comment {SMC power-on reset (REFCLK powergood stretcher) async assertion/deassertion into SMC CPU tlDM/dtm and SEP EL2 DMI JTAG-TCK flops via the DTP PTAP trst AND-gate. The TAP leaves Test-Logic-Reset only when TMS sequences it out (IEEE 1149.1 requires a TMS pull-up), and the other TCK-domain registers update only in TAP data-register states or on DMI requests issued from them, so on the edges around reset removal every destination's next state equals its reset value and the race cannot change state. Extends SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_dtp_jtag to the CPU/SEP TCK domains that only connect flat.} \
    -filter [apply_modprefix [apply_prefix {(SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND (DestClockInfoList:DestClockInfo:ClockName =~ "JTAG*") AND ((DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/*") OR (DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/*"))}]] \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_smc_porst_to_jtag_tck} \
    -comment {SMC power-on reset (REFCLK powergood stretcher) used-as-data into JTAG-TCK-domain debug logic through the DTP PTAP trst AND-gate / Chipyard dmiReset reset-bypass network (trace-verified: no functional datapath). The TAP leaves Test-Logic-Reset only when TMS sequences it out (IEEE 1149.1 requires a TMS pull-up), and the other TCK-domain registers update only in TAP data-register states or on DMI requests issued from them, so on the edges around reset removal every destination's next state equals its reset value and the race cannot change state.} \
    -filter [apply_modprefix [apply_prefix {(SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND (DestClockInfoList:DestClockInfo:ClockName =~ "JTAG*") AND ((DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/dtm/*") OR (DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/*") OR (DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/*") OR (DestObject =~ "${PREFIX}u_dtp/u_jtag_intf_unit/*"))}]] \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_CTRL_smc_cpu_dm} \
    -comment {SMC CPU tlDM AsyncQueue safe-reset handshake. Each source is either a debug-domain reset input (powergood stretcher, RESET_CTRL debug_reset_n CSR, STAP TRST port), which Rocket's AsyncQueue ORs with the local reset to reset each side's valid synchronizers, or one side's synchronized valid bit captured by the far side's 3-flop extend chain. A reset input can only reset the crossing, never raise a valid. Reported only in the flat SMU run.} \
    -filter [apply_modprefix [apply_prefix {(DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/*") AND ((SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") OR (SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu_ctrl_wrap/reset_ctrl_reg_value_n0_scan.debug_reset_n*") OR (SrcObject == "${PREFIX}jtag_ptap_client_tap_ctrl_i.trst_n") OR ((SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/*/io_out_source_valid_0/output_chain/u_prim_flop_3sync_r/q_ddd/Q") AND (DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/*_extend/io_out_source_valid_0/output_chain/u_prim_flop_3sync_r/*")))}]] \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_smc_cpu_dm} \
    -comment {SMC CPU tlDM DMI response AsyncQueue payload (dmiXing nodeIn_d_source mem_0_*) into the dmOuter sink's deq register: the sink reads the payload only after the write-index gray pointer has crossed its 3-flop synchronizer, so the payload is stable when captured. Reported only in the flat SMU run, where the reset fan-in of the pointer chains hides that qualification from the tool.} \
    -filter [apply_modprefix [apply_prefix {(SrcObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmInner/dmiXing/nodeIn_d_source/mem_0_*") AND (DestObject =~ "${PREFIX}u_smc/u_smc_cpu_wrapper/u_smc_cpu/u_digital_top/tlDM/dmOuter/asource/nodeIn_d_sink/io_deq_bits_deq_bits_reg/cdc_reg/*")}]] \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_ASYNCRESET_smc_porst_to_sep_dbg} \
    -comment {SMC power-on reset (REFCLK powergood stretcher = DBG_RSTB_I at SMU) async deassertion into the SEP VeeR debug-reset-domain registers and the DMI jtag-to-core synchronizers; when it releases, PRIMARY (RST_NI) still holds every functional source in reset and the debug transport is idle, so each destination's next state equals its reset value on the edges around release and the race cannot change state.} \
    -filter [apply_modprefix [apply_prefix {(SrcObject =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_reset_unit/u_smc_reset_ctrl/u_powergood_stretcher_n0_scan/*") AND ((DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/veer/dbg/*") OR (DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_mpc_reset_run_req_sync/*") OR (DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/i_dmi_jtag_to_core_sync/*"))}]] \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_UNSYNC_NOSCHEME_sep_spi_miso} \
    -comment {SEP SPI-host MISO readback: external slave launches pad2core_i data from the SEP-generated SCK (SPICLK/SPICLK_OUT_GPIO derive from the controller's own SMUCLK bit timing); the SMUCLK shift-register capture is source-synchronous to the controller's own clock, not an async crossing. Its round-trip timing is an IO-timing requirement the SMU constraints do not apply (SPI stays untimed at SMU and the pads fall back to ck_feedthru). Flat-only (SEP block sees the SEPCLK-timed rsp port).} \
    -filter [apply_modprefix [apply_prefix {(SrcObject =~ "${PREFIX}pad2core_i*") AND (DestObject =~ "${PREFIX}gen_sep.u_sep/u_sep_io/u_sep_ot_spi_wrap/*") AND ((SrcClockInfoList:SrcClockInfo:ClockName =~ "SPICLK*") OR (SrcClockInfoList:SrcClockInfo:ClockName == "ck_feedthru"))}]] \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

waive_violation -add {SMU_CDC_COHERENCY_MULTI_SYNC_debug_observation} \
    -comment {ext_trng_irq_i / the SEP WDT reset request synced on its functional path and again by the SMC external debug-bus observation sync (u_ext_debug_bus_sync3, DFD capture-only); single-bit independent lanes with no coherency requirement.} \
    -filter [apply_modprefix [apply_prefix {(NoConvNoSrcControlPathList:NoConvControlPathInfo:SyncOutput =~ "${PREFIX}u_smc/u_smc_base/u_ext_debug_bus_sync3/*") AND (ContainerInstance == "${BLOCKINST}")}]] \
    -app { cdc } -tag { CDC_COHERENCY_MULTI_SYNC } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Same source set as SEP_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_5975; the flat run reports the convergence at the
# VeeR LSU address adder (lsu_lsc_ctl/lsadder rs1 operand) instead of the tlu mstatus enable. DMI rden/wren syncs
# (JTAG_TCK -> SMUCLK) and PIC gateway syncs (ck_feedthru -> SMUCLK) are independent single-bit events that reach the
# operand only through architectural state; arrival order is functionally arbitrary.
waive_violation -add {SMU_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_sep_dmi_pic} \
    -comment {Independent DMI op-bit and PIC gateway synchronizer outputs converge at the VeeR LSU address adder rs1 operand through architectural state; independent events, arrival order arbitrary (same disposition as SEP_CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ_5975).} \
    -filter [apply_modprefix [apply_prefix {(ConvergencePoint =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/veer/*") AND (ReasonInfoList:ReasonInfo:ReasonCode == "ASYNC_SRC_CONV") AND (ConvControlPathList:ConvergingControlPath:SyncOutput =~ "${PREFIX}gen_sep.u_sep/u_sep_cpu/u_el2_veer_wrapper/dmi_wrapper/i_dmi_jtag_to_core_sync/*")}]] \
    -app { cdc } -tag { CDC_COHERENCY_ASYNCSRCS_RECONV_SEQ } -user { nbetik } -timestamp { 17-09-2026 11:44:06 }

# =============================================================================
# Warning-class dispositions
# =============================================================================

waive_violation -add {SMU_SETUP_CLOCK_UNUSED_BOUNDARY_CLKS} \
    -comment {Output-port memory-interface clocks (SMUCLK_ROM / SMUCLK_RAM* / SMUCLK_{I,D}CACHE_* / SEPCLK_PKA_* / PERIPHERALCLK_I3C_*) and the SPICLK base of the GPIO SPI clocks clock no internal sequentials by construction. SEP_WDT_CLK clocks only the SEP watchdog, which the no-SEP configuration does not elaborate.} \
    -filter [apply_modprefix [apply_prefix {(Clock:ClkName =~ "SMUCLK_*") OR (Clock:ClkName =~ "SEPCLK_*") OR (Clock:ClkName =~ "PERIPHERALCLK_I3C_*") OR (Clock:ClkName == "SPICLK") OR (Clock:ClkName == "SEP_WDT_CLK")}]] \
    -app { cdc } -tag { SETUP_CLOCK_UNUSED } -user { nbetik } -timestamp { 16-09-2026 12:50:22 }

# Reset-tree edges that cross a block boundary, so neither block's RESET_OVERLAP class waiver owns them.
waive_violation -add {SMU_SETUP_RESET_OVERLAP_CROSS_BLOCK_TREE} \
    -comment {DTP trst_n_combined is passed through the PTAP TAP controller and the SMC STAP to smc_cpu_jtag_reset_i, where smu.sv inverts it into the active-high JTAG_RESET. One declared reset reaching the root of another is the reset tree by construction.} \
    -filter [apply_modprefix [apply_prefix {(SrcRstInfo:ResetName == "trst_n_combined") AND (DesRstInfo:ResetName == "JTAG_RESET")}]] \
    -app { cdc } -tag { SETUP_RESET_OVERLAP } -user { nbetik } -timestamp { 17-09-2026 00:00:00 }
waive_violation -add {SMU_SETUP_OUTPUT_MULTICLOCK_DRIVER_avs_pad} -comment {core2pad_o[50] is the AVS MDATA pad: its pad-function mux selects between the SMUCLK GPIO data register and AVS MDATA, launched on the AVS divider clock, so the port is in the fan-out of both domains by design. The select is a quasi-static DATA_CTRL field; the SMC block run times the pad on the AVS GPIO clocks.} -filter [apply_modprefix [apply_prefix {(PortName == "${PREFIX}core2pad_o[50]") AND (ClockedInstanceList:ClockedInstance:InstanceName =~ "${PREFIX}u_smc/u_smc_peripherals/u_smc_padring/gen_gpio_intf[50].u_gpio_interface/u_gpio_intf_reg/field_storage*") AND (ClockedInstanceList:ClockedInstance:ClockName =~ "${PREFIX}u_smc/u_smc_peripherals/u_avsbus_controller/u_clk_div/clk_o")}]] -app { cdc } -tag { SETUP_OUTPUT_MULTICLOCK_DRIVER } -user { nbetik } -timestamp { 02-10-2026 12:45:00 }
