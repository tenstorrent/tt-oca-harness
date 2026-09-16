# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length
#
# DTP SpyGlass RDC waivers for Tenstorrent-owned RTL and OpenTitan prim_*
# primitives. PULP axi_cdc_clearable / cdc_fifo_gray_clearable /
# cdc_reset_ctrlr waivers live in dtp.vcrdc.opensource_ip.waiver.tcl.
#
# All violations waived here have been individually reviewed. Each waiver entry
# documents the design intent and justification for why the flagged condition is
# safe or expected.

#=======================================================================================================================
# INTEGRITY_RESET_GLITCH : combinational logic in JTAG domain async reset paths
#=======================================================================================================================
# Two groups of violations share the same root cause: a flop output drives an async
# reset pin through a single-gate combinational cell (prim_or2, prim_and2, or prim_inv).
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
#   by u_rst_n_or (prim_or2) combining:
#     - u_reset_hold_inv/out_o     (prim_inv of u_reset_hold_scan_reg, TCK-domain)
#     - scan_ctrl_i.rst_n          (TAP !test_logic_reset, TCK-domain TLR)
#   Both sources are TCK-domain flops; the primitive merge is glitch-free because
#   both inputs only toggle synchronously with TCK.
#
# The "glitch" concern only applies when a flop output changes asynchronously relative
# to the receiving reset domain. Here all sources are TCK-domain flops whose outputs
# change synchronously to TCK. The gated reset paths are therefore glitch-free in
# normal operation and safe to waive.
#=======================================================================================================================
waive_violation -add {ocah_dtp_INTEGRITY_RESET_GLITCH_3dcr_scan_regs} \
    -comment {Five 3DCR scan register update flop async reset pins are driven through prim_or2 from u_config_hold_sticky_flop (TCK-domain) OR the local TRST_N gated reset. The config_hold_sticky_flop output is TCK-synchronous; it cannot glitch the async reset independently of TCK transitions. Single-gate combinational logic with TCK-synchronous inputs is glitch-free.} \
    -filter {(Tag == "INTEGRITY_RESET_GLITCH") AND (Module == "dtp")} \
    -app { rdc } -tag { INTEGRITY_RESET_GLITCH } -user { bmelton } -timestamp { 15-05-2026 11:30:00 }

