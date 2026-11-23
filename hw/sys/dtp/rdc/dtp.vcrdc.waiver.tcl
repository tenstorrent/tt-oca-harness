# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP VC SpyGlass RDC waivers for Tenstorrent-owned RTL and OpenTitan prim_*
# primitives. Third-party IP waivers live in dtp.vcrdc.opensource_ip.waiver.tcl.

# general_waiver.tcl -- DTP RDC waivers
#
# All violations waived here have been individually reviewed. Each waiver entry
# documents the design intent and justification for why the flagged condition is
# safe or expected.

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

#=======================================================================================================================
# INTEGRITY_RESET_GLITCH : combinational logic in JTAG domain async reset paths
#=======================================================================================================================
# Two groups of violations share the same root cause: a flop output drives an async
# reset pin through a single-gate combinational cell (prim_or2 or prim_and2).
#
# Group 1 -- 3DCR scan register update flops (5 violations: PTAP + 4 STAPs):
#   u_*stap*/u_3dcr_scan_reg/gen_rst_n_reset.u_update_flop reset pin is driven by
#   u_rst_n_or (prim_or2) combining:
#     - u_config_hold_sticky_flop/q_o  (TCK-domain flop: "3DCR config-hold sticky" bit)
#     - u_*_rst_n_and/out_o            (the locally-gated TRST_N combined reset)
#   The "glitch source" is u_config_hold_sticky_flop/q_o, which is a TCK-domain flop.
#   Its output only changes on TCK edges, not asynchronously. The prim_or2 is a single
#   level of logic -- no internal state -- and its inputs cannot glitch simultaneously
#   because config_hold_sticky only toggles synchronously to TCK.
#
# Group 2 -- IC Reset enable-control scan register update flop (1 violation):
#   u_reset_enable_control_scan_reg/gen_rst_n_reset.u_update_flop reset pin is driven
#   by reset_enable_control_scan_ctrl.rst_n combining:
#     - u_reset_hold_scan_reg/gen_rst_n_reset.u_update_flop/q_o  (TCK-domain scan flop)
#     - u_test_logic_reset_flop/q_o                               (JTAG TLR soft reset)
#   Both sources are TCK-domain flops; the combinational merge is glitch-free because
#   both inputs only toggle synchronously with TCK.
#
# The "glitch" concern only applies when a flop output changes asynchronously relative
# to the receiving reset domain. Here all sources are TCK-domain flops whose outputs
# change synchronously to TCK. The gated reset paths are therefore glitch-free in
# normal operation and safe to waive.
#=======================================================================================================================
waive_violation -add {ocah_dtp_INTEGRITY_RESET_GLITCH_3dcr_scan_regs} \
    -comment {Five 3DCR scan register update flop async reset pins are driven through prim_or2 from u_config_hold_sticky_flop (TCK-domain) OR the local TRST_N gated reset. The config_hold_sticky_flop output is TCK-synchronous; it cannot glitch the async reset independently of TCK transitions. Single-gate combinational logic with TCK-synchronous inputs is glitch-free.} \
    -filter {(Tag == "INTEGRITY_RESET_GLITCH") AND (GlitchyDestObjectList:GlitchyDestObject =~ "*/u_3dcr_scan_reg/*")} \
    -app { rdc } -tag { INTEGRITY_RESET_GLITCH } -user { bmelton } -timestamp { 15-05-2026 11:30:00 }

