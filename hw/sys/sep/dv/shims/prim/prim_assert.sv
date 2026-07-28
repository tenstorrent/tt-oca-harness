// SPDX-License-Identifier: Apache-2.0
//
// prim_assert.sv override for the SEP OSS DV build (Verilator + VCS).
// (Do NOT start a comment line with the word "verilator" -- the lexer treats it as a pragma.)
//
// This restores the OCH `ifndef SYNTHESIS gating of ASSUME/COVER/ASSERT_NEVER (and
// ASSERT under VERILATOR) that lived in hw/common/ot_prim_modifications/rtl/prim_assert.sv
// until the vendoring reorg deleted that override and left the build resolving the
// vendored upstream OpenTitan prim_assert.sv. The upstream copy only no-ops ASSERT
// under VERILATOR and leaves ASSUME unconditional, so with +define+SYNTHESIS the
// unsupported concurrent assumptions still reach Verilator (e.g. kmac sha3pad's
// `##[1:$]` ASSUME -> %Error-UNSUPPORTED). Listing shims/prim ahead of the vendored
// prim incdir (see sep_sim_cfg.toml [build].incdirs, which the runlib prepends before
// the bender filelist) makes `include "prim_assert.sv" resolve here so +define+SYNTHESIS
// neutralizes those assertions, exactly as the OSS build did before the reorg. Only
// prim_assert.sv is shadowed; the `include'd prim_assert_sec_cm.svh / prim_flop_macros.sv
// below resolve from the vendored prim incdir (searched after this dir).
//
// Contains assertions picked out from OT prim_assert.svh such that they can be used in conjunction
// with the TT common_cells assertions.

// FIXME: This is really a hack to get the TT common_cells assertions to work with the OT prim_assert.svh.
// Revisit this in the future.

// Helper macro to convert a block of code into a Verilog string
`define PRIM_STRINGIFY(__x) `"__x`"

// Default clk and rst options to simplify code
`define ASSERT_DEFAULT_CLK clk_i
`define ASSERT_DEFAULT_RST !rst_ni

`ifdef VERILATOR
`define ASSERT(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST)
`define ASSERT_INIT(__name, __prop)
`else
`define ASSERT(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef SYNTHESIS                                                                        \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))       \
    else begin                                                                           \
      `ASSERT_ERROR(__name)                                                              \
    end                                                                                  \
`endif

`define ASSERT_INIT(__name, __prop)    \
`ifndef SYNTHESIS                      \
  initial begin                        \
    __name: assert (__prop)            \
      else begin                       \
        `ASSERT_ERROR(__name)          \
      end                              \
  end                                  \
`endif
`endif

`define ASSERT_ERROR(__name)                                                              \
`ifdef UVM                                                                                \
  uvm_pkg::uvm_report_error("ASSERT FAILED", `PRIM_STRINGIFY(__name), uvm_pkg::UVM_NONE, \
                            `__FILE__, `__LINE__, "", 1);                                 \
`else                                                                                     \
`ifdef SIM                                                                                \
  $error("%0t: (%0s:%0d) [%m] [ASSERT FAILED] %0s", $time, `__FILE__, `__LINE__,         \
         `PRIM_STRINGIFY(__name));                                                        \
`else                                                                                     \
  $error("[%m] [ASSERT FAILED] %0s", `PRIM_STRINGIFY(__name));                           \
`endif                                                                                    \
`endif

// This macro is suitable for conditionally triggering lint errors, e.g., if a Sec parameter takes
// on a non-default value. This may be required for pre-silicon/FPGA evaluation but we don't want
// to allow this for tapeout.
`define ASSERT_STATIC_LINT_ERROR(__name, __prop)     \
  localparam int __name = (__prop) ? 1 : 2;          \
  always_comb begin                                  \
    logic unused_assert_static_lint_error;           \
    unused_assert_static_lint_error = __name'(1'b1); \
  end

// Static assertions for checks inside SV packages. If the conditions is not true, this will
// trigger an error during elaboration.
`define ASSERT_STATIC_IN_PACKAGE(__name, __prop)              \
  function automatic bit assert_static_in_package_``__name(); \
    bit unused_bit [((__prop) ? 1 : -1)];                     \
    unused_bit = '{default: 1'b0};                            \
    return unused_bit[0];                                     \
  endfunction

`define ASSERT_INIT_NET(__name, __prop)                                               \
`ifndef SYNTHESIS                                                                    \
  initial begin                                                                      \
    // When a net is assigned with a value, the assignment is evaluated after        \
    // initial in Xcelium. Add 1ps delay to check value after the assignment is      \
    // completed.                                                                    \
    #1ps;                                                                            \
    __name: assert (__prop)                                                          \
      else begin                                                                     \
        `ASSERT_ERROR(__name)                                                        \
      end                                                                            \
  end                                                                                \
`endif

`define ASSERT_I(__name, __prop) \
`ifndef SYNTHESIS                \
  __name: assert (__prop)        \
    else begin                   \
      `ASSERT_ERROR(__name)      \
    end                          \
`endif

`define ASSERT_FINAL(__name, __prop)                                         \
`ifndef SYNTHESIS                                                            \
`ifndef FPV_ON                                                               \
  final begin                                                                \
    __name: assert (__prop || $test$plusargs("disable_assert_final_checks")) \
      else begin                                                             \
        `ASSERT_ERROR(__name)                                                \
      end                                                                    \
  end                                                                        \
`endif                                                                       \
`endif

`define ASSERT_NEVER(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef SYNTHESIS                                                                              \
  __name: assert property (@(posedge __clk) disable iff ((__rst) !== '0) not (__prop))         \
    else begin                                                                                 \
      `ASSERT_ERROR(__name)                                                                    \
    end                                                                                        \
`endif

`define ASSERT_KNOWN(__name, __sig, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef FPV_ON                                                                                \
  `ASSERT(__name, !$isunknown(__sig), __clk, __rst)                                           \
`endif

`define COVER(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef SYNTHESIS                                                                       \
  __name: cover property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop));      \
`endif

`define ASSUME(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef SYNTHESIS                                                                        \
  __name: assume property (@(posedge __clk) disable iff ((__rst) !== '0) (__prop))       \
    else begin                                                                           \
      `ASSERT_ERROR(__name)                                                              \
    end                                                                                  \
`endif

`define ASSUME_I(__name, __prop) \
`ifndef SYNTHESIS                \
  __name: assume (__prop)        \
    else begin                   \
      `ASSERT_ERROR(__name)      \
    end                          \
`endif

`define ASSERT_PULSE(__name, __sig, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
  `ASSERT(__name, $rose(__sig) |=> !(__sig), __clk, __rst)

`define ASSERT_IF(__name, __prop, __enable, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
  `ASSERT(__name, (__enable) |-> (__prop), __clk, __rst)

`define ASSERT_KNOWN_IF(__name, __sig, __enable, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifndef FPV_ON                                                                                             \
  `ASSERT_KNOWN(__name``KnownEnable, __enable, __clk, __rst)                                               \
  `ASSERT_IF(__name, !$isunknown(__sig), __enable, __clk, __rst)                                           \
`endif

`define ASSUME_FPV(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifdef FPV_ON                                                                                \
   `ASSUME(__name, __prop, __clk, __rst)                                                     \
`endif

`define ASSUME_I_FPV(__name, __prop) \
`ifdef FPV_ON                        \
   `ASSUME_I(__name, __prop)         \
`endif

`define COVER_FPV(__name, __prop, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
`ifdef FPV_ON                                                                               \
   `COVER(__name, __prop, __clk, __rst)                                                     \
`endif

`define ASSERT_FPV_LINEAR_FSM(__name, __state, __type, __clk = `ASSERT_DEFAULT_CLK, __rst = `ASSERT_DEFAULT_RST) \
  `ifdef INC_ASSERT                                                                                              \
     bit __name``_cond;                                                                                          \
     always_ff @(posedge __clk or posedge __rst) begin                                                           \
       if (__rst) begin                                                                                          \
         __name``_cond <= 0;                                                                                     \
       end else begin                                                                                            \
         __name``_cond <= 1;                                                                                     \
       end                                                                                                       \
     end                                                                                                         \
     property __name``_p;                                                                                        \
       __type initial_state;                                                                                     \
       (!$stable(__state) & __name``_cond, initial_state = $past(__state)) |->                                   \
           (__state != initial_state) until !(__name``_cond);                                                    \
     endproperty                                                                                                 \
   `ASSERT(__name, __name``_p, __clk, 0)                                                                         \
  `endif


`include "prim_assert_sec_cm.svh"
`include "prim_flop_macros.sv"
