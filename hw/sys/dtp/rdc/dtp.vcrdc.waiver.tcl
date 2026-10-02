# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP VC SpyGlass RDC waivers for Tenstorrent-owned RTL and OpenTitan prim_*
# primitives. PULP axi_cdc_clearable / cdc_fifo_gray_clearable /
# cdc_reset_ctrlr waivers live in dtp.vcrdc.opensource_ip.waiver.tcl.

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
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "dtp") AND (DestObject =~ "*clk_stop_sync*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }

#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : Tenstorrent-owned jtag2axi RTL interacting with PULP axi_cdc_clearable (Group D)
#=======================================================================================================================
# Violations in this group occur in Tenstorrent-owned jtag2axi RTL where the destination flop sits inside
# jtag2axi but the upstream source is the PULP cdc_reset_ctrlr / cdc_fifo_gray_clearable 4-phase clearable
# handshake.  The TCK-domain command processor and series_*_fifo storage registers are quiescent during reset
# because the clearable protocol forces the destination side into isolation before any reset-induced state
# change can affect active logic, and the TCK-domain registers are independently reset by
# trst_n_combined/tlr_reset.
#
# Module-scoped waivers for the PULP primitives themselves (Module == "axi_cdc_clearable" /
# "cdc_fifo_gray_clearable" / "cdc_reset_ctrlr") live in opensource_ip_waiver.tcl.  The waivers in this
# section target Module == "jtag2axi" or Module == "prim_fifo_sync" (OpenTitan primitive used by jtag2axi).
#
# Filter ORDER matters: VC Static credits the first matching waiver.  Per-register waivers are deliberately
# placed BEFORE the same-Module catch-all so each named register carries its own justification; the catch-all
# documents exactly what remains uncovered.
#=======================================================================================================================

#-----------------------------------------------------------------------------------------------------------------------
# jtag2axi: TCK-domain *_tclk command-processor state registers
#-----------------------------------------------------------------------------------------------------------------------
# The jtag2axi command processor holds many *_tclk state registers that latch
# AXI transaction parameters and per-transaction status for the JTAG-driven AXI
# master.  These registers receive handshake/status feedback from the DTPCLK
# domain through the clearable CDC; when rst_n_i asserts, the clearable protocol
# forces the destination side into isolation and the TCK-domain command processor
# sees safe (isolated) status values.  The TCK-domain registers are also
# independently reset by trst_n_combined/tlr_reset, so no register can enter a
# corrupt state.
#
# Four register-specific waivers come first so each named register carries its
# own per-register justification (address loads, transaction-stale flag, etc.).
# The catch-all that follows absorbs the remaining *_tclk register patterns
# under the same clearable-protocol argument.
#-----------------------------------------------------------------------------------------------------------------------

# current_addr_tclk (smc_jtag2axi): per-read AXI read address
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_addr_tclk} \
    -comment {jtag2axi (smc_jtag2axi): cdc_fifo_gray_clearable_ar half_b (rst_n_i, DTPCLK) state reaches current_addr_tclk (no reset, JTAG_TCK). This register holds the current AXI read address; it has no reset because it is loaded from each JTAG command. The clearable protocol guarantees no AXI read is active during reset, so stale address content cannot affect any in-flight transaction. FSM reloads it at the start of each new read.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_addr_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# current_incr_series_addr_tclk (sep_otp_jtag2axi): running incrementing-series address
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_incr_series_addr_tclk} \
    -comment {jtag2axi (sep_otp_jtag2axi): cdc_fifo_gray_clearable_aw half_b (rst_n_i, DTPCLK) state reaches current_incr_series_addr_tclk (no reset, JTAG_TCK). This register holds the running AXI address for an incrementing write series; it has no reset because it is loaded from each JTAG command. The clearable protocol guarantees no AXI transaction is active during reset, so stale address content cannot be forwarded. FSM reloads it before any new series begins.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_incr_series_addr_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# current_tx_stale_tclk (smc_jtag2axi): per-transaction stale/abort flag
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_tx_stale_tclk} \
    -comment {jtag2axi (smc_jtag2axi): CDC reset controller half_b (rst_n_i, DTPCLK) state reaches current_tx_stale_tclk (no reset, JTAG_TCK). This register marks whether the current AXI transaction has stalled; it has no reset because the TCK FSM manages it per-transaction. The clearable protocol guarantees no transaction is active during reset; stale content cannot affect any in-flight operation. FSM clears this at the start of each new transaction.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_tx_stale_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# last_single_op_was_read_tclk (smc_otp_jtag2axi): inter-transaction status
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_last_single_op_was_read_tclk} \
    -comment {jtag2axi (smc_otp_jtag2axi): CDC reset controller half_a (rst_n_i, DTPCLK) state reaches last_single_op_was_read_tclk (no reset, JTAG_TCK). This TCK-domain status register tracks the last AXI transaction type; it has no reset because its value is irrelevant between transactions and the clearable protocol guarantees no AXI transaction is active during reset. The FSM reinitialises it on the first post-reset transaction.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*last_single_op_was_read_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# remaining TCK-domain command-processor *_tclk registers
#   Covers the remaining *_tclk register patterns not enumerated above, e.g.:
#     axi_state_q_tclk                    (jtag2axi command FSM state)
#     current_custom_wstrb_tclk           (latched custom WSTRB for current op)
#     current_data_tclk                   (latched AXI write data for current op)
#     current_is_series_data_with_error_status_op_tclk
#     current_jtag_size_tclk              (latched AXI size from JTAG command)
#     current_op_tclk                     (decoded op code)
#     current_tx_is_from_single_buffer_tclk
#     current_tx_is_series_read_tclk
#     current_use_custom_wstrb_tclk
#     last_read_data_tclk                 (last read data returned to JTAG)
#     last_single_op_status_tclk          (last single op status)
#     plain_reads_pending_tclk            (read counter)
#     series_errstat_pending_tclk         (series errstat pending flag)
#     series_reads_in_flight_tclk         (in-flight read counter)
#     shift_register_q_tclk               (JTAG TDI/TDO shift register)
#     single_op_pending_tclk              (single-op outstanding flag)
#     single_tx_req_valid_tclk            (single-op request valid)
#     sticky_axi_status_tclk              (sticky AXI status latch)
#   All share the same 4-phase clearable-protocol justification: the DTPCLK-side
#   controller drives status that is captured into these TCK-domain registers
#   under the protocol's quiescence guarantee; each register is also
#   independently reset by trst_n_combined/tlr_reset on the TCK side.
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_command_state_tclk_regs} \
    -comment {jtag2axi command processor: DTPCLK-side clearable reset controller half_b data_src_q (rst_n_i) reaches TCK-domain *_tclk command-state registers (trst_n_combined/tlr_reset). The 4-phase clearable protocol forces the destination side into isolation when rst_n_i asserts, so the TCK-domain command processor observes safe isolated values. All TCK-side registers are also independently reset by trst_n_combined/tlr_reset. Catches the remaining *_tclk register patterns beyond the four register-specific waivers above (axi_state_q_tclk, current_custom_wstrb_tclk, current_data_tclk, current_is_series_data_with_error_status_op_tclk, current_jtag_size_tclk, current_op_tclk, current_tx_is_from_single_buffer_tclk, current_tx_is_series_read_tclk, current_use_custom_wstrb_tclk, last_read_data_tclk, last_single_op_status_tclk, plain_reads_pending_tclk, series_errstat_pending_tclk, series_reads_in_flight_tclk, shift_register_q_tclk, single_op_pending_tclk, single_tx_req_valid_tclk, sticky_axi_status_tclk).} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# jtag2axi and prim_fifo_sync: internal FIFO storage (no-reset by design)
