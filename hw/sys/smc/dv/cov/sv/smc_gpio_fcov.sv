// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC GPIO pad functional coverage: output pads driven low after high, the
// strap pattern latched when the primary reset releases, and the default
// direction map on the per-pad input-buffer enable.
//
// smc_periph_fcov carries the pad-bus activity and BootStallPad points.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or the smc_wrapper pad bus.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_gpio_fcov #(
  parameter int unsigned GPIO_WIDTH = 65,
  // Bonded pads carrying straps: STRAPS_LO/HI cover [60:0].
  parameter int unsigned STRAP_WIDTH = 61,
  parameter int unsigned DEFAULT_OUTPUT_COUNT = 3,
  parameter int unsigned DEFAULT_INPUT_COUNT = 62,
  // smc_padring_pkg::DefaultDirectionMap, passed in by tb_top: bit i is 1 when
  // pad i is an input by default. The direction map reaches the boundary on
  // pad2core_en_o, so the same vector is the expected value of that bus.
  parameter logic [GPIO_WIDTH-1:0] DEFAULT_INPUT_MAP = '1
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,

  input wire [GPIO_WIDTH-1:0] core2pad_i,
  input wire [GPIO_WIDTH-1:0] core2pad_en_i,
  input wire [GPIO_WIDTH-1:0] pad2core_en_i,
  input wire [GPIO_WIDTH-1:0] pad_i,
  input wire [GPIO_WIDTH-1:0] lsio_select_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Output pad driven low. Low with the driver enabled is the reset state of
  // the default-output pads, so each pad qualifies on having driven high
  // first: the point means "an output pad returned low".
  // ------------------------------------------------------------------
  logic [GPIO_WIDTH-1:0] pad_high_seen_q;
  logic [GPIO_WIDTH-1:0] pad_driven_high, pad_driven_low_after_high;
  always_comb begin
    for (int unsigned i = 0; i < GPIO_WIDTH; i++) begin
      pad_driven_high[i] = (core2pad_en_i[i] === 1'b1) && (core2pad_i[i] === 1'b1);
      pad_driven_low_after_high[i] = pad_high_seen_q[i] && (core2pad_en_i[i] === 1'b1)
          && (core2pad_i[i] === 1'b0);
    end
  end
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) pad_high_seen_q <= '0;
    else pad_high_seen_q <= pad_high_seen_q | pad_driven_high;
  end
  wire pad_output_low_e = (pad_driven_low_after_high != '0);
  `OCAH_FCOV_COVER(c_pad_output_low, pad_output_low_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Strap pattern on the bonded pads in the sample that releases the
  // primary reset, and the default direction map in the same sample.
  // ------------------------------------------------------------------
  logic primary_smc_q;
  always_ff @(posedge clk_smc_i) primary_smc_q <= rst_primary_smc_clk_ni;
  wire release_primary_smc = (rst_primary_smc_clk_ni === 1'b1) && (primary_smc_q === 1'b0);

`ifdef SMC_FCOV_PHASE2
  // Phase 2 (SMC_FCOV.adoc): the reference integration captures no strap
  // pattern (STRAPS_LO/HI read zero whatever the pads carry), so a pattern at
  // the pads has no consequence the bench can check.
  wire [STRAP_WIDTH-1:0] straps = pad_i[STRAP_WIDTH-1:0];
  wire straps_known = (^straps !== 1'bx);
  wire straps_all_zero_e = release_primary_smc && (straps === '0);
  wire straps_all_ones_e = release_primary_smc && (straps === '1);
  wire straps_mixed_e = release_primary_smc && straps_known && (straps != '0) && (straps != '1);
  `OCAH_FCOV_COVER(c_straps_all_zero, straps_all_zero_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_straps_all_ones, straps_all_ones_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_straps_mixed_pattern, straps_mixed_e, clk_smc_i, in_reset)
`endif

  // Default-direction tallies are taken from pad2core_en_i, the per-pad
  // input-buffer enable: a pad that is an output by default has its input
  // buffer disabled. core2pad_en_i does not carry the map -- gpio.sv holds it
  // at 0 for every instance until a CSR or the LSIO interface drives it.
  // The two tallies come from separate passes over the bus, so each point
  // stands on its own count rather than on the other one's complement.
  logic [$clog2(GPIO_WIDTH+1)-1:0] output_count;
  logic [$clog2(GPIO_WIDTH+1)-1:0] input_count;
  always_comb begin
    output_count = '0;
    input_count = '0;
    for (int unsigned i = 0; i < GPIO_WIDTH; i++) begin
      if (pad2core_en_i[i] === 1'b0) output_count = output_count + 1'b1;
      if (pad2core_en_i[i] === 1'b1) input_count = input_count + 1'b1;
    end
  end
  wire default_output_count_e = release_primary_smc && (output_count == DEFAULT_OUTPUT_COUNT);
  wire default_input_count_e = release_primary_smc && (input_count == DEFAULT_INPUT_COUNT);
  // A pad an LSIO function owns takes that function's direction rather than
  // its INPUT_BY_DEFAULT (Programmer's Guide, Selecting and Reclaiming LSIO), so
  // the map is compared on the pads software and the default still own.
  wire lsio_known = (^lsio_select_i !== 1'bx);
  wire [GPIO_WIDTH-1:0] default_map_diff = (pad2core_en_i ^ DEFAULT_INPUT_MAP) & ~lsio_select_i;
  wire default_map_matches_e = release_primary_smc && lsio_known && (lsio_select_i != '1)
      && (default_map_diff === '0);
  `OCAH_FCOV_COVER(c_default_output_count_3, default_output_count_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_default_input_count_62, default_input_count_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_per_instance_default_matches_map, default_map_matches_e, clk_smc_i, in_reset)

endmodule : smc_gpio_fcov
