// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Property macros for formal property modules (hw/common/dv/docs/formal-property-style.adoc).
//
// The bodies expand only when FORMAL is defined, which every formal backend launch script sets;
// simulation, lint and synthesis compiles see empty macros, so a property module can sit on any
// filelist. Expansion does not depend on SYNTHESIS: the open-source frontend keeps SYNTHESIS
// defined so that simulation-only assertions in vendored RTL stay out of the formal model.
//
// __expr is a boolean expression sampled at posedge __clk, disabled while the active-low __rst_n
// is low. Each property carries its own clocking event: the open-source frontend has no default
// clocking and accepts neither sequence operators (|->, |=>, ##) nor the $stable, $rose, $fell,
// $isunknown and $onehot0 functions; the expression helpers below cover the sampled-value
// functions with $past, which the frontend does accept.

`ifndef OCAH_FV_MACROS_SVH
`define OCAH_FV_MACROS_SVH

// verilog_format: off
`ifdef FORMAL
`define OCAH_FV_ASSERT(__name, __expr, __clk, __rst_n) \
  __name : assert property (@(posedge __clk) disable iff (!(__rst_n)) (__expr));

`define OCAH_FV_ASSUME(__name, __expr, __clk, __rst_n) \
  __name : assume property (@(posedge __clk) disable iff (!(__rst_n)) (__expr));

`define OCAH_FV_COVER(__name, __expr, __clk, __rst_n) \
  __name : cover property (@(posedge __clk) disable iff (!(__rst_n)) (__expr));

// Reset held in the initial state: the declaration initializer marks the first cycle and the
// assumption pins reset low there, so every $past sampled after reset release reads a value that
// exists in the trace.
`define OCAH_FV_INITIAL_RESET(__clk, __rst_n) \
  logic ocah_fv_first_cycle_q = 1'b1; \
  always_ff @(posedge __clk) ocah_fv_first_cycle_q <= 1'b0; \
  asm_initial_reset : assume property (@(posedge __clk) !ocah_fv_first_cycle_q || !(__rst_n));
`else
`define OCAH_FV_ASSERT(__name, __expr, __clk, __rst_n)
`define OCAH_FV_ASSUME(__name, __expr, __clk, __rst_n)
`define OCAH_FV_COVER(__name, __expr, __clk, __rst_n)
`define OCAH_FV_INITIAL_RESET(__clk, __rst_n)
`endif

// Expression helpers. __sig of the edge helpers is a single bit.
`define OCAH_FV_IMPLIES(__ante, __cons) (!(__ante) || (__cons))
`define OCAH_FV_STABLE(__sig) ((__sig) == $past(__sig))
`define OCAH_FV_ROSE(__sig) ((__sig) && !$past(__sig))
`define OCAH_FV_FELL(__sig) (!(__sig) && $past(__sig))
// verilog_format: on

`endif  // OCAH_FV_MACROS_SVH
