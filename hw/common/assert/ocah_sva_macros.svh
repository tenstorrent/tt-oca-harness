// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Two-state protocol-checker assertion macros.
//
// `OCAH_ASSERT and `OCAH_ASSERT_I (ocah_assert_standard_macros.svh) compile
// out whenever OCAH_INC_ASSERT is undefined, which includes every Verilator
// build. The macros here are live wherever SIMULATION is defined, which the
// DV profiles set for every simulator; lint and synthesis do not set it, so
// they expand to nothing there. Verilator evaluates them when the build
// passes --assert and drops them otherwise. They carry rules whose operands are two-state
// safe (value compares, implications, $stable, $past, bounded repetition); a
// rule that needs four-state operands ($isunknown, X-propagation) stays on
// `OCAH_ASSERT so it runs only on a four-state simulator.
//
// Failure reporting goes through `OCAH_ASSERT_ERROR (ocah_assert.svh):
// uvm_report_error under UVM, $error otherwise. __rst is an active-high "in
// reset" expression, matching the `OCAH_ASSERT disable convention.

`ifndef OCAH_SVA_MACROS_SVH
`define OCAH_SVA_MACROS_SVH

`include "ocah_assert.svh"

`ifdef SIMULATION
`define OCAH_SVA_ASSERT(__name, __prop, __clk, __rst)                                 \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))  \
    else begin                                                                       \
      `OCAH_ASSERT_ERROR(__name)                                                     \
    end

`define OCAH_SVA_ASSERT_I(__name, __prop) \
  __name: assert (__prop)                 \
    else begin                            \
      `OCAH_ASSERT_ERROR(__name)          \
    end
`else
`define OCAH_SVA_ASSERT(__name, __prop, __clk, __rst)
`define OCAH_SVA_ASSERT_I(__name, __prop)
`endif

`endif  // OCAH_SVA_MACROS_SVH