#-----------------------------------------------------------------------------------------------------------------------

# prim_fifo_sync read pointer vs storage (smc_otp_jtag2axi series_request_fifo)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_prim_fifo_sync_rptr_storage} \
    -comment {prim_fifo_sync (smc_otp_jtag2axi series_request_fifo): read pointer rptr_wrap_cnt_q (has reset) is visible at storage array (no reset), both in JTAG_TCK domain. prim_fifo_sync intentionally omits storage reset: pointer reset declares the FIFO empty (rptr==wptr), making all storage entries invalid without clearing them. No stale entry can be read because the occupancy is tracked by pointers alone. Standard FIFO design; no real corruption path.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "prim_fifo_sync") AND (ContainerInstance =~ "*jtag2axi*") AND (DestObject =~ "*storage*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# jtag2axi series_rsp_fifo storage (smc_jtag2axi B-channel response)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_series_rsp_fifo_storage} \
    -comment {jtag2axi (smc_jtag2axi): cdc_fifo_gray_clearable_b half_a (rst_n_i, DTPCLK) reset state reaches TCK-domain series_rsp_fifo storage (no reset). The 4-phase clearable-reset protocol ensures B-channel FIFO is drained before the reset state change affects active logic; storage reset is omitted by design (pointer reset declares FIFO empty). Equivalent to the prim_fifo_sync storage waiver above.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*series_rsp_fifo*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# jtag2axi series_request_fifo storage (smc_otp_jtag2axi A-channel request)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_series_request_fifo_storage} \
    -comment {jtag2axi (smc_otp_jtag2axi): series_request_fifo_din_tclk.addr (no reset, JTAG_TCK) drives series_request_fifo storage (no reset, JTAG_TCK). Both are in the same clock domain. FIFO storage has no reset by design; FIFO pointers are reset on TRST/TLR declaring all entries invalid without requiring storage clearance. Same prim_fifo_sync design rationale as RDC:1701. No cross-domain boundary; no real corruption path.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*series_request_fifo*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# TCK-side clear-sequence observers in the DTPCLK (rst_n_i) domain
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_tck_clear_seq_observers} -comment {trst_n_combined/tlr_reset-sourced cdc_reset_ctrlr state reaching the DTPCLK (rst_n_i) consumers of the clearable-CDC clear sequence inside jtag2axi: the CDC dst spill registers and the abort/drain bookkeeping (dst_clear_pending_q, outstanding/orphan counters, discard flags, u_write_fork state). The sequence arrives through the cdc_4phase synchronizer and only drains or discards transactions a TAP reset abandoned; no payload.} -filter [apply_prefix {(RdcSourceResets:ResetName == "trst_n_combined") AND (SrcObject =~ "${PREFIX}u_jtag_intf_unit/u_jtag_ptap/*jtag2axi*/u_axi_cdc/*/i_cdc_reset_ctrlr/*/i_state_transition_cdc_src/data_src_q/*") AND (DestObject =~ "${PREFIX}u_jtag_intf_unit/u_jtag_ptap/*jtag2axi*/*") AND ((RdcDestResets:DestResetInfo:ResetName == "rst_n_i") OR (RdcDestResets:DestResetInfo:ResetName == "PRIMARY_RESET_N_SMC_CLK")) AND ((DestClockInfoList:DestClockInfo:ClockName == "DTPCLK") OR (DestClockInfoList:DestClockInfo:ClockName == "SMUCLK"))}] -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { nbetik } -timestamp { 17-09-2026 18:15:09 }