waive_violation -add {ocah_dtp_INTEGRITY_RESET_GLITCH_ic_reset_scan_reg} \
    -comment {IC Reset enable-control scan register update flop async reset is driven through prim_or2 of prim_inv(u_reset_hold_scan_reg) and TAP TLR (scan_ctrl_i.rst_n). Both sources are TCK-synchronous; no asynchronous glitch is possible on the combined reset net.} \
    -filter {(Tag == "INTEGRITY_RESET_GLITCH") AND (ContainerInstance =~ "*u_jtag_ptap*")} \
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
# Reset hierarchy (declared in dtp.timing_post.tcl):
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
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "pwr_on_rst_ni") AND (DesRstInfo:ResetName == "trst_n_combined")} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: trst_n_combined -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_rdc_SETUP_RESET_OVERLAP_trst_n_combined_to_children} \
    -comment {Declared edges trst_n_combined -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. Each child is computed as prim_and2(trst_n_combined, local enable); the master physically feeding its child's AND gate is by construction. Hierarchy declared in dtp.timing_post.tcl.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "trst_n_combined") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

# Edges: tlr_reset -> {5 STAP gated resets, ic_reset_ctrl_rst_n}
waive_violation -add {ocah_dtp_rdc_SETUP_RESET_OVERLAP_tlr_reset_to_siblings} \
    -comment {Declared edges tlr_reset -> {stap_sep_dbg_rst, stap_io_rst, stap_3dcr_rst, stap_extra0_rst, stap_smc_dbg_rst, ic_reset_ctrl_rst_n}. tlr_reset is the JTAG TAP Test-Logic-Reset flop output (sibling of the STAP/IC gated resets under trst_n_combined). Per IEEE 1149.1, TLR resets all TAP/SIB state, so the TLR flop output fans into the same TAP-side reset tree that the STAP and IC reset gates drive. Sibling-to-sibling overlap within the JTAG TCK domain, not a cross-hierarchy hazard.} \
    -filter {(Tag == "SETUP_RESET_OVERLAP") AND (SrcRstInfo:ResetName == "tlr_reset") AND ((DesRstInfo:ResetName == "stap_sep_dbg_rst") OR (DesRstInfo:ResetName == "stap_io_rst") OR (DesRstInfo:ResetName == "stap_3dcr_rst") OR (DesRstInfo:ResetName == "stap_extra0_rst") OR (DesRstInfo:ResetName == "stap_smc_dbg_rst") OR (DesRstInfo:ResetName == "ic_reset_ctrl_rst_n"))} \
    -app { rdc } -tag { SETUP_RESET_OVERLAP } -user { bmelton } -timestamp { 17-05-2026 17:30:00 }

#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : JTAG scan chain data registers with no async reset (Groups A-C)
#=======================================================================================================================
# JTAG scan chain registers (prim_jtag_scan_reg, jtag_stap SIB mux, jtag_intf_unit scan data)
# follow IEEE 1149.1 conventions:
#
#   u_update_flop: Has async reset (cleared on TRST_N / TLR). Its output drives the
#                  shift-register chain as the last-updated value.
#   scan_data:     Does NOT have async reset by design. Scan chain data represents the
#                  last JTAG-programmed value; resetting it would discard valid content.
#                  The JTAG protocol (not the hardware reset) initializes scan_data.
#
# When TRST_N or TLR asserts asynchronously:
#   - u_update_flop is immediately cleared (async reset)
#   - On the next TCK rising edge, scan_data captures the cleared value
#   - This is exactly IEEE 1149.1 behavior: all JTAG registers initialize to their
#     default values on TRST_N via the scan update protocol, not via async reset pins
#
# The RDC tool flags this because it sees a reset propagating from u_update_flop to
# scan_data without a blocking synchronizer, but the propagation is intentional and
# bounded to one TCK clock cycle. Both source and destination are in the same TCK
# clock domain; the "corruption" concern only applies across clock domain boundaries.
#
# Group A: prim_jtag_scan_reg internal (V2: RDC:1678, V3: RDC:1689, V8: RDC:1866, V10: RDC:1914)
# Group B: jtag_stap 3DCR update flop → SIB mux scan_data (V9: RDC:1883, V11: RDC:1919)
# Group C: jtag_intf_unit flops → scan_data (V5: RDC:1833, V6: RDC:1861, V7: RDC:1863)
#=======================================================================================================================
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_scan_reg_update_to_scan_data} \
    -comment {prim_jtag_scan_reg: u_update_flop (has async reset) drives scan_data (no reset) within the same TCK clock domain. IEEE 1149.1 JTAG scan chain design: scan_data holds the last JTAG-programmed value and is not reset asynchronously; on TRST/TLR the update_flop is cleared and the reset value propagates to scan_data on the next TCK edge. Both flops are in the same clock domain; RDC corruption concern requires a cross-domain boundary, which is absent here.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "prim_jtag_scan_reg") AND (DestObject =~ "*scan_data*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }

waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_stap_scan_data} \
    -comment {jtag_stap: 3DCR scan register update_flop output (stap_*_rst reset) drives sib_mux_pre scan_data (no reset) within the same JTAG_TCK clock domain. By IEEE 1149.1 convention, scan_data in the SIB mux has no async reset; the JTAG update protocol initializes it. Reset assertion clears the update_flop, and scan_data takes the cleared value on the next TCK cycle -- intentional single-domain behavior, not a real cross-domain corruption path.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag_stap") AND (DestObject =~ "*scan_data*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }

waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_intf_unit_scan_data} \
    -comment {jtag_intf_unit: Three intra-TCK-domain paths where a JTAG control flop (dbg_disable_sync output, shift_dr_flop, or dfd_sib update_flop -- all reset by JTAG resets) drives a downstream scan_data register (no reset). All source and destination flops share JTAG_TCK. Scan_data registers in JTAG scan chains intentionally have no async reset per IEEE 1149.1; they are initialized by JTAG scan protocol. No cross-domain boundary is involved.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag_intf_unit") AND (DestObject =~ "*scan_data*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }

waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag_ptap_scan_data} \
    -comment {jtag_ptap: TAP controller state flop (u_current_state_flop, trst_n_combined reset) drives the debug_ctrl scan register scan_data (no reset) within the same JTAG_TCK domain. Same IEEE 1149.1 scan chain pattern as prim_jtag_scan_reg Group A: scan_data intentionally has no async reset; the TAP state drives scan_data via normal shift/update protocol. No cross-domain boundary.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag_ptap") AND (DestObject =~ "*scan_data*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 15-05-2026 12:00:00 }

