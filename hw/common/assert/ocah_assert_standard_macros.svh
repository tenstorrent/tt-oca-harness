// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// OCAH common assertion macro bodies (PULP-style single source).
//
// Every macro is always defined; each body is guarded by `ifdef OCAH_INC_ASSERT so
// that under synthesis / Verilator (where OCAH_INC_ASSERT is not defined) the macros
// expand to nothing. OCAH_INC_ASSERT is defined by ocah_assert.svh, which includes
// this file. This replaces the former standard/dummy macro-swap.

`define OCAH_ASSERT_I(__name, __prop) \
`ifdef OCAH_INC_ASSERT                     \
  __name: assert (__prop)            \
    else begin                       \
      `OCAH_ASSERT_ERROR(__name)     \
    end                              \
`endif

`define OCAH_ASSERT_INIT(__name, __prop) \
`ifdef OCAH_INC_ASSERT                        \
  initial begin                          \
    __name: assert (__prop)              \
      else begin                         \
        `OCAH_ASSERT_ERROR(__name)       \
      end                                \
  end                                    \
`endif

`define OCAH_ASSERT_INIT_NET(__name, __prop) \
`ifdef OCAH_INC_ASSERT                            \
  initial begin                              \
    // Nets are assigned after the initial block in some simulators; delay 1ps  \
    // so the value is checked after the assignment completes.                   \
    #1ps;                                    \
    __name: assert (__prop)                  \
      else begin                             \
        `OCAH_ASSERT_ERROR(__name)           \
      end                                    \
  end                                        \
`endif

`define OCAH_ASSERT_FINAL(__name, __prop)                                      \
`ifdef OCAH_INC_ASSERT                                                              \
  final begin                                                                  \
    __name: assert (__prop || $test$plusargs("disable_assert_final_checks"))   \
      else begin                                                               \
        `OCAH_ASSERT_ERROR(__name)                                             \
      end                                                                      \
  end                                                                          \
`endif

`define OCAH_ASSERT_AT_RESET(__name, __prop, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                              \
  __name: assert property (@(posedge __rst) $isunknown(__rst) || (__prop))     \
    else begin                                                                 \
      `OCAH_ASSERT_ERROR(__name)                                               \
    end                                                                        \
`endif

`define OCAH_ASSERT_AT_RESET_AND_FINAL(__name, __prop, __rst = `OCAH_ASSERT_DEFAULT_RST) \
    `OCAH_ASSERT_AT_RESET(AtReset_``__name``, __prop, __rst)                           \
    `OCAH_ASSERT_FINAL(Final_``__name``, __prop)

// Keep macro headers on one physical line for synthesis elaboration.
// verilog_format: off
`define OCAH_ASSERT(__name, __prop, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                                                 \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))                \
    else begin                                                                                    \
      `OCAH_ASSERT_ERROR(__name)                                                                  \
    end                                                                                           \
`endif

`define OCAH_ASSERT_NEVER(__name, __prop, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                                                       \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) not (__prop))                  \
    else begin                                                                                          \
      `OCAH_ASSERT_ERROR(__name)                                                                        \
    end                                                                                                 \
`endif

`define OCAH_ASSERT_KNOWN(__name, __sig, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
  `OCAH_ASSERT(__name, !$isunknown(__sig), __clk, __rst)

`define OCAH_COVER(__name, __prop, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                                                 \
  __name: cover property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop));                \
`endif

`define OCAH_ASSUME(__name, __prop, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                                                 \
  __name: assume property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))                \
    else begin                                                                                    \
      `OCAH_ASSERT_ERROR(__name)                                                                  \
    end                                                                                           \
`endif

`define OCAH_ASSUME_I(__name, __prop) \
`ifdef OCAH_INC_ASSERT                     \
  __name: assume (__prop)            \
    else begin                       \
      `OCAH_ASSERT_ERROR(__name)     \
    end                              \
`endif

`define OCAH_ASSERT_ZERO_ONEHOT(__name, __prop, __clk = `OCAH_ASSERT_DEFAULT_CLK, __rst = `OCAH_ASSERT_DEFAULT_RST) \
`ifdef OCAH_INC_ASSERT                                                                                                   \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) ((((__prop) & ((__prop) - 'h1)) == 'h0))) \
    else begin                                                                                                      \
      `OCAH_ASSERT_ERROR(__name)                                                                                    \
    end                                                                                                             \
`endif
// verilog_format: on
