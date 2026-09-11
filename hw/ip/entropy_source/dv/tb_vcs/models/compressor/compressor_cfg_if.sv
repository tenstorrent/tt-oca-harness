// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Entropy Compressor Configuration Interface
//
// Description:
//   SystemVerilog interface for configuring the Entropy Compressor (BIW
//   Extractor) reference model. Provides runtime control over compression
//   behavior, bypass modes, and debug features.
//------------------------------------------------------------------------------

interface compressor_cfg_if;

  //--------------------------------------------------------------------------
  // Configuration Signals
  //--------------------------------------------------------------------------

  // Primary Controls
  logic        enable;           // Enable compressor (1=active, 0=disabled)
                                 // Default: 1 (enabled)

  logic        bypass;           // Bypass mode:
                                 // 0 = Normal BIW compression
                                 // 1 = Simple concatenation (debug only)
                                 // Default: 0 (normal mode)

  logic [11:0] lane_mask;        // Per-lane enable mask
                                 // Bit[i] = 1: lane i active
                                 // Bit[i] = 0: lane i forced to 0x00
                                 // Default: 0xFFF (all lanes active)

  // Checker Controls
  logic        checker_enable;   // Enable output checker (1=enabled, 0=disabled)
                                 // Default: 1 (enabled)
  logic        checker_verbose;  // Show MATCH messages (1=verbose, 0=errors only)
                                 // Default: 0 (errors only)

  //--------------------------------------------------------------------------
  // Modports
  //--------------------------------------------------------------------------

  // Master modport: Used by testbench/Python to configure model
  modport master(
      output enable,
      output bypass,
      output lane_mask,
      output checker_enable,
      output checker_verbose
  );

  // Slave modport: Used by reference model
  modport slave(input enable, input bypass, input lane_mask);

  //--------------------------------------------------------------------------
  // Power-on defaults to avoid X propagation before Python configuration
  //--------------------------------------------------------------------------
  // NOTE: All runtime defaults are specified and applied in test_config.py (CompressorConfig)
  //       via compressor_init() function in test_base.py
  // These are minimal fallbacks only to prevent X propagation
  initial begin
    enable          = 1'b1;      // Enabled (safe default)
    bypass          = 1'b0;      // Normal mode
    lane_mask       = 12'hFFF;   // All lanes active
    checker_enable  = 1'b1;      // Checker enabled
    checker_verbose = 1'b0;      // Errors only (not verbose)
  end

  //--------------------------------------------------------------------------
  // Helper Functions (for Python/testbench)
  //--------------------------------------------------------------------------

  // Check if specific lane is enabled
  function automatic logic is_lane_enabled(input int lane_num);
    if (lane_num >= 0 && lane_num < 12) return lane_mask[lane_num];
    else return 1'b0;
  endfunction

  // Count number of active lanes
  function automatic int count_active_lanes();
    int count = 0;
    for (int i = 0; i < 12; i++) begin
      if (lane_mask[i]) count++;
    end
    return count;
  endfunction

  // Get lane indices for a specific group (strided grouping)
  function automatic void get_group_lanes(input int group_num, output int lane_a, output int lane_b,
                                          output int lane_c);
    case (group_num)
      0: begin
        lane_a = 0;
        lane_b = 4;
        lane_c = 8;
      end  // Group 0: [0,4,8]
      1: begin
        lane_a = 1;
        lane_b = 5;
        lane_c = 9;
      end  // Group 1: [1,5,9]
      2: begin
        lane_a = 2;
        lane_b = 6;
        lane_c = 10;
      end  // Group 2: [2,6,10]
      3: begin
        lane_a = 3;
        lane_b = 7;
        lane_c = 11;
      end  // Group 3: [3,7,11]
      default: begin
        lane_a = 0;
        lane_b = 0;
        lane_c = 0;
      end
    endcase
  endfunction

endinterface : compressor_cfg_if