#=======================================================================================================================
# RDC_CORRUPT_OBSERVED : debug_ctrl scan reg → clock-stop synchronizer (dtp, cross-domain)
#=======================================================================================================================
# RDC:1644 — Module: dtp
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
    -comment {dtp: JTAG debug_ctrl scan register update_flop (TCK domain, JTAG reset) drives DTPCLK clock-stop synchronizer (u_clk_stop_sync, 2-stage SYNC_BY_NFF). When TRST asserts the update_flop is cleared, deassserting clock-stop in the DTPCLK domain -- intentional safe behavior so JTAG reset does not leave the chip clock-stopped. u_sync_1 is the CDC synchronizer first stage (SYNC_BY_NFF); the RDC tool flags this as corruption but the synchronizer correctly captures the async change within one DTPCLK cycle. No missing blocking scheme -- the synchronizer is the scheme.} \
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
# "cdc_fifo_gray_clearable" / "cdc_reset_ctrlr") live in dtp.vcrdc.opensource_ip.waiver.tcl.  The waivers in this
# section target Module == "jtag2axi" or Module == "prim_fifo_sync" (OpenTitan primitive used by jtag2axi).
# Equivalent CDC convergence violation at the same boundary is waived as
# ocah_dtp_CDC_COHERENCY_RECONV_SEQ_jtag2axi_axi_state_fsm in vccdc/inputs/waivers/general_waiver.tcl.
#
# Filter ORDER matters: VC Static credits the first matching waiver.  Per-register
# waivers are placed before broader DestObject globs so each named register
# carries its own justification.
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

# RDC:2568 — current_addr_tclk (smc_jtag2axi): per-read AXI read address
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_addr_tclk} \
    -comment {RDC:2568 — jtag2axi (smc_jtag2axi): cdc_fifo_gray_clearable_ar half_b (rst_n_i, DTPCLK) state reaches current_addr_tclk (no reset, JTAG_TCK). This register holds the current AXI read address; it has no reset because it is loaded from each JTAG command. The clearable protocol guarantees no AXI read is active during reset, so stale address content cannot affect any in-flight transaction. FSM reloads it at the start of each new read.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_addr_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:2308 — current_incr_series_addr_tclk (sep_otp_jtag2axi): running incrementing-series address
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_incr_series_addr_tclk} \
    -comment {RDC:2308 — jtag2axi (sep_otp_jtag2axi): cdc_fifo_gray_clearable_aw half_b (rst_n_i, DTPCLK) state reaches current_incr_series_addr_tclk (no reset, JTAG_TCK). This register holds the running AXI address for an incrementing write series; it has no reset because it is loaded from each JTAG command. The clearable protocol guarantees no AXI transaction is active during reset, so stale address content cannot be forwarded. FSM reloads it before any new series begins.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_incr_series_addr_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:2318 — current_tx_stale_tclk (smc_jtag2axi): per-transaction stale/abort flag
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_current_tx_stale_tclk} \
    -comment {RDC:2318 — jtag2axi (smc_jtag2axi): CDC reset controller half_b (rst_n_i, DTPCLK) state reaches current_tx_stale_tclk (no reset, JTAG_TCK). This register marks whether the current AXI transaction has stalled; it has no reset because the TCK FSM manages it per-transaction. The clearable protocol guarantees no transaction is active during reset; stale content cannot affect any in-flight operation. FSM clears this at the start of each new transaction.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*current_tx_stale_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1936 — last_single_op_was_read_tclk (smc_otp_jtag2axi): inter-transaction status
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_last_single_op_was_read_tclk} \
    -comment {RDC:1936 — jtag2axi (smc_otp_jtag2axi): CDC reset controller half_a (rst_n_i, DTPCLK) state reaches last_single_op_was_read_tclk (no reset, JTAG_TCK). This TCK-domain status register tracks the last AXI transaction type; it has no reset because its value is irrelevant between transactions and the clearable protocol guarantees no AXI transaction is active during reset. The FSM reinitialises it on the first post-reset transaction.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*last_single_op_was_read_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1315 — orphan_r_count_q / orphan_b_count_q (smc_jtag2axi): DTPCLK outstanding-response counters
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_orphan_count_q} \
    -comment {RDC:1315 — jtag2axi (smc_jtag2axi): cdc_reset_ctrlr half_a data_src_q (trst_n_combined/tlr_reset, JTAG_TCK) reaches orphan_r_count_q / orphan_b_count_q (rst_n_i, DTPCLK). These counters track in-flight AXI R/B beats across the clearable CDC; they are asynchronously reset by rst_n_i on the DTPCLK side. The 4-phase clearable protocol isolates both domains before reset-induced CDC state can be consumed, so a stale count cannot affect an in-flight transaction.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*orphan_*_count_q*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 01-09-2026 18:10:00 }

