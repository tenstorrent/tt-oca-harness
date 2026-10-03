# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP VC SpyGlass CDC waivers for Tenstorrent-owned RTL and OpenTitan prim_*
# primitives. Third-party IP waivers live in dtp.vccdc.opensource_ip.waiver.tcl.

# For waiving CDC violations on IP developed by Tenstorrent teams

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
# ----------------------------------------------------------------------------------

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# CDC_COHERENCY_RECONV_SEQ : Sequential convergence of synchronized signals from the same source domain
#=======================================================================================================================

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# CDC_COHERENCY_RECONV_SEQ : cross_trigger_port 4-phase handshake (req_in + ack_in)
#=======================================================================================================================
# Each external cross_trigger_port (gen_ext_ctp[N]) implements a 4-phase handshake to
# transfer triggers between the external asynchronous domain (ck_feedthru) and DTPCLK.
# Two independent 2-flop synchronizers are used: u_sync_req_in for the request and
# u_sync_ack_in for the acknowledge. Both sources are the same external ck_feedthru
# domain; after synchronization they reconverge at u_handshake_ctrl/busy_d.
# The tool flags this as CDC_COHERENCY_RECONV_SEQ because it sees two independently
# synchronized paths from the same source domain converging, but it does not model
# the 4-phase handshake protocol:
#   - req_in is asserted first and ack_in is only asserted later in response;
#     they are strictly alternating and can never be simultaneously asserted.
#   - busy_d correctly tracks the handshake state based on independently
#     synchronized req and ack.
# All 16 gen_ext_ctp instances (N=0..15) have the same pattern.
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_COHERENCY_RECONV_SEQ_ctp_4phase_busy_d} \
    -comment {cross_trigger_port 4-phase handshake: req_in and ack_in are independently synchronized 1-bit signals from ck_feedthru domain that converge at u_handshake_ctrl/busy_d. The 4-phase protocol guarantees they are strictly alternating (never simultaneously asserted); the CDC tool does not model the handshake protocol. One waiver covers all 16 gen_ext_ctp instances.} \
    -filter {(ReasonInfoList:ReasonInfo:ReasonCode == "SYNC_SRC_CONV") AND (ReasonInfoList:ReasonInfo:ReasonCode == "GRAY_CHECK_IGNORED_SEQ_CONV") AND (ConvergencePoint =~ "*gen_ext_ctp*u_handshake_ctrl/busy_d") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_COHERENCY_RECONV_SEQ } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# CDC_COHERENCY_RECONV_SEQ : cross_trigger_matrix source selector
#=======================================================================================================================
# The CTM source selector (gen_src_selectors[0].u_src_selector/ct_src_comb) receives
# independently synchronized 1-bit req_out signals from all ext CTPs (xtrig_ctp_req_out_din_i[0..15],
# each synchronized via u_sync_req_out) and int CTPs (xtrig_ctm_dst_req_i[0..9], each
# synchronized via u_sync_req_out). All sources come from the same ck_feedthru domain.
# The tool flags this as RECONV_SEQ because multiple independently synchronized 1-bit
# paths from the same source domain converge at ct_src_comb. However:
#   - Each bit is an independent 1-bit trigger request from a distinct trigger source.
#   - The CTM source selector uses combinational OR/priority logic over these bits;
#     it does not require atomic multi-bit coherency across sources.
#   - Each CTP uses a 4-phase handshake ensuring each req bit is stable when read.
# The tool does not model the trigger arbitration semantics.
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_COHERENCY_RECONV_SEQ_ctm_src_selector} \
    -comment {Cross-trigger matrix source selector: multiple independently synchronized 1-bit req_out signals from all CTPs (ck_feedthru domain) converge at ct_src_comb. Each bit is a distinct independent trigger request; CTM does not require atomic coherency across sources. 4-phase handshake in each CTP ensures per-bit stability. Tool does not model trigger arbitration.} \
    -filter {(ReasonInfoList:ReasonInfo:ReasonCode == "SYNC_SRC_CONV") AND (ReasonInfoList:ReasonInfo:ReasonCode == "GRAY_CHECK_IGNORED_SEQ_CONV") AND (ConvergencePoint =~ "*u_ctm*u_src_selector/ct_src_comb") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_COHERENCY_RECONV_SEQ } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# CDC_UNSYNC_NOSCHEME : pwr_on_rst_ni forwarded directly to STAP TRST_N outputs
