// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

`timescale 1ns/1ps

// Decorrelator Configuration Interface
// Provides runtime control of decorrelator operating mode and sample period
interface decor_cfg_if;
    // Operating mode selection
    // 0: DECOR_29 - 29-deep XOR decorrelator (default, per spec)
    // 1: DECOR_7  - 7-deep XOR decorrelator (shallow, for testing)
    // 2: BYPASS   - No decorrelation, raw bits (for debug)
    // 3: LFSR_29  - 29-bit Fibonacci LFSR (x^29 + x^2 + 1)
    // 4: LFSR_7   - 7-bit Fibonacci LFSR (x^7 + x^6 + 1)
    logic [2:0] mode;

    // Output sample period in clock cycles
    // Recommended values per mode (all coprime with depth):
    //   Mode 0 (DECOR_29): 64 cycles (default per spec)
    //   Mode 1 (DECOR_7):  16 cycles (coprime with 7)
    //   Mode 2 (BYPASS):    8 cycles (output every 8 cycles)
    //   Mode 3 (LFSR_29): 64 cycles (same as DECOR_29)
    //   Mode 4 (LFSR_7):  16 cycles (same as DECOR_7)
    // Range: 1 to 65535
    logic [15:0] sample_period;

    // Shift direction (applies to all modes)
    // 0: SHIFT_RIGHT - Input at [28], output at [7:0], shift right (28→27→...→0)
    // 1: SHIFT_LEFT  - Input at [0], output at [28:21], shift left (0→1→2→...→28) [DEFAULT]
    logic shift_dir;

    // Per-lane bypass mask (12 bits, one per lane)
    // bypass_mask[i] = 1: Lane i bypasses (no decorrelation)
    // bypass_mask[i] = 0: Lane i uses mode setting
    // Examples:
    //   0x000: All lanes decorrelate (pure mode)
    //   0xFFF: All lanes bypass (pure bypass)
    //   0x001: Lane 0 bypasses, others decorrelate (mixed mode)
    //   0xAAA: Even lanes bypass, odd decorrelate (mixer mode)
    logic [11:0] bypass_mask;

    // Checker enable control
    // 1: Enable decorrelator output checker (default)
    // 0: Disable decorrelator output checker
    logic checker_enable;

    // Checker verbose mode
    // 1: Show both MATCH and MISMATCH messages (verbose)
    // 0: Show only MISMATCH messages (default, less verbose)
    logic checker_verbose;

    // Power-on defaults to avoid X propagation before Python configuration
    // NOTE: All runtime defaults are specified and applied in test_config.py (DecorrelatorConfig)
    //       via decor_init() function in test_base.py
    // These are minimal fallbacks only to prevent X propagation
    initial begin
        mode            = 3'd0;   // DECOR_29
        sample_period   = 16'd64; // 64 cycles
        shift_dir       = 1'b1;   // SHIFT_LEFT (default)
        bypass_mask     = 12'd0;  // No bypass (all lanes decorrelate)
        checker_enable  = 1'b0;   // Disabled (safe default - enable only when needed)
        checker_verbose = 1'b0;   // Only mismatches (less verbose)
    end

    modport cfg ();
endinterface
