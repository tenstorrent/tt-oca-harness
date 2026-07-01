// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`define TT_ASSERT_I(__name, __prop) \
  __name: assert (__prop)           \
    else begin                      \
      `TT_ASSERT_ERROR(__name)      \
    end

`define TT_ASSERT_INIT(__name, __prop)  \
  initial begin                         \
    __name: assert (__prop)             \
      else begin                        \
        `TT_ASSERT_ERROR(__name)        \
      end                               \
  end                                   \

`define TT_ASSERT_FINAL(__name, __prop)                                      \
  final begin                                                                \
    __name: assert (__prop || $test$plusargs("disable_assert_final_checks")) \
      else begin                                                             \
        `TT_ASSERT_ERROR(__name)                                             \
      end                                                                    \
  end

`define TT_ASSERT_AT_RESET(__name, __prop, __rst = `TT_ASSERT_DEFAULT_RST)  \
  __name: assert property (@(posedge __rst) $isunknown(__rst) || (__prop))  \
    else begin                                                              \
      `TT_ASSERT_ERROR(__name)                                              \
    end

`define TT_ASSERT_AT_RESET_AND_FINAL(__name, __prop, __rst = `TT_ASSERT_DEFAULT_RST) \
    `TT_ASSERT_AT_RESET(AtReset_``__name``, __prop, __rst)                           \
    `TT_ASSERT_FINAL(Final_``__name``, __prop)

`define TT_ASSERT(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))                \
    else begin                                                                                    \
      `TT_ASSERT_ERROR(__name)                                                                    \
    end

`define TT_ASSERT_NEVER(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) not (__prop))                  \
    else begin                                                                                          \
      `TT_ASSERT_ERROR(__name)                                                                          \
    end

`define TT_ASSERT_KNOWN(__name, __sig, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  `TT_ASSERT(__name, !$isunknown(__sig), __clk, __rst)

`define TT_COVER(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  __name: cover property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop));

`define TT_ASSUME(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST) \
  __name: assume property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))                \
    else begin                                                                                    \
      `TT_ASSERT_ERROR(__name)                                                                    \
    end

`define TT_ASSUME_I(__name, __prop) \
  __name: assume (__prop)           \
    else begin                      \
      `TT_ASSERT_ERROR(__name)      \
    end

`define TT_ASSERT_ZERO_ONEHOT(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)     \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) ((((__prop) & ((__prop) - 'h1)) == 'h0)))  \
    else begin                                                                                                      \
      `TT_ASSERT_ERROR(__name)                                                                                      \
    end