# RDC:1953 — DTPCLK-side AXI fall-through FIFOs and outstanding/discard state
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_dtpclk_ft_and_outstanding} \
    -comment {RDC:1953 — jtag2axi (smc_jtag2axi): cdc_reset_ctrlr half_a data_src_q (trst_n_combined/tlr_reset, JTAG_TCK) reaches DTPCLK-side fall-through FIFO pointers (*_ft_reg/i_fifo/*_pointer_q), outstanding counters (*_outstanding_q), and dst_clear/discard response flags. All are asynchronously reset by rst_n_i. The 4-phase clearable protocol isolates the AXI CDC before these registers can consume reset-induced source state.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND ((DestObject =~ "*_ft_reg*") OR (DestObject =~ "*_outstanding_q*") OR (DestObject =~ "*dst_clear_pending*") OR (DestObject =~ "*discard_rsp_q*"))} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 01-09-2026 18:10:00 }

# RDC:1989 — remaining TCK-domain command-processor *_tclk registers
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
    -comment {RDC:1989 — jtag2axi command processor: DTPCLK-side clearable reset controller half_b data_src_q (rst_n_i) reaches TCK-domain *_tclk command-state registers (trst_n_combined/tlr_reset). The 4-phase clearable protocol forces the destination side into isolation when rst_n_i asserts, so the TCK-domain command processor observes safe isolated values. All TCK-side registers are also independently reset by trst_n_combined/tlr_reset. Catches the remaining *_tclk register patterns beyond the four register-specific waivers above (axi_state_q_tclk, current_custom_wstrb_tclk, current_data_tclk, current_is_series_data_with_error_status_op_tclk, current_jtag_size_tclk, current_op_tclk, current_tx_is_from_single_buffer_tclk, current_tx_is_series_read_tclk, current_use_custom_wstrb_tclk, last_read_data_tclk, last_single_op_status_tclk, plain_reads_pending_tclk, series_errstat_pending_tclk, series_reads_in_flight_tclk, shift_register_q_tclk, single_op_pending_tclk, single_tx_req_valid_tclk, sticky_axi_status_tclk).} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*_tclk*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

#-----------------------------------------------------------------------------------------------------------------------
# jtag2axi and prim_fifo_sync: internal FIFO storage (no-reset by design)
#-----------------------------------------------------------------------------------------------------------------------

# RDC:1701 — prim_fifo_sync read pointer vs storage (smc_otp_jtag2axi series_request_fifo)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_prim_fifo_sync_rptr_storage} \
    -comment {RDC:1701 — prim_fifo_sync (smc_otp_jtag2axi series_request_fifo): read pointer rptr_wrap_cnt_q (has reset) is visible at storage array (no reset), both in JTAG_TCK domain. prim_fifo_sync intentionally omits storage reset: pointer reset declares the FIFO empty (rptr==wptr), making all storage entries invalid without clearing them. No stale entry can be read because the occupancy is tracked by pointers alone. Standard FIFO design; no real corruption path.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "prim_fifo_sync") AND (DestObject =~ "*storage*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1807 — jtag2axi series_rsp_fifo storage (smc_jtag2axi B-channel response)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_series_rsp_fifo_storage} \
    -comment {RDC:1807 — jtag2axi (smc_jtag2axi): cdc_fifo_gray_clearable_b half_a (rst_n_i, DTPCLK) reset state reaches TCK-domain series_rsp_fifo storage (no reset). The 4-phase clearable-reset protocol ensures B-channel FIFO is drained before the reset state change affects active logic; storage reset is omitted by design (pointer reset declares FIFO empty). Equivalent to the prim_fifo_sync storage waiver above.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*series_rsp_fifo*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# RDC:1708 — jtag2axi series_request_fifo storage (smc_otp_jtag2axi A-channel request)
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_series_request_fifo_storage} \
    -comment {RDC:1708 — jtag2axi (smc_otp_jtag2axi): series_request_fifo_din_tclk.addr (no reset, JTAG_TCK) drives series_request_fifo storage (no reset, JTAG_TCK). Both are in the same clock domain. FIFO storage has no reset by design; FIFO pointers are reset on TRST/TLR declaring all entries invalid without requiring storage clearance. Same prim_fifo_sync design rationale as RDC:1701. No cross-domain boundary; no real corruption path.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*series_request_fifo*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 17-05-2026 21:00:00 }

# PULP stream_fork outstanding-state flops inside jtag2axi (inp_state_q /
# gen_oup_state[*].oup_state_q). Attributed to Module==jtag2axi, reset by rst_n_i.
waive_violation -add {ocah_dtp_RDC_CORRUPT_OBSERVED_jtag2axi_write_fork_state} \
    -comment {jtag2axi: PULP stream_fork u_write_fork inp_state_q / gen_oup_state[*].oup_state_q (DTPCLK, rst_n_i) observe TCK-side cdc_reset_ctrlr half_a data_src_q (trst_n_combined/tlr_reset). The 4-phase clearable protocol isolates the AXI CDC before these handshake flops can consume reset-induced source state; each dest is independently reset by rst_n_i.} \
    -filter {(Tag == "RDC_CORRUPT_OBSERVED") AND (Module == "jtag2axi") AND (DestObject =~ "*u_write_fork*")} \
    -app { rdc } -tag { RDC_CORRUPT_OBSERVED } -user { bmelton } -timestamp { 01-09-2026 18:12:00 }
