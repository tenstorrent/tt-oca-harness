// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef OCAH_REGISTERS_SVH
`define OCAH_REGISTERS_SVH

// Flip-flop macros. Names and argument order follow the current pulp-platform
// common_cells registers.svh, with an OCAH_ prefix so they coexist with any version of
// those macros in an integrating design. Every argument is explicit: there is no default
// clock or reset.
//
//   __q        register
//   __d        next value
//   __load     enable; the register holds its value while it is low
//   __clear    synchronous clear to __rst_val, taking priority over __load
//   __rst_val  value taken in reset
//   __clk      clock, rising edge
//   __rst_n    active-low reset, asynchronous in OCAH_FF*, synchronous in OCAH_FF*SRN

// Asynchronous active-low reset.
`define OCAH_FF(__q, __d, __rst_val, __clk, __rst_n) \
  always_ff @(posedge (__clk) or negedge (__rst_n)) begin \
    if (!(__rst_n)) begin                                 \
      __q <= (__rst_val);                                 \
    end else begin                                        \
      __q <= (__d);                                       \
    end                                                   \
  end

// Asynchronous active-low reset, with load enable.
`define OCAH_FFL(__q, __d, __load, __rst_val, __clk, __rst_n) \
  always_ff @(posedge (__clk) or negedge (__rst_n)) begin     \
    if (!(__rst_n)) begin                                     \
      __q <= (__rst_val);                                     \
    end else if (__load) begin                                \
      __q <= (__d);                                           \
    end                                                       \
  end

// Asynchronous active-low reset, with synchronous clear.
`define OCAH_FFARNC(__q, __d, __clear, __rst_val, __clk, __rst_n) \
  `ifndef VERILATOR                                               \
  /``* synopsys sync_set_reset `"__clear`" *``/                   \
  `endif                                                          \
  always_ff @(posedge (__clk) or negedge (__rst_n)) begin         \
    if (!(__rst_n)) begin                                         \
      __q <= (__rst_val);                                         \
    end else if (__clear) begin                                   \
      __q <= (__rst_val);                                         \
    end else begin                                                \
      __q <= (__d);                                               \
    end                                                           \
  end

// Asynchronous active-low reset, with synchronous clear and load enable.
`define OCAH_FFLARNC(__q, __d, __load, __clear, __rst_val, __clk, __rst_n) \
  `ifndef VERILATOR                                                        \
  /``* synopsys sync_set_reset `"__clear`" *``/                            \
  `endif                                                                   \
  always_ff @(posedge (__clk) or negedge (__rst_n)) begin                  \
    if (!(__rst_n)) begin                                                  \
      __q <= (__rst_val);                                                  \
    end else if (__clear) begin                                            \
      __q <= (__rst_val);                                                  \
    end else if (__load) begin                                             \
      __q <= (__d);                                                        \
    end                                                                    \
  end

// Synchronous active-low reset.
`define OCAH_FFSRN(__q, __d, __rst_val, __clk, __rst_n) \
  always_ff @(posedge (__clk)) begin                    \
    if (!(__rst_n)) begin                               \
      __q <= (__rst_val);                               \
    end else begin                                      \
      __q <= (__d);                                     \
    end                                                 \
  end

// Synchronous active-low reset, with load enable.
`define OCAH_FFLSRN(__q, __d, __load, __rst_val, __clk, __rst_n) \
  always_ff @(posedge (__clk)) begin                             \
    if (!(__rst_n)) begin                                        \
      __q <= (__rst_val);                                        \
    end else if (__load) begin                                   \
      __q <= (__d);                                              \
    end                                                          \
  end

// No reset.
`define OCAH_FFNR(__q, __d, __clk) \
  always_ff @(posedge (__clk)) begin \
    __q <= (__d);                    \
  end

// No reset, with load enable.
`define OCAH_FFLNR(__q, __d, __load, __clk) \
  always_ff @(posedge (__clk)) begin        \
    if (__load) begin                       \
      __q <= (__d);                         \
    end                                     \
  end

`endif  // OCAH_REGISTERS_SVH