#=======================================================================================================================
# pwr_on_rst_ni (power-on reset, asynchronous) is forwarded directly to the trst_n field
# of four downstream sub-TAP host control outputs:
#   jtag_stap_extra_host_tap_ctrl_o[0].trst_n
#   jtag_stap_io_host_tap_ctrl_o.trst_n
#   jtag_stap_sep_host_tap_ctrl_o.trst_n
#   jtag_stap_smc_host_tap_ctrl_o.trst_n
# IEEE 1149.1 TRST_N is inherently an asynchronous reset signal; it is designed to be
# asserted without synchronization to TCK. Forwarding pwr_on_rst_ni to TRST_N without
# a synchronizer is correct behavior: adding a synchronizer on an async-to-async reset
# path would be wrong. The CDC tool flags this as a DTPCLK → JTAG_TCK crossing because
# pwr_on_rst_ni is associated with the DTPCLK domain, but no synchronization is
# appropriate or expected on this path.
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_UNSYNC_NOSCHEME_pwr_on_rst_to_stap_trst} \
    -comment {pwr_on_rst_ni is forwarded directly to STAP TRST_N outputs (stap_extra, stap_io, stap_sep, stap_smc). Per IEEE 1149.1 Rule 4.6.1(a), TRST* assertion (1->0) shall be asynchronous to TCK by definition. Deassertion (0->1) has a documented race if TRST* and TCK rise simultaneously with TMS=0 (Recommendation 4.6.1(d)); the standard resolves this via a host protocol constraint (hold TMS=1 during deassertion) rather than a synchronizer on TRST* itself. No in-chip synchronizer is expected or appropriate.} \
    -filter {(SrcObject == "pwr_on_rst_ni") AND (DestObject =~ "*jtag_stap_*host_tap_ctrl_o*.trst_n") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# CDC_UNSYNC_NOSCHEME : cross_trigger_port DTPCLK outputs to ck_feedthru primary outputs
#=======================================================================================================================
# All gen_ext_ctp[N] instances output 7 handshake/data signals from DTPCLK-domain flops
# to the ck_feedthru GPIO pad ring:
#   ct_req_out_dout_q   -> xtrig_ctp_req_out_dout_o[N]
#   ct_req_out_dout_en_q -> xtrig_ctp_req_out_dout_en_o[N]
#   ct_req_out_din_en_q  -> xtrig_ctp_req_out_din_en_o[N]
#   ct_req_in_din_en_q   -> xtrig_ctp_req_in_din_en_o[N]
#   ct_ack_out_dout_q    -> xtrig_ctp_ack_out_dout_o[N]
#   ct_ack_out_dout_en_q -> xtrig_ctp_ack_out_dout_en_o[N]
#   ct_ack_in_din_en_q   -> xtrig_ctp_ack_in_din_en_o[N]
# These are primary outputs of DTP to the GPIO pad ring. The pad ring and chiplet-to-chiplet
# link are responsible for absorbing the clock domain crossing. The 4-phase handshake
# used by each CTP ensures each output is stable before a new handshake begins.
# One waiver covers all 16 gen_ext_ctp instances (N=0..15).
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_UNSYNC_NOSCHEME_ctp_primary_outputs} \
    -comment {gen_ext_ctp[N] DTPCLK-domain handshake/data outputs to ck_feedthru GPIO primary outputs (req_out, req_in_din_en, ack_out, ack_in_din_en). These are primary outputs; synchronization at the DTP boundary is the responsibility of the GPIO pad ring and CLA. 4-phase handshake ensures stability before each new handshake.} \
    -filter {(ReasonInfoList:ReasonInfo:ReasonCode == "NO_SYNC_METHOD") AND (DestObjectType == "primary output") AND (DestClockInfoList:DestClockInfo:ClockName == "ck_feedthru") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_UNSYNC_NOSCHEME } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# INTEGRITY_ASYNCRESET_COMBO_MUX : JTAG TAP async resets gated by prim_and2 / prim_or2
