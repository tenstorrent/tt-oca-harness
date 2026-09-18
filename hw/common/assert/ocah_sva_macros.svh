// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Two-state protocol-checker assertion macros.
//
// `OCAH_ASSERT and `OCAH_ASSERT_I (ocah_assert_standard_macros.svh) compile
// out whenever OCAH_INC_ASSERT is undefined, which includes every Verilator
// build. The macros here are live wherever SIMULATION is defined, which the
// DV profiles set for every simulator, and wherever FORMAL is defined, which
// every formal backend script sets (hw/common/dv/docs/formal-property-style.adoc);
// lint and synthesis define neither, so they expand to nothing there. Verilator
// evaluates them when the build passes --assert and drops them otherwise. They
// carry rules whose operands are two-state safe (value compares, implications,
// $stable, $past, bounded repetition); a rule that needs four-state operands
// ($isunknown, X-propagation) stays on `OCAH_ASSERT so it runs only on a
// four-state simulator.
//
// `OCAH_SVA_RULE and `OCAH_RULE take a first argument that selects the kind
// of the concurrent check: an assumption when it is set, an assertion
// otherwise. A protocol checker routes each rule through one of them with the
// parameter of the side that drives the rule's signals, so one instance
// asserts the design's side and assumes the environment's. `OCAH_SVA_RULE is
// the two-state form over the macros of this file; `OCAH_RULE is the
// four-state form over `OCAH_ASSERT and `OCAH_ASSUME (ocah_assert.svh), live
// where OCAH_INC_ASSERT is. The check sits in a generate block named
// gen_<name>, so its hierarchical path gains that level. Immediate checks have
// no selected form: a statement label is unique within its procedural block,
// and a simulator treats an immediate assume as an assert.
//
// Failure reporting goes through `OCAH_ASSERT_ERROR (ocah_assert.svh):
// uvm_report_error under UVM, $error otherwise. __rst is an active-high "in
// reset" expression, matching the `OCAH_ASSERT disable convention.

`ifndef OCAH_SVA_MACROS_SVH
`define OCAH_SVA_MACROS_SVH

`include "ocah_assert.svh"

`ifdef SIMULATION
`define OCAH_SVA_MACROS_LIVE
`elsif FORMAL
`define OCAH_SVA_MACROS_LIVE
`endif

// verilog_format: off
`ifdef OCAH_SVA_MACROS_LIVE
`define OCAH_SVA_ASSERT(__name, __prop, __clk, __rst)                                 \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))  \
    else begin                                                                       \
      `OCAH_ASSERT_ERROR(__name)                                                     \
    end

`define OCAH_SVA_ASSUME(__name, __prop, __clk, __rst)                                 \
  __name: assume property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))  \
    else begin                                                                       \
      `OCAH_ASSERT_ERROR(__name)                                                     \
    end

`define OCAH_SVA_ASSERT_I(__name, __prop) \
  __name: assert (__prop)                 \
    else begin                            \
      `OCAH_ASSERT_ERROR(__name)          \
    end

`define OCAH_SVA_ASSUME_I(__name, __prop) \
  __name: assume (__prop)                 \
    else begin                            \
      `OCAH_ASSERT_ERROR(__name)          \
    end
`else
`define OCAH_SVA_ASSERT(__name, __prop, __clk, __rst)
`define OCAH_SVA_ASSUME(__name, __prop, __clk, __rst)
`define OCAH_SVA_ASSERT_I(__name, __prop)
`define OCAH_SVA_ASSUME_I(__name, __prop)
`endif

// Concurrent rule whose kind the first argument selects: an assumption when __assume is set, an
// assertion otherwise. A generate item.
`define OCAH_SVA_RULE(__assume, __name, __prop, __clk, __rst) \
  if (__assume) begin : gen_``__name                          \
    `OCAH_SVA_ASSUME(__name, __prop, __clk, __rst)            \
  end else begin : gen_``__name                               \
    `OCAH_SVA_ASSERT(__name, __prop, __clk, __rst)            \
  end

// The four-state form of the same selection over `OCAH_ASSUME and `OCAH_ASSERT.
`define OCAH_RULE(__assume, __name, __prop, __clk, __rst) \
  if (__assume) begin : gen_``__name                      \
    `OCAH_ASSUME(__name, __prop, __clk, __rst)            \
  end else begin : gen_``__name                           \
    `OCAH_ASSERT(__name, __prop, __clk, __rst)            \
  end
// verilog_format: on

`endif  // OCAH_SVA_MACROS_SVH
