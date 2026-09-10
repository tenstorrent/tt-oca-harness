// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef OCAH_ASSERT_SV
`define OCAH_ASSERT_SV

// Default clock and reset signals for assertion macros
`define OCAH_ASSERT_DEFAULT_CLK i_clk
`define OCAH_ASSERT_DEFAULT_RST !i_reset_n

// Helper macro to convert a block of code into a Verilog string
`define OCAH_STRINGIFY(__x) `"__x`"

// OCAH_ASSERT_ERROR logs an error message with either `uvm_error or with $error.
// The UVM call uses the five-argument form: portable across UVM versions
// (uvm-1.1's global uvm_report_error has no context_name /
// report_enabled_checked parameters, and later versions default them).
`define OCAH_ASSERT_ERROR(__name)                                                                                      \
`ifdef UVM                                                                                                           \
  uvm_pkg::uvm_report_error("ASSERT FAILED", `OCAH_STRINGIFY(__name), uvm_pkg::UVM_NONE, `__FILE__, `__LINE__);        \
`else                                                                                                                \
  $error("%0t: (%0s:%0d) [%m] [ASSERT FAILED] %0s", $time, `__FILE__, `__LINE__, `OCAH_STRINGIFY(__name));             \
`endif


// The assertion macro bodies live in ocah_assert_standard_macros.svh. Each body is
// guarded by `ifdef OCAH_INC_ASSERT, so it expands to nothing for tools that do not compile
// assertions in. OCAH_INC_ASSERT is defined below only when assertions are enabled, and can
// also be used by RTL to conceal signal definitions used exclusively by assertions.
// The macros that are supported include:
// OCAH_ASSERT_I: An immediate assertion. Be aware that such assertions are susceptible to simulation glitches.
// OCAH_ASSERT_INIT: An assertion within the initial block. This is useful for tasks like checking parameters.
// OCAH_ASSERT_FINAL: An assertion within the final block. This can be applied to ensure that queues are empty at the simulation's conclusion, all credits have been returned, and state machines are idle.
// OCAH_ASSERT_AT_RESET: An assertion just prior to a reset. This is suitable for verifying sum-like properties that are reset. Note that if your simulation doesn’t conclude with a reset, this property won’t be checked at the simulation’s end; instead, use OCAH_ASSERT_AT_RESET_AND_FINAL if you also want the property checked at that time.
// OCAH_ASSERT_AT_RESET_AND_FINAL: An assertion just prior to a reset and within the final block. This is useful for checking sum-like properties before every reset and at the simulation’s end.
// OCAH_ASSERT: Direct assertion of a concurrent property. It can be invoked as an item within a module (or interface) body.
// Note: We use (__rst !== '0) in the disable iff statements rather than (__rst == '1). This ensures that the assertion is properly disabled when the reset is X at the simulation’s start. In such cases, (reset == '1) would not disable the assertion.
// OCAH_ASSERT_NEVER: Assert that a concurrent property NEVER occurs.
// OCAH_ASSERT_KNOWN: Assert that a signal possesses a known value (with each bit being either '0' or '1') following a reset. It can be invoked as an item within a module (or interface) body.
// OCAH_COVER: Cover a concurrent property.
// OCAH_ASSUME: Assume a concurrent property.
// OCAH_ASSUME_I: Assume an immediate property.

// Define OCAH_INC_ASSERT only when assertions should be compiled in. The macro bodies in
// ocah_assert_standard_macros.svh are each guarded by `ifdef OCAH_INC_ASSERT, so under
// synthesis / Verilator (OCAH_INC_ASSERT undefined) they expand to nothing.
`ifndef SYNTHESIS
`ifndef VERILATOR
`ifndef TARGET_VERILATOR
`ifndef NO_OCAH_ASSERT
`define OCAH_INC_ASSERT
`endif
`endif
`endif
`endif
`include "ocah_assert_standard_macros.svh"
//////////////////////////////
// Complex assertion macros //
//////////////////////////////

// Keep macro headers on one physical line for synthesis elaboration.
// verilog_format: off
// Assert that signal is an active-high pulse with pulse length of 1 clock cycle
`define OCAH_ASSERT_PULSE(__name, __sig, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
  `OCAH_ASSERT(__name, $rose(__sig) |=> !(__sig), __clk, __rst)

// Assert that a property is true only when an enable signal is set.
`define OCAH_ASSERT_IF(__name, __prop, __enable, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
  `OCAH_ASSERT(__name, (__enable) |-> (__prop), __clk, __rst)

// Assert that signal has a known value (each bit is either '0' or '1') after reset if enable is set
`define OCAH_ASSERT_KNOWN_IF(__name, __sig, __enable, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
  `OCAH_ASSERT_KNOWN(__name``KnownEnable, __enable, __clk, __rst)                                                     \
  `OCAH_ASSERT_IF(__name, !$isunknown(__sig), __enable, __clk, __rst)
// verilog_format: on

`endif  // OCAH_ASSERT_SV