waive_violation -add {ocah_dtp_INTEGRITY_RESET_GLITCH_ic_reset_scan_reg} \
    -comment {IC Reset enable-control scan register update flop async reset is driven by the combinational merge of u_reset_hold_scan_reg output (TCK-domain scan flop) and the JTAG TLR flop output (also TCK-domain). Both sources are TCK-synchronous; no asynchronous glitch is possible on the combined reset net.} \
    -filter {(Tag == "INTEGRITY_RESET_GLITCH") AND (GlitchyDestObjectList:GlitchyDestObject =~ "*u_jtag_ic_reset_reg/u_reset_enable_control_scan_reg/*")} \
    -app { rdc } -tag { INTEGRITY_RESET_GLITCH } -user { bmelton } -timestamp { 15-05-2026 11:30:00 }

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
waive_violation -add {ocah_dtp_rdc_SETUP_CLOCK_UNUSED_output_tck_clocks} \
    -comment {Nine JTAG_TCK_*_OUT generated clocks are output-only feed-through copies of JTAG_TCK for downstream STAP/BSR/DFD/DFT blocks. No DTP-internal flops are captured by them; this is by design. The clocks are created with -combinational so STA constrains the feed-through path correctly.} \
    -filter {(Tag == "SETUP_CLOCK_UNUSED") AND ((Clock:ClkName =~ "JTAG_TCK_BSR_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFD_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFT_OUT") OR (Clock:ClkName =~ "JTAG_TCK_DFT_SECURE_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_EXTRA_OUT0") OR (Clock:ClkName =~ "JTAG_TCK_STAP_IO_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_SEP_OUT") OR (Clock:ClkName =~ "JTAG_TCK_STAP_SMC_OUT"))} \
    -app { rdc } -tag { SETUP_CLOCK_UNUSED } -user { bmelton } -timestamp { 15-05-2026 11:30:00 }

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
waive_violation -add {ocah_dtp_rdc_SETUP_RESET_OVERLAP_pwr_on_rst_to_trst_n_combined} \
    -comment {Declared edge pwr_on_rst_ni (create_reset) -> trst_n_combined (create_generated_reset). trst_n_combined = prim_and2(pwr_on_rst_ni, TRST_N pin); the master physically reaching its child's AND gate is by construction.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND ((SrcRstInfo:ResetName == "pwr_on_rst_ni") OR (SrcRstInfo:ResetName == "POWERGOOD_STABLE_N")) AND (DesRstInfo:ResetName == "trst_n_combined")} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: trst_n_combined -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_rdc_SETUP_RESET_OVERLAP_trst_n_combined_to_children} \
    -comment {Declared edges trst_n_combined -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. Each child is computed as prim_and2(trst_n_combined, local enable); the master physically feeding its child's AND gate is by construction. Hierarchy declared in dtp.resets.tcl.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "trst_n_combined") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: tlr_reset -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_rdc_SETUP_RESET_OVERLAP_tlr_reset_to_siblings} \
    -comment {Declared edges tlr_reset -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. tlr_reset is the JTAG TAP Test-Logic-Reset flop output (sibling of the STAP/IC gated resets under trst_n_combined). Per IEEE 1149.1, TLR resets all TAP/SIB state, so the TLR flop output fans into the same TAP-side reset tree that the STAP and IC reset gates drive. Sibling-to-sibling overlap within the JTAG TCK domain, not a cross-hierarchy hazard.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "tlr_reset") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : debug_ctrl scan reg → clock-stop synchronizer (dtp, cross-domain)
#=======================================================================================================================
# Module: dtp
#   Source : u_debug_ctrl_scan_reg/gen_rst_n_reset.u_update_flop/q_o/Q[3]
#            (JTAG_TCK domain, reset by JTAG reset hierarchy)
#   Dest   : u_cross_trigger_network/u_clock_stop_ctrl/u_clk_stop_sync/u_sync_1/q_o/Q[0]
#            (DTPCLK domain, rst_n_i only)
#
# The JTAG debug_ctrl scan register's update_flop (bit 3, which controls clock stop)
# drives into the DTPCLK clock-stop synchronizer chain via a CDC synchronizer
# (u_clk_stop_sync = 2-stage SYNC_BY_NFF). When TRST_N asserts:
#   1. The update_flop is cleared (debug_ctrl → 0, clock-stop bit = 0)
#   2. The cleared value passes through u_sync_1 (DTPCLK-domain) on the next DTPCLK edge
#   3. DTPCLK logic sees "clock stop deasserted"
#
# This is SAFE and intentional: when JTAG resets, debug-commanded clock stops should
# deassert so the chip is not left in a clock-stopped state after JTAG disconnects.
# The 2-stage synchronizer is the correct CDC mechanism for this path; u_sync_1/q_o
# is the CDC destination flop, not a data register that is "corrupted" by the reset.
# The RDC tool does not model that the synchronizer's job is to handle exactly this
# asynchronous domain change.
#=======================================================================================================================
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_debug_ctrl_clk_stop_sync} \
    -comment {dtp: JTAG debug_ctrl scan register update_flop (TCK domain, JTAG reset) drives DTPCLK clock-stop synchronizer (u_clk_stop_sync, 2-stage SYNC_BY_NFF). When TRST asserts the update_flop is cleared, deasserting clock-stop in the DTPCLK domain -- intentional safe behavior so JTAG reset does not leave the chip clock-stopped. u_sync_1 is the CDC synchronizer first stage (SYNC_BY_NFF); the RDC tool flags this as corruption but the synchronizer correctly captures the async change within one DTPCLK cycle. No missing blocking scheme -- the synchronizer is the scheme.} \
    -filter [apply_modprefix {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "${MODPREFIX}dtp") AND (DestObject =~ "*clk_stop_sync*")}] \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }
