// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Shell each assert define for Synthesis

`define TT_ASSERT_AT_RESET_AND_FINAL(__name, __prop, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_ASSERT_AT_RESET(__name, __prop, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_ASSERT_FINAL(__name, __prop)
`define TT_ASSERT_I(__name, __prop)
`define TT_ASSERT_INIT_NET(__name, __prop)
`define TT_ASSERT_INIT(__name, __prop)
`define TT_ASSERT_KNOWN(__name, __sig, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_ASSERT_NEVER(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_ASSERT(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_ASSUME_I(__name, __prop)
`define TT_ASSUME(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)
`define TT_COVER(__name, __prop, __clk = `TT_ASSERT_DEFAULT_CLK, __rst = `TT_ASSERT_DEFAULT_RST)
