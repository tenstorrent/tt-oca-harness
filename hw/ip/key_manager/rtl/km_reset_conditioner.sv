// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
// Copyright 2026 Tenstorrent Inc.

/**
 * @file km_reset_conditioner.sv
 * @brief Dual-output reset conditioner: cold (AASD) and warm (synchronous).
 *
 * @details Produces two clean, glitch-free, active-low resets for the Key
 *          Manager subsystem:
 *
 *          Cold path (rst_cold_aasd_no):
 *            - Source: cold_rst_ni only.
 *            - Synchronization: async-assert/sync-deassert via prim_rst_sync.
 *            - Resets the entire KM (AASD).
 *
 *          Warm path (rst_warm_sync_no):
 *            - Synchronous sources: warm_rst_ni (external pulse) or soft_rst_ni
 *              (KMCSR software trigger); both assumed synchronous to clk_i.
 *            - Cold source: rst_cold_aasd_no is the async reset of the warm
 *              counter flop, so any cold-reset event immediately asserts
 *              rst_warm_sync_no and clears all warm-reset-only state.
 *            - Pulse extension: minimum MIN_RESET_CYCLES hold time.
 *            - Resets the PicoRV32 CPU, KPV lock bits, KMCSR warm subset, and
 *              DRBG sampler CSRs.
 *
 *          DFT: scan_rst_ni / scanmode_i bypass both output paths consistently.
 *
 * @param MIN_RESET_CYCLES  Minimum warm reset hold time in clock cycles (default 10).
 */

module km_reset_conditioner import prim_mubi_pkg::*; #(
    // Minimum reset hold time in clock cycles
    parameter int unsigned MIN_RESET_CYCLES = 10
) (
    // Clock
    input  logic clk_i,

    // Reset inputs
    input  logic   cold_rst_ni,   // Async cold reset (active-low, from external system)
    input  logic   soft_rst_ni,   // Soft reset (active-low, from KMCSR; sync to clk_i)
    input  logic   warm_rst_ni,   // Warm reset pulse (active-low, from integrator; sync to clk_i)
    input  logic   scan_rst_ni,   // Scan reset (active-low, for DFT)
    input  mubi4_t scanmode_i,    // Scan mode (MuBi4True enables scan override)

    // Reset outputs
    output logic        rst_cold_aasd_no,  // Cold reset: async-assert / sync-deassert (AASD)
    output logic        rst_warm_sync_no   // Warm reset: fully synchronous
);

    `include "prim_assert.sv"

    //=========================================================================
    // Local Parameters
    //=========================================================================

    /** @brief Counter width sized to hold MIN_RESET_CYCLES. */
    localparam int unsigned COUNT_WIDTH = $clog2(MIN_RESET_CYCLES + 1);

    //=========================================================================
    // Cold Path — single prim_rst_sync (AASD)
    //=========================================================================

    prim_rst_sync #(
        .ActiveHigh(1'b0),
        .SkipScan  (1'b0)
    ) u_cold_rst_sync (
        .clk_i       (clk_i),
        .d_i         (cold_rst_ni),
        .q_o         (rst_cold_aasd_no),
        .scan_rst_ni (scan_rst_ni),
        .scanmode_i  (scanmode_i)
    );

    //=========================================================================
    // Warm Path — fully synchronous, MIN_RESET_CYCLES hold counter
    //=========================================================================
    // warm_trigger covers the two synchronous warm sources:
    //   - warm_rst_ni low: external pulse from integrator (already sync).
    //   - soft_rst_ni low: software-triggered reset (already sync from KMCSR).
    //
    // Cold reset (rst_cold_aasd_no) is wired as the async reset of the counter
    // flop directly; it must not appear in the synchronous trigger because
    // rst_cold_aasd_no is AASD (async-assert) and would create a CDC hazard
    // inside a posedge-only always_ff.
    //
    // While warm_trigger is true the counter is reloaded every cycle.
    // After warm_trigger deasserts the counter counts down; output stays
    // asserted until counter reaches zero.

    logic warm_trigger;
    assign warm_trigger = !warm_rst_ni | !soft_rst_ni;

    logic [COUNT_WIDTH-1:0] warm_count;
    logic warm_hold_active;

    always_ff @(posedge clk_i or negedge rst_cold_aasd_no) begin
        if (!rst_cold_aasd_no) begin
            warm_count       <= MIN_RESET_CYCLES[COUNT_WIDTH-1:0];
            warm_hold_active <= 1'b1;
        end else if (warm_trigger) begin
            // Reload counter every cycle that trigger is active.
            warm_count       <= MIN_RESET_CYCLES[COUNT_WIDTH-1:0];
            warm_hold_active <= 1'b1;
        end else if (warm_hold_active) begin
            if (warm_count > 0) begin
                warm_count <= warm_count - 1'b1;
            end else begin
                warm_hold_active <= 1'b0;
            end
        end
    end

    // rst_warm_sync_no output flop.
    // Async-reset by rst_cold_aasd_no so that rst_warm_sync_no asserts
    // immediately when cold reset fires (satisfies WarmAssertedWhenCold_A).
    // DFT: when scan mode is active, bypass with scan_rst_ni.
    logic warm_hold_active_q;
    always_ff @(posedge clk_i or negedge rst_cold_aasd_no) begin
        if (!rst_cold_aasd_no) begin
            warm_hold_active_q <= 1'b1;
        end else begin
            warm_hold_active_q <= warm_hold_active | warm_trigger;
        end
    end

    assign rst_warm_sync_no = mubi4_test_true_strict(scanmode_i) ? scan_rst_ni
                                                                   : ~warm_hold_active_q;

    //=========================================================================
    // Assertions
    //=========================================================================

    `OCAH_OT_ASSERT_INIT(MinResetCyclesValid_A, MIN_RESET_CYCLES >= 2)

    // Warm reset must always be asserted when cold reset is asserted.
    `OCAH_OT_ASSERT(WarmAssertedWhenCold_A,
            !rst_cold_aasd_no |-> !rst_warm_sync_no,
            clk_i,
            !rst_cold_aasd_no || mubi4_test_true_strict(scanmode_i))

endmodule : km_reset_conditioner

