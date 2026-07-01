// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef TT_ASSERT_SV
`define TT_ASSERT_SV

// Default clock and reset signals for assertion macros
`define TT_ASSERT_DEFAULT_CLK i_clk
`define TT_ASSERT_DEFAULT_RST !i_reset_n

// Helper macro to convert a block of code into a Verilog string
`define TT_STRINGIFY(__x) `"__x`"

// TT_ASSERT_ERROR logs an error message with either `uvm_error or with $error.
`define TT_ASSERT_ERROR(__name)                                                                                      \
`ifdef UVM                                                                                                           \
  uvm_pkg::uvm_report_error("ASSERT FAILED", `TT_STRINGIFY(__name), uvm_pkg::UVM_NONE, `__FILE__, `__LINE__, "", 1); \
`else                                                                                                                \
  $error("%0t: (%0s:%0d) [%m] [ASSERT FAILED] %0s", $time, `__FILE__, `__LINE__, `TT_STRINGIFY(__name));             \
`endif


// Helper macros are generally defined within "implementation headers." Despite having the same functionality in each case (apart from the dummy variant), they must be compatible with the corresponding tools.
// For tools that incorporate assertions in some form, INC_ASSERT is also defined. This can be used to conceal signal definitions exclusively utilized for assertions.
// The macros that are supported include:
// TT_ASSERT_I: An immediate assertion. Be aware that such assertions are susceptible to simulation glitches.
// TT_ASSERT_INIT: An assertion within the initial block. This is useful for tasks like checking parameters.
// TT_ASSERT_FINAL: An assertion within the final block. This can be applied to ensure that queues are empty at the simulation's conclusion, all credits have been returned, and state machines are idle.
// TT_ASSERT_AT_RESET: An assertion just prior to a reset. This is suitable for verifying sum-like properties that are reset. Note that if your simulation doesn’t conclude with a reset, this property won’t be checked at the simulation’s end; instead, use TT_ASSERT_AT_RESET_AND_FINAL if you also want the property checked at that time.
// TT_ASSERT_AT_RESET_AND_FINAL: An assertion just prior to a reset and within the final block. This is useful for checking sum-like properties before every reset and at the simulation’s end.
// TT_ASSERT: Direct assertion of a concurrent property. It can be invoked as an item within a module (or interface) body.
// Note: We use (__rst !== '0) in the disable iff statements rather than (__rst == '1). This ensures that the assertion is properly disabled when the reset is X at the simulation’s start. In such cases, (reset == '1) would not disable the assertion.
// TT_ASSERT_NEVER: Assert that a concurrent property NEVER occurs.
// TT_ASSERT_KNOWN: Assert that a signal possesses a known value (with each bit being either '0' or '1') following a reset. It can be invoked as an item within a module (or interface) body.
// TT_COVER: Cover a concurrent property.
// TT_ASSUME: Assume a concurrent property.
// TT_ASSUME_I: Assume an immediate property.

`ifdef SYNTHESIS
  `include "tt_assert_dummy_macros.svh"
`elsif VERILATOR
  `include "tt_assert_dummy_macros.svh"
`elsif TARGET_VERILATOR
  `include "tt_assert_dummy_macros.svh"
`elsif NO_TT_ASSERT
  `include "tt_assert_dummy_macros.svh"
`else
  `include "tt_assert_standard_macros.svh"
  `define INC_ASSERT
`endif
//////////////////////////////
// Complex assertion macros //
//////////////////////////////

// Assert that signal is an active-high pulse with pulse length of 1 clock cycle
`define TT_ASSERT_PULSE(__name, __sig, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  `TT_ASSERT(__name, $rose(__sig) |=> !(__sig), __clk, __rst)

// Assert that a property is true only when an enable signal is set.
`define TT_ASSERT_IF(__name, __prop, __enable, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  `TT_ASSERT(__name, (__enable) |-> (__prop), __clk, __rst)

// Assert that signal has a known value (each bit is either '0' or '1') after reset if enable is set
`define TT_ASSERT_KNOWN_IF(__name, __sig, __enable, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  `TT_ASSERT_KNOWN(__name``KnownEnable, __enable, __clk, __rst)                                                     \
  `TT_ASSERT_IF(__name, !$isunknown(__sig), __enable, __clk, __rst)

`endif  // TT_ASSERT_SV
