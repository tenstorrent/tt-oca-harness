# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
#
# tclint-disable line-length

# For waiving violations on IP developed by Tenstorrent teams

#=======================================================================================================================
# RULE INFO:
#=======================================================================================================================
# STARC05-1_1_1_1: Module name should be the same as file name
# STARC05-3_3_1_4b: Flop should have async set or reset
# W362: Arithmetic comparison with unequal length
# W164b: LHS of assignment wider than RHS
# STARC05-2_1_3_1: width of function arguments must match width of function inputs
# W553: Different bits of a bus are driven in different combinational blocks
# W391: Module driven by both edges of a clock
# STARC05-2_10_6_1: Possible loss of carry or borrow in addition or subtraction when width of LHS = width of RHS
# W401: Clock generated internally in module
# W193: Empty statement (isolated semicolon)
# W123: Signal is read but not set
# W240: Input declared but not read
# STARC05-1_3_1_3: Async reset used as sync reset or non-reset
# STARC05-2_11_3_1: Sequential and combinational parts of FSM described in same "always" block
# W415: Signal has multiple drivers but is not declared a tri-state
# checkIOPinConnectedToNet: Input pin on an instance is unconnected
#=======================================================================================================================

# Rule Waivers (should be consolidated into new ruleset)
# Prefix for Module filters; set by the flow's post_proc script.
# Defaults to empty string so waivers still match unprefixed module names.
if { ![info exists PREFIX] } {
    set PREFIX ""
}
# Substitute the literal ${PREFIX} token in a -filter expression with $PREFIX's
# value. Uses string map rather than brace interpolation so that $clog2, bus
# indices like [i], and embedded quotes inside the filter are preserved verbatim.
proc apply_prefix { filter } {
    return [string map [list {${PREFIX}} $::PREFIX] $filter]
}