#=======================================================================================================================
# Three single-cell gates sit in front of TAP scan-register async reset pins; the tool flags each because the
# reset arrives through combinational logic. All inputs are in the TCK domain and none can switch in the same
# window as another, so no gate can produce a pulse or glitch at the reset pin:
#   - PTAP u_trst_n_and: AND of two active-low resets (trst_n, pwr_on_rst_ni). Asserts when either input
#     asserts, so it is at least as conservative as either reset alone.
#   - 3DCR reg and STAP u_rst_n_and: trst_n AND (config_hold_sticky OR TLR rst_n). config_hold_sticky is a
#     TCK flop written at Update-DR; TLR rst_n (!test_logic_reset) asserts only in Test-Logic-Reset, a
#     different TAP state, so the OR inputs never change together.
#   - jtag_ic_reset_reg u_rst_n_or: TLR rst_n OR !reset_hold. reset_hold=0 blocks TLR so the IC-reset
#     enable/control register survives Test-Logic-Reset. reset_hold is a TCK flop (Update-DR, TRST-reset to 1);
#     under TRST both OR inputs fall together, so the output is monotonic.
# Primitive cells keep each reset path a single known cell that synthesis cannot merge (W402b).
#=======================================================================================================================
waive_violation -add {ocah_dtp_INTEGRITY_ASYNCRESET_COMBO_MUX_prim_and2_resets} \
    -comment {Single-cell async reset gating in the JTAG TAP. prim_and2 combines two active-low resets and asserts on either; prim_or2 masks the TLR reset with a TCK-domain hold bit (config_hold_sticky, reset_hold) that changes only at Update-DR, never in Test-Logic-Reset, and under TRST both inputs fall together so the output is monotonic. All inputs are TCK-domain, so no glitch can form at the reset pin; primitive cells keep the path from being merged by synthesis (W402b).} \
    -filter {(Tag == "INTEGRITY_ASYNCRESET_COMBO_MUX") AND (ContainerInstance =~ "*u_jtag_intf_unit/*") AND ((Module == "prim_and2") OR (Module == "jtag_ic_reset_reg") OR ((Module == "prim_or2") AND (ContainerInstance =~ "*u_jtag_ic_reset_reg/*")))} \
    -app { cdc } -tag { INTEGRITY_ASYNCRESET_COMBO_MUX } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# SETUP_CLOCK_UNUSED : output TCK clock passthroughs (JTAG_TCK_*_OUT)
#=======================================================================================================================
# Nine generated output clocks (JTAG_TCK_BSR_OUT, JTAG_TCK_DFD_OUT, JTAG_TCK_DFT_OUT,
# JTAG_TCK_DFT_SECURE_OUT, JTAG_TCK_STAP_EXTRA_OUT0, JTAG_TCK_STAP_IO_OUT,
# JTAG_TCK_STAP_OUT, JTAG_TCK_STAP_SEP_OUT, JTAG_TCK_STAP_SMC_OUT) are feed-through
# copies of JTAG_TCK to downstream STAP/BSR/DFD/DFT blocks. They are created with
# -combinational -divide_by 1 so that STA constrains the combinational feed-through
# path rather than treating it as data.
# At the DTP level there are no internal flops captured by these clocks (they are
# output-only); hence SETUP_CLOCK_UNUSED. This is by design: the clocks are intended
# for downstream blocks outside of DTP.
#=======================================================================================================================
waive_violation -add {ocah_dtp_SETUP_CLOCK_UNUSED_output_tck_clocks} \
    -comment {Nine JTAG_TCK_*_OUT generated clocks are output-only feed-through copies of JTAG_TCK for downstream STAP/BSR/DFD/DFT blocks. No DTP-internal flops are captured by them; this is by design. The clocks are created with -combinational so STA constrains the feed-through path.} \
    -filter {(Clock:ClkName =~ "JTAG_TCK_*_OUT") OR (Clock:ClkName =~ "JTAG_TCK_BSR_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFD_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFT_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFT_SECURE_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_EXTRA_OUT0") OR (Clock:ClkName =~ "JTAG_TCK_STAP_IO_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_SEP_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_SMC_OUT")} \
    -app { cdc } -tag { SETUP_CLOCK_UNUSED } -user { bmelton } -timestamp { 14-05-2026 22:30:00 }

