// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`ifndef ASSERTION_MACROS_VH
`define ASSERTION_MACROS_VH

/*  Assertion Macros
 * Each RV_ASSERT* also has an RV_ASSUME* version
 * RV_ASSERT(name, clock, rst_n, enable, expr, msg)
 * RV_ASSERT_IMPLICATION(name, clock, rst_n, enable, num_cks, antecedent, consequent, msg)
 * RV_ASSERT_WIN_IMPLICATION(name, clock, rst_n, enable, num_cks, antecedent, consequent, msg)
 *   Checks that consequent follows antecedent in any of the next num_cks
 *   Use only if multiple antecedents are not expected before consequent
 * RV_ASSERT_NEVER(name, clock, rst_n, enable, expr, msg)
 * RV_ASSERT_NEVER_UNKNOWN(name, clock, rst_n, enable, expr, msg)
 * RV_ASSERT_NEXT(name, clock, rst_n, enable, num_cks, start, expr, msg)
 *   Checks that expr is raised iff start was raised num_cks ago
 *   Checks that there's no overlapping start-> expr sequences
 * RV_ASSERT_ONE_HOT(name, clock, rst_n, enable, expr, msg)
 * RV_ASSERT_RANGE(name, clock, rst_n, enable, min, max, expr, msg)
 *   Checks that expr in [min, max]
 * RV_ASSERT_WIN_UNCHANGE(name, clock, rst_n, enable, start_event, end_event, expr, msg)
 *   Checks that expr is unchanged from when start_event is raised to when end_event is raised
 * RV_ASSERT_ZERO_ONE_HOT(name, clock, rst_n, enable, expr, msg)
 * RV_ASSERT_ASYNC(name, expr, msg)
 * RV_ASSERT_IMMEDIATE(name, expr, msg)
 */

`define _ASSERTION_MACROS_INTERNAL_ERROR(msg)                       \
    `ifdef uvm_error                                                \
        begin                                                       \
            import uvm_pkg::*;                                      \
            `uvm_error("assertion_macros", $sformatf("%m: %s",msg)) \
        end                                                         \
    `else                                                           \
        `ifdef RV_ASSERT_ERROR_HANDLER                              \
           `RV_ASSERT_ERROR_HANDLER(msg)                            \
        `else                                                       \
            $error("%m: %s", msg)                                   \
        `endif                                                      \
    `endif

`define _ASSERTION_MACROS_INTERNAL_ASYNC(type, name, sens, expr, msg)                      \
    `ifdef ASSERTION_ENABLE                                                                \
    `ifndef ASYNC_ASSERTIONS_UNSUPPORTED                                                   \
        always @(sens) name: type final(expr) else `_ASSERTION_MACROS_INTERNAL_ERROR(msg); \
    `endif                                                                                 \
    `endif

`define RV_ASSERT_ASYNC(name, sens, expr, msg) `_ASSERTION_MACROS_INTERNAL_ASYNC(assert, name, sens, expr, msg)
`define RV_ASSUME_ASYNC(name, sens, expr, msg) `_ASSERTION_MACROS_INTERNAL_ASYNC(assume, name, sens, expr, msg)

`define _ASSERTION_MACROS_INTERNAL_IMMEDIATE(type, name, expr, msg)   \
    `ifdef ASSERTION_ENABLE                                           \
        name: type(expr) else `_ASSERTION_MACROS_INTERNAL_ERROR(msg); \
     `endif

`define RV_ASSERT_IMMEDIATE(name, expr, msg) `_ASSERTION_MACROS_INTERNAL_IMMEDIATE(assert, name, expr, msg)
`define RV_ASSUME_IMMEDIATE(name, expr, msg) `_ASSERTION_MACROS_INTERNAL_IMMEDIATE(assume, name, expr, msg)

`define _ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, expr, msg)                                  \
    `ifdef ASSERTION_ENABLE                                                                                      \
        always @(posedge clock) begin                                                                            \
            if ((rst_n)=='0) begin                                                                                   \
            end else begin                                                                                      \
                `_ASSERTION_MACROS_INTERNAL_IMMEDIATE(type,en_x_``name,!$isunknown(enable),"Xs in assertion en") \
                if (enable) begin                                                                                \
                    `_ASSERTION_MACROS_INTERNAL_IMMEDIATE(type,x_``name,!$isunknown(expr),"Xs in assertion")     \
                    `_ASSERTION_MACROS_INTERNAL_IMMEDIATE(type,name,expr,msg)                                    \
                end                                                                                              \
            end                                                                                                  \
        end                                                                                                      \
     `else                                                                                                       \
        if (0) begin end                                                                                         \
     `endif

`define _ASSERTION_MACROS_INTERNAL_IMPLICATION(type, name, clock, rst_n, enable, num_cks, antecedent, consequent, msg)          \
    if (1) begin                                                                                                                \
        logic antecedent_delayed[num_cks:1];                                                                                    \
        always_ff @(posedge (clock))  begin                                                                                     \
            for (int ast_ck = 1; ast_ck <= (num_cks); ast_ck++) begin                                                           \
            antecedent_delayed[ast_ck] <= ((rst_n)=='0) ? 1'b0 : (ast_ck == 1 ? (antecedent) : antecedent_delayed[ast_ck-1]); \
            end                                                                                                                 \
        end                                                                                                                     \
        `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, !antecedent_delayed[num_cks] || (consequent), msg)        \
    end

`define _ASSERTION_MACROS_INTERNAL_WIN_IMPLICATION(type, name, clock, rst_n, enable, num_cks, antecedent, consequent, msg)  \
    if (1) begin                                                                                                            \
        logic win_started;                                                                                                  \
        logic consequent_detected;                                                                                          \
        `_ASSERTION_MACROS_INTERNAL_IMPLICATION(type, name, clock, rst_n, enable, num_cks, antecedent, consequent_detected, msg)    \
        `_ASSERTION_MACROS_INTERNAL_WIN_UNCHANGE(type, name, clock, rst_n, enable, antecedent, consequent,                  \
            win_started ? antecedent : 1'b0, "antecedent seen twice before consequent")                                     \
        always_ff @(posedge (clock))  begin                                                                                 \
            win_started <= (!rst_n) ? 1'b0 : (antecedent) || (win_started && !(consequent));                                \
            consequent_detected <= (!rst_n || antecedent) ? 1'b0 : ((!consequent_detected && consequent) ? 1'b1 : consequent_detected); \
        end                                                                                                                 \
    end

`define _ASSERTION_MACROS_INTERNAL_NEVER(type, name, clock, rst_n, enable, expr, msg) \
    `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, !(expr), msg)

`define _ASSERTION_MACROS_INTERNAL_NEVER_UNKNOWN(type, name, clock, rst_n, enable, expr, msg) \
    `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, !$isunknown(expr), msg)

`define _ASSERTION_MACROS_INTERNAL_NEXT(type, name, clock, rst_n, enable, num_cks, start, expr, msg)    \
    if (1) begin                                                                                        \
        logic[num_cks:1] start_delayed;                                                                 \
        always_ff @(posedge (clock))  begin                                                             \
        start_delayed <= {start_delayed[num_cks-1:1], ((rst_n)=='0) ? 1'b0 : start};                        \
        end                                                                                             \
        `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, start_delayed[num_cks] == (expr)  \
            && !(start && |start_delayed), msg)                                                         \
    end

`define _ASSERTION_MACROS_INTERNAL_ONE_HOT(type, name, clock, rst_n, enable, expr, msg)                    \
    `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, $onehot(expr) && !$isunknown(expr), msg)

`define _ASSERTION_MACROS_INTERNAL_RANGE(type, name, clock, rst_n, enable, min, max, expr, msg)            \
    `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, (expr) >= (min) && (expr) <= (max), msg)

`define _ASSERTION_MACROS_INTERNAL_WIN_UNCHANGE(type, name, clock, rst_n, enable, start_event, end_event, expr, msg) \
    if (1) begin                                                                                                     \
        logic started;                                                                                               \
        logic [$bits(expr)-1:0] saved;                                                                               \
        always_ff @(posedge (clock)) begin                                                                           \
        started <= ((rst_n)=='0) ? 1'b0 : (start_event) || (started && !(end_event));                                   \
            saved   <= (start_event) ? (expr) : saved;                                                               \
        end                                                                                                          \
        `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, !started || saved == (expr), msg)              \
    end

`define _ASSERTION_MACROS_INTERNAL_ZERO_ONE_HOT(type, name, clock, rst_n, enable, expr, msg)                              \
    `_ASSERTION_MACROS_INTERNAL(type, name, clock, rst_n, enable, $onehot0(expr) && !$isunknown(expr), msg)

`define _rv_macros           \
        `X(IMPLICATION, 8)   \
        `X(WIN_IMPLICATION, 8)   \
        `X(NEVER, 6)         \
        `X(NEVER_UNKNOWN, 6) \
        `X(NEXT, 8)          \
        `X(ONE_HOT, 6)       \
        `X(RANGE, 8)         \
        `X(WIN_UNCHANGE, 8)  \
        `X(ZERO_ONE_HOT, 6)

`define X(name, numargs)                          \
        `_RV_GEN_``numargs(assert, ASSERT, ``name) \
        `_RV_GEN_``numargs(assume, ASSUME, ``name)

`define RV_ASSERT(_1, _2, _3, _4, _5, _6) `_ASSERTION_MACROS_INTERNAL(assert, _1, _2, _3, _4, _5, _6)
`define RV_ASSUME(_1, _2, _3, _4, _5, _6) `_ASSERTION_MACROS_INTERNAL(assume, _1, _2, _3, _4, _5, _6)

`define _RV_GEN_6(type, uptype, name)                                             \
        `ifdef ASSERTION_ENABLE                                                   \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6) `_ASSERTION_MACROS_INTERNAL_``name(type, _1, _2, _3, _4, _5, _6) \
        `else                                                                     \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6) if (0) begin end \
        `endif

`define _RV_GEN_7(type, uptype, name)                                                 \
        `ifdef ASSERTION_ENABLE                                                       \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6, _7) `_ASSERTION_MACROS_INTERNAL_``name (type, _1, _2, _3, _4, _5, _6, _7)  \
        `else                                                                         \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6, _7) if (0) begin end \
        `endif

`define _RV_GEN_8(type, uptype, name)                                                     \
        `ifdef ASSERTION_ENABLE                                                           \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6, _7, _8) `_ASSERTION_MACROS_INTERNAL_``name(type, _1, _2, _3, _4, _5, _6, _7, _8) \
        `else                                                                             \
            `define RV_``uptype``_``name(_1, _2, _3, _4, _5, _6, _7, _8) if (0) begin end \
        `endif

`_rv_macros
`undef X
`undef _RV_GEN_6
`undef _RV_GEN_7
`undef _RV_GEN_8
`endif
