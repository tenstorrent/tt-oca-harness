// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Functional-coverage cover-point macro.
//
// `OCAH_COVER (ocah_assert_standard_macros.svh) compiles out whenever
// OCAH_INC_ASSERT is undefined — which includes every Verilator build — so it
// cannot carry functional-coverage collection in the public flow.
// `OCAH_FCOV_COVER stays live in every simulation flow: under Verilator the
// labeled cover property lands in the coverage database as a user point
// (--coverage / --coverage-user), and commercial simulators record the same
// labeled point natively. The emulation view keeps it; only the synthesis
// view (OCAH_DEBUG_LIVE undefined, ocah_assert.svh) compiles it out.
//
// __rst is an active-high "in reset" expression, matching the `OCAH_COVER
// disable convention.

`ifndef OCAH_FCOV_MACROS_SVH
`define OCAH_FCOV_MACROS_SVH

`include "ocah_assert.svh"

`ifdef OCAH_DEBUG_LIVE
`define OCAH_FCOV_COVER(__name, __prop, __clk, __rst) \
    __name: cover property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop));
`else
`define OCAH_FCOV_COVER(__name, __prop, __clk, __rst)
`endif

`endif  // OCAH_FCOV_MACROS_SVH