waive_violation -add {ocah_dtp_ReserveName} -comment {Error is meant for flagging reserved words in VHDL -- not relevant to us since we do not intend to port it to VHDL. Created by nbetik on 19-Feb-2025} -filter {(Module =~ "*")} -app { lint } -tag { ReserveName } -user { nbetik } -timestamp { 26-02-2026 14:27:03 }
waive_violation -add {ocah_dtp_STARC05-1_1_1_1} -comment {Not functionally relevant, only important for code readability. Created by nbetik on 26-Feb-2026} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cdc_4phase_src")}] -app { lint } -tag { STARC05-1.1.1.1 } -user { nbetik } -timestamp { 26-02-2026 14:27:45 }
waive_violation -add {ocah_dtp_STARC05-3_3_1_4b_prim_fifo_sync} -comment {prim_fifo_sync storage[] array intentionally has no async reset; pointer/counter state has async reset and gates data validity. OpenTitan-derived primitive, do not modify.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}prim_fifo_sync")}] -app { lint } -tag { STARC05-3.3.1.4b } -user { bmelton } -timestamp { 13-05-2026 15:35:00 }
waive_violation -add {ocah_dtp_STARC05-3_3_1_4b_cla_clock_stop_sync} -comment {jtag_debug_ctrl_reg/u_cla_clock_stop_sync (prim_flop_2sync, TCK-clocked, rst_ni tied 1'b1): synchronizer-only flops for ck_feedthru -> JTAG_TCK CDC capture of cla_clock_stop_i. Reset is intentionally omitted because (a) the module has no TCK-domain reset port available to wire in, and (b) for a status-read CDC synchronizer, metastability resolves within 2 TCK cycles after power-up and the JTAG host always captures cla_clock_stop via Capture-DR (which itself takes >=2 TCK after RTI). The 2 prim_flop instances (u_sync_1, u_sync_2) flag STARC05-3.3.1.4b because rst_ni=1 makes the reset branch unreachable.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}prim_flop") AND (DesignObjHierarchy =~ "*u_cla_clock_stop_sync*")}] -app { lint } -tag { STARC05-3.3.1.4b } -user { bmelton } -timestamp { 17-05-2026 21:55:00 }
waive_violation -add {ocah_dtp_STARC05-2_2_3_3_cross_trigger_matrix_reg} -comment {cross_trigger_matrix_reg is PeakRDL-generated (--cpuif axi4-lite-flat). The multiple non-blocking assignments to axil_arvalid/axil_awvalid/axil_wvalid/axil_prev_was_rd in the AXI4-Lite handshake always_ff are an inherent pattern of the axi4-lite-flat CPU interface template; accept conditions take priority over new-request conditions via SystemVerilog last-assignment semantics. Editing the generated file is not sustainable; the generator does not provide an option to produce a single-assignment equivalent without changing to a struct-based cpuif.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cross_trigger_matrix_reg")}] -app { lint } -tag { STARC05-2.2.3.3 } -user { bmelton } -timestamp { 14-05-2026 16:01:00 }
waive_violation -add {ocah_dtp_STARC05-2_2_3_3_cross_trigger_port_reg} -comment {cross_trigger_port_reg is PeakRDL-generated (--cpuif axi4-lite-flat). Same rationale as cross_trigger_matrix_reg: multiple non-blocking assignments in the AXI4-Lite handshake FSM are inherent to the axi4-lite-flat template and cannot be eliminated without changing the cpuif type.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cross_trigger_port_reg")}] -app { lint } -tag { STARC05-2.2.3.3 } -user { bmelton } -timestamp { 14-05-2026 16:01:00 }
waive_violation -add {ocah_dtp_STARC05-2_2_3_3_jtag2axi_discard_rsp} -comment {Set-then-override-clear is the intended AXI handshake idiom here; restructuring into a single priority chain was considered and rejected in favour of keeping the source readable. Created by gchang on 17-Aug-2026} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}jtag2axi") AND (Clock_Register =~ "*_discard_rsp_q")}] -app { lint } -tag { STARC05-2.2.3.3 } -user { gchang } -timestamp { 17-08-2026 00:00:00 }
waive_violation -add {ocah_dtp_W391_jtag_tck} -comment {jtag_ptap_client_tap_ctrl_i.tck drives flops on both edges by design per IEEE 1149.1: the TAP state machine uses posedge TCK while data registers launch outputs on negedge TCK (dr_scan_select_reg). Mixed-edge TCK usage is fundamental to the JTAG protocol and cannot be eliminated.} -filter {(Goal == "lint_rtl_enhanced") AND (DesignObjSignal =~ "*jtag_ptap_client_tap_ctrl_i.tck")} -app { lint } -tag { W391 } -user { bmelton } -timestamp { 14-05-2026 16:13:00 }
waive_violation -add {ocah_dtp_W481a_prim_util_clog2} -comment {prim_util_pkg _clog2: the for-loop exit condition (v > 0) does not contain the step variable (result), but loop termination is guaranteed by the body (v >>= 1 strictly decreases v toward zero). The result variable is a counter of iterations. This is an OpenTitan-derived primitive; the pattern is intentional.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}dtp") AND (VariableName == "result") AND (Statement == "    for (result = 0; v > 0; result++) begin")}] -app { lint } -tag { W481a } -user { nbetik } -timestamp { 06-08-2026 16:13:00 }
waive_violation -add {ocah_dtp_NoFeedThrus_tck} -comment {jtag_ptap_client_tap_ctrl_i.tck feeds through directly to all downstream host scan/tap-ctrl outputs in dtp.sv. TCK is a JTAG clock that must be routed structurally to every client TAP and scan chain; it is not registered inside DTP. This feedthrough is intentional and required by IEEE 1149.1.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}dtp") AND (SourceNode == "jtag_ptap_client_tap_ctrl_i.tck")}] -app { lint } -tag { NoFeedThrus-ML } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
waive_violation -add {ocah_dtp_NoFeedThrus_tdi} -comment {jtag_ptap_client_tdi_i feeds through directly to jtag_bsr_host_scan_out_o. TDI is the serial scan-in that is passed structurally to the BSR scan chain output when no BSR shift is active; it is not registered inside DTP and is part of the JTAG boundary scan daisy-chain topology required by IEEE 1149.1.} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}dtp") AND (SourceNode == "jtag_ptap_client_tdi_i")}] -app { lint } -tag { NoFeedThrus-ML } -user { bmelton } -timestamp { 14-05-2026 23:55:00 }
waive_violation -add {ocah_dtp_W402b_jtag_trst_n} -comment {jtag_trst_n (output of u_trst_n_and prim_and2) is an intentionally gated reset combining external TRST_N with pwr_on_rst_ni. Feeding this qualified reset to dr_scan_select_reg is the required design. The AND gate primitive makes the gating explicit and glitch-free; the reset domain is safe because pwr_on_rst_ni transitions cleanly before TCK activity begins.} -filter {(Goal == "lint_rtl_enhanced") AND (DesignObjSignal =~ "*jtag_trst_n")} -app { lint } -tag { W402b } -user { bmelton } -timestamp { 14-05-2026 23:55:00 }
waive_violation -add {ocah_dtp_W240_ctm_reg_prot} -comment {cross_trigger_matrix_reg and cross_trigger_port_reg are PeakRDL-generated. s_axil_awprot and s_axil_arprot are required AXI4-Lite port fields but the generated register block does not decode the protection bits (standard for DTP register slaves which do not implement ARPROT-based access control).} -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module =~ "${PREFIX}cross_trigger_*_reg") AND (Signal =~ "*prot*")}] -app { lint } -tag { W240 } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
