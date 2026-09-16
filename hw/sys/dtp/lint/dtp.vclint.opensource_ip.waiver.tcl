# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

# For waiving violations on open-source 3rd party IP

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
#=======================================================================================================================

# iDMA

# PULP AXI
# Prefix for Module filters; set by the flow's post_proc script.
# Defaults to empty string so waivers still match unprefixed module names.
if {![info exists PREFIX]} {
    set PREFIX ""
}
# Substitute the literal ${PREFIX} token in a -filter expression with $PREFIX's
# value. Uses string map rather than brace interpolation so that $clog2, bus
# indices like [i], and embedded quotes inside the filter are preserved verbatim.
proc apply_prefix {filter} {
    return [string map [list {${PREFIX}} $::PREFIX] $filter]
}

waive_violation -add {W146_cdc_fifo_gray_dst}  -comment {Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cdc_fifo_gray_dst")}]  -app { lint } -tag { W146 } -user { nbetik } -timestamp { 27-02-2026 15:46:58 }
waive_violation -add {W146_cdc_fifo_gray_src}  -comment {Common cells component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cdc_fifo_gray_src")}]  -app { lint } -tag { W146 } -user { nbetik } -timestamp { 27-02-2026 15:41:45 }
waive_violation -add {W146_cdc_fifo_gray_src_clearable}  -comment {Third-party common_cells clearable CDC FIFO. Positional parameter passing to gray_to_binary/binary_to_gray primitives is standard style in this upstream component; renaming to named association is not sustainable.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cdc_fifo_gray_src_clearable")}]  -app { lint } -tag { W146 } -user { bmelton } -timestamp { 14-05-2026 16:13:00 }
waive_violation -add {W146_cdc_fifo_gray_dst_clearable}  -comment {Third-party common_cells clearable CDC FIFO. Same rationale as cdc_fifo_gray_src_clearable.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}cdc_fifo_gray_dst_clearable")}]  -app { lint } -tag { W146 } -user { bmelton } -timestamp { 14-05-2026 16:13:00 }
waive_violation -add {W193_axi_lite_mailbox_slave}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_lite_mailbox_slave")}]  -app { lint } -tag { W193 } -user { nbetik } -timestamp { 27-02-2026 15:42:58 }
waive_violation -add {W193_axi_lite_to_apb}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_lite_to_apb")}]  -app { lint } -tag { W193 } -user { nbetik } -timestamp { 27-02-2026 15:43:44 }
waive_violation -add {W193_axi_lite_from_mem}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_lite_from_mem")}]  -app { lint } -tag { W193 } -user { nbetik } -timestamp { 27-02-2026 15:44:14 }
waive_violation -add {W193_axi_isolate_inner}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_isolate_inner")}]  -app { lint } -tag { W193 } -user { nbetik } -timestamp { 27-02-2026 15:44:41 }
waive_violation -add {NoGenLabel-ML_axi_isolate}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_isolate")}]  -app { lint } -tag { NoGenLabel-ML } -user { nbetik } -timestamp { 27-02-2026 15:45:42 }
waive_violation -add {NoGenLabel-ML_axi_err_slv}  -comment {PULP axi component. Lint category is for visual cleanliness only. Created by nbetik on 27-Feb-2026}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_err_slv")}]  -app { lint } -tag { NoGenLabel-ML } -user { nbetik } -timestamp { 27-02-2026 15:46:25 }

# common_cells
waive_violation -add {STARC05-2_3_4_2_addr_decode_dync}  -comment {Third-party common_cells component (deps/common_cells). The initial begin block contains simulation-only parameter assumption checks (ASSUME_I macro). This is a standard OpenHW/PULP idiom; modifying upstream code is not sustainable.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}addr_decode_dync")}]  -app { lint } -tag { STARC05-2.3.4.2 } -user { bmelton } -timestamp { 14-05-2026 16:05:00 }
waive_violation -add {PragmaComments_cdc_fifo_gray_clearable}  -comment {Third-party common_cells FFLARNC macro emits a synopsys sync_set_reset pragma to guide synthesis tool register inference. This is standard PULP CDC FIFO style; the pragma is necessary for correct synthesis of the clearable gray-pointer register.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module =~ "${PREFIX}cdc_fifo_gray_*_clearable")}]  -app { lint } -tag { PragmaComments-ML } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
waive_violation -add {W240_spill_register_flushable}  -comment {Third-party common_cells spill_register_flushable. clk_i, rst_ni, and flush_i are declared but not read in this instantiation context because the flushable variant reduces to a passthrough when flush is unused. Upstream component; not modifiable.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}spill_register_flushable")}]  -app { lint } -tag { W240 } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
waive_violation -add {W240_fifo_v3_testmode}  -comment {Third-party common_cells fifo_v3. testmode_i is a test-mode clock-gating bypass input that is tied off (not driven) in the DTP integration; test insertion is handled at a higher level.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}fifo_v3")}]  -app { lint } -tag { W240 } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
waive_violation -add {W240_axi_lite_to_axi}  -comment {Third-party PULP axi_lite_to_axi. mst_resp_i is a full AXI response struct; fields b.id, b.user, r.id, r.last, r.user are AXI4 extensions not used in the AXI4-Lite context.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_lite_to_axi")}]  -app { lint } -tag { W240 } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
waive_violation -add {W240_axi_lite_mux_test}  -comment {Third-party PULP axi_lite_mux. test_i is a DFT test-mode input tied off at the DTP integration level.}  -filter [apply_prefix {(Goal == "lint_rtl_enhanced") AND (Module == "${PREFIX}axi_lite_mux")}]  -app { lint } -tag { W240 } -user { bmelton } -timestamp { 14-05-2026 16:41:00 }