#=======================================================================================================================
# CDC_GLITCH_CTRL : OR-reduction of clk-stop-request signals before synchronizers
#=======================================================================================================================
# Both ctn_clock_stop_ctrl and jtag_debug_ctrl_reg reduce multi-bit clock-stop request
# vectors combinationally (via | operator) before feeding a 2-stage synchronizer.
# The tool flags two patterns:
#
# u_cla_clock_stop_sync (TCK domain):
#   xtrig_clk_stop_req_i[8:0] (ck_feedthru) are all in the same domain; their OR
#   reduction is glitch-free in practice because the bits are synchronous to each other.
#   Any sub-cycle glitch on the OR output is far shorter than one TCK period and will
#   be resolved by the 2-stage synchronizer.
#
# u_clk_stop_sync (DTPCLK domain):
#   xtrig_clk_stop_req_i[8:0] (ck_feedthru) and jtag_clock_stop (JTAG_TCK) are OR'd
#   before the DTPCLK synchronizer. The 2-stage synchronizer is precisely the mechanism
#   designed to handle multi-domain asynchronous inputs: any transient at the synchronizer
#   input is resolved within 2 DTPCLK cycles. For a safety-fail-safe "stop clock" signal,
#   metastability at the synchronizer input is acceptable because the resolved output is
#   always correct (clocks stop if and only if a stop is genuinely requested).
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_GLITCH_CTRL_ctn_clk_stop_sync} \
    -comment {ctn_clock_stop_ctrl/u_clk_stop_sync (DTPCLK domain), GLITCH_SOURCES_FROM_DIFF_DOMAIN: xtrig_clk_stop_req_i[8:0] (ck_feedthru) is OR'd with jtag_clock_stop (JTAG_TCK) before the 2-stage synchronizer. The synchronizer is precisely the correct mechanism for asynchronous multi-domain inputs; any transient at its input resolves within 2 DTPCLK cycles. Fail-safe stop-clock path -- output is metastability-free regardless of input waveform.} \
    -filter {(GlitchDestInfo:DestObject =~ "*u_clock_stop_ctrl/u_clk_stop_sync*") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_GLITCH_CTRL } -user { bmelton } -timestamp { 15-05-2026 04:30:00 }

waive_violation -add {ocah_dtp_CDC_GLITCH_CTRL_cla_clock_stop_sync} \
    -comment {jtag_debug_ctrl_reg/u_cla_clock_stop_sync (JTAG_TCK domain), GLITCH_SOURCES_FROM_SAME_DOMAIN: xtrig_clk_stop_req_i[8:0] (all ck_feedthru) is OR-reduced before the 2-stage synchronizer. The 9 bits are synchronous to each other so the OR is glitch-free in practice. The synchronizer captures the result during JTAG Capture-DR; any residual transient resolves within 2 TCK cycles. Worst-case incorrect capture is harmless -- JTAG host re-reads on the next scan.} \
    -filter {(GlitchDestInfo:DestObject =~ "*u_jtag_debug_ctrl_reg/u_cla_clock_stop_sync*") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_GLITCH_CTRL } -user { bmelton } -timestamp { 15-05-2026 04:30:00 }

#=======================================================================================================================
# CDC_UNSYNC_CTRL : NONSTATIC_COMBO_IN_CROSSING for clock-stop synchronizer inputs
#=======================================================================================================================
# The tool flags NONSTATIC_COMBO_IN_CROSSING because the OR-reduction of
# xtrig_clk_stop_req_i (and the OR with jtag_clock_stop in ctn_clock_stop_ctrl)
# is combinational logic in the crossing path, not a registered source.
#
# This is intentional: xtrig_clk_stop_req_i is a primary input (ck_feedthru domain)
# and ctn_clock_stop_ctrl does not have the ck_feedthru clock — the OR-reduction CANNOT
# be pre-registered in the source domain within this module. The 2-stage synchronizer is
# placed immediately after the OR-reduction to resolve metastability. The tool also
# reports SYNC_BY_NFF (Multi Flop Synchronizer detected), confirming it recognizes the
# synchronizer; it is only objecting to the non-registered source.
#
# xtrig_clk_stop_req_i → u_cla_clock_stop_sync (TCK)
# xtrig_clk_stop_req_i → u_clk_stop_sync (DTPCLK)
# jtag_clock_stop Q[3] (JTAG_TCK) → u_clk_stop_sync (DTPCLK)
#   (partially-matched because the OR before the sync merges this with the ck_feedthru signal)
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_UNSYNC_CTRL_cla_clock_stop_sync} \
    -comment {NONSTATIC_COMBO_IN_CROSSING: xtrig_clk_stop_req_i[8:0] is OR-reduced combinationally before u_cla_clock_stop_sync. ctn_clock_stop_ctrl lacks the ck_feedthru clock so pre-registration in source domain is not possible here. Tool confirms SYNC_BY_NFF (2-stage synchronizer present). The synchronizer correctly resolves any metastability within 2 TCK cycles.} \
    -filter {(DestObject =~ "*u_cla_clock_stop_sync*") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { bmelton } -timestamp { 15-05-2026 04:30:00 }

waive_violation -add {ocah_dtp_CDC_UNSYNC_CTRL_clk_stop_sync} \
    -comment {NONSTATIC_COMBO_IN_CROSSING + ASYNC_SRC_CONVERGE: xtrig_clk_stop_req_i[8:0] (ck_feedthru) and jtag_clock_stop Q[3] (JTAG_TCK) are OR'd combinationally before u_clk_stop_sync. Two sources from different domains cannot be pre-registered together without knowing which domain to use. The OR-then-sync pattern is the standard approach for "is any stop requested?" logic; the 2-stage synchronizer handles both sources. Tool confirms SYNC_BY_NFF.} \
    -filter {(DestObject =~ "*u_clk_stop_sync*") AND (Module == "dtp")} \
    -app { cdc } -tag { CDC_UNSYNC_CTRL } -user { bmelton } -timestamp { 15-05-2026 04:30:00 }

#=======================================================================================================================
# CDC_UNSYNC_ASYNCRESET : pwr_on_rst_ni async deassertion observed at JTAG-domain flop reset pins
#=======================================================================================================================
# pwr_on_rst_ni is declared as a DTPCLK-domain primary reset (create_reset in
# dtp.resets.tcl). After that declaration, VC Static traces every path from
# pwr_on_rst_ni to a flop async-reset pin whose clock is asynchronous to DTPCLK and
# reports the *deassertion* as an unsynchronized CDC.  All 27 destinations sit
# inside u_jtag_intf_unit and are reached via:
#
#   pwr_on_rst_ni -> u_trst_n_and (prim_and2 with TRST_N pad) -> trst_n_combined
#       -> JTAG TAP controller flops (capture/shift/update FSM, TLR flop, tdo_oen,
#          tdo_retimed, dr_scan_select_reg, current_state, tms_reset_counter)
#       -> per-STAP rst_n gates -> *_config_hold_sticky_flop / u_3dcr_scan_reg
#          gen_rst_n_reset.u_update_flop
#       -> u_jtag_ic_reset_reg/u_reset_hold_scan_reg/u_update_flop
#       -> u_jtag_tmp/u_tmp_state_flop
#
# Per IEEE 1149.1 Rule 4.6.1(a), TRST* assertion is asynchronous to TCK by
# definition; deassertion is governed by the host-protocol constraint in
# Recommendation 4.6.1(d) (hold TMS=1 while TRST* deasserts, with TCK either
# inactive or stably clocking). At chip power-on, TCK is quiescent (no JTAG host
# activity yet), so any pwr_on_rst_ni deassertion is safe by construction. A
# pwr_on_rst_ni assertion during JTAG activity would be a chip-level fault
# requiring host re-synchronisation anyway; no in-chip synchronizer is expected.
# Same justification family as ocah_dtp_CDC_UNSYNC_NOSCHEME_pwr_on_rst_to_stap_trst
# (which covers the dtp.sv boundary STAP TRST_N outputs).
#=======================================================================================================================
waive_violation -add {ocah_dtp_CDC_UNSYNC_ASYNCRESET_pwr_on_rst_to_jtag_flops} \
    -comment {pwr_on_rst_ni (DTPCLK-domain primary reset) is gated with TRST_N via prim_and2 (u_trst_n_and) into trst_n_combined and further per-STAP rst_n gates. All 27 destinations are JTAG-domain flop async-reset pins inside u_jtag_intf_unit (TAP FSM flops, dr_scan_select_reg, tdo_retimed, per-STAP config_hold_sticky_flop, *_3dcr update flops, jtag_ic_reset_reg update flop, jtag_tmp state flop). Per IEEE 1149.1 Rule 4.6.1(a), TRST* assertion is asynchronous to TCK by definition; deassertion is governed by Recommendation 4.6.1(d) (host holds TMS=1 with TCK inactive or stably clocking). At chip power-on TCK is quiescent so pwr_on_rst_ni deassertion is safe by construction. Same justification family as ocah_dtp_CDC_UNSYNC_NOSCHEME_pwr_on_rst_to_stap_trst.} \
    -filter {(Tag == "CDC_UNSYNC_ASYNCRESET") AND (SrcObject == "pwr_on_rst_ni") AND (Module == "dtp") AND (DestObject =~ "*u_jtag_intf_unit*")} \
    -app { cdc } -tag { CDC_UNSYNC_ASYNCRESET } -user { bmelton } -timestamp { 17-05-2026 22:30:00 }

#=======================================================================================================================
# SETUP_RESET_OVERLAP : declared parent→child propagations in the JTAG reset hierarchy
#=======================================================================================================================
# Declaring create_generated_reset -master_reset <P> for a child C causes VC Static
# to emit a SETUP_RESET_OVERLAP for every (P -> C) edge: the master reset physically
# feeds the gate/flop that computes C, which is by definition how a generated reset
# is constructed. This is declared design intent, not uncontrolled overlap.
#
# Reset hierarchy (declared in dtp.resets.tcl):
#
#   pwr_on_rst_ni                         (create_reset)
#     └── trst_n_combined                 (= prim_and2(pwr_on_rst_ni, TRST_N))
#           ├── tlr_reset                 (= TLR flop output, reset by trst_n_combined)
#           ├── stap_sep_dbg_rst          (= prim_and2(trst_n_combined, local rst_n))
#           ├── stap_io_rst               (= prim_and2(trst_n_combined, local rst_n))
#           ├── stap_3dcr_rst             (= prim_and2(trst_n_combined, local rst_n))
#           ├── stap_extra0_rst           (= prim_and2(trst_n_combined, local rst_n))
#           ├── stap_smc_dbg_rst          (= prim_and2(trst_n_combined, local rst_n))
#           └── ic_reset_ctrl_rst_n       (= prim_and2(trst_n_combined, scan enable))
#
# tlr_reset also reaches each STAP/IC gated reset because the TLR flop output is
# wired into the same TAP-side reset tree those gates drive (IEEE 1149.1: TLR
# resets all TAP/SIB state). Those edges are sibling-to-sibling within the JTAG
# TCK domain, not cross-hierarchy hazards.
#
# Each waiver below targets one specific source reset and an explicit list of
# allowed destinations. A new STAP, a new hierarchy parent, or any unexpected
# parent->child edge will NOT be silently swept up -- it will appear as an
# unwaived SETUP_RESET_OVERLAP requiring deliberate review.
#=======================================================================================================================

# Edge: pwr_on_rst_ni -> trst_n_combined
waive_violation -add {ocah_dtp_cdc_SETUP_RESET_OVERLAP_pwr_on_rst_to_trst_n_combined} \
    -comment {Declared edge pwr_on_rst_ni (create_reset) -> trst_n_combined (create_generated_reset). trst_n_combined = prim_and2(pwr_on_rst_ni, TRST_N pin); the master physically reaching its child's AND gate is by construction.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND ((SrcRstInfo:ResetName == "pwr_on_rst_ni") OR (SrcRstInfo:ResetName == "POWERGOOD_STABLE_N")) AND (DesRstInfo:ResetName == "trst_n_combined")} \
    -app { cdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: trst_n_combined -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_cdc_SETUP_RESET_OVERLAP_trst_n_combined_to_children} \
    -comment {Declared edges trst_n_combined -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. Each child is computed as prim_and2(trst_n_combined, local enable); the master physically feeding its child's AND gate is by construction. Hierarchy declared in dtp.resets.tcl.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "trst_n_combined") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { cdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: tlr_reset -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_cdc_SETUP_RESET_OVERLAP_tlr_reset_to_siblings} \
    -comment {Declared edges tlr_reset -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. tlr_reset is the JTAG TAP Test-Logic-Reset flop output (sibling of the STAP/IC gated resets under trst_n_combined). Per IEEE 1149.1, TLR resets all TAP/SIB state, so the TLR flop output fans into the same TAP-side reset tree that the STAP and IC reset gates drive. Sibling-to-sibling overlap within the JTAG TCK domain, not a cross-hierarchy hazard.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "tlr_reset") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { cdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }
