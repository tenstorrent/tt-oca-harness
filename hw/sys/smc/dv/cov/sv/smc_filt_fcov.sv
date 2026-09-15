// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC filter functional coverage: the AXI-Lite protection filter guarding a
// GPIO wrap, and the JTAG2AXI manager's path through the alias remap and the
// inbound fabric filter.
//
// The protection filter compares the request's prot against a programmed
// requirement, so the two points are "equal" and "one bit apart" -- the
// second is the nearest miss, which a coarse mismatch point would hide.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_filt_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // GPIO wrap 0 AXI-Lite protection filter.
  input wire gpio_awvalid_i,
  input wire gpio_arvalid_i,
  input wire [2:0] gpio_awprot_i,
  input wire [2:0] gpio_arprot_i,
  input wire [2:0] gpio_awprot_req_i,
  input wire [2:0] gpio_arprot_req_i,
  input wire gpio_wr_filter_en_i,
  input wire gpio_rd_filter_en_i,

  // JTAG2AXI manager activity, its alias-remap hit debug and the inbound
  // fabric filter decision.
  input wire jtag_awvalid_i,
  input wire jtag_arvalid_i,
  input wire [2:0] remap_jtag_aw_hit_i,
  input wire [2:0] remap_jtag_ar_hit_i,
  input wire [15:0] inb_write_hit_i,
  input wire [15:0] inb_read_hit_i,
  input wire inb_isolate_write_i,
  input wire inb_isolate_read_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Protection filter. Both points require the corresponding filter enable,
  // because with the enable clear the comparison is bypassed and the prot
  // value carries no meaning.
  // ------------------------------------------------------------------
  wire [2:0] awprot_diff = gpio_awprot_i ^ gpio_awprot_req_i;
  wire [2:0] arprot_diff = gpio_arprot_i ^ gpio_arprot_req_i;

  logic [1:0] awprot_diff_ones, arprot_diff_ones;
  always_comb begin
    awprot_diff_ones = '0;
    arprot_diff_ones = '0;
    for (int unsigned b = 0; b < 3; b++) begin
      if (awprot_diff[b] === 1'b1) awprot_diff_ones = awprot_diff_ones + 2'd1;
      if (arprot_diff[b] === 1'b1) arprot_diff_ones = arprot_diff_ones + 2'd1;
    end
  end

  wire aw_filtered = (gpio_awvalid_i === 1'b1) && (gpio_wr_filter_en_i === 1'b1)
      && (^gpio_awprot_i !== 1'bx) && (^gpio_awprot_req_i !== 1'bx);
  wire ar_filtered = (gpio_arvalid_i === 1'b1) && (gpio_rd_filter_en_i === 1'b1)
      && (^gpio_arprot_i !== 1'bx) && (^gpio_arprot_req_i !== 1'bx);

  wire awprot_exact_match_e = aw_filtered && (awprot_diff_ones == 2'd0);
  wire awprot_one_bit_off_e = aw_filtered && (awprot_diff_ones == 2'd1);
  wire arprot_exact_match_e = ar_filtered && (arprot_diff_ones == 2'd0);
  wire arprot_one_bit_off_e = ar_filtered && (arprot_diff_ones == 2'd1);
  `OCAH_FCOV_COVER(c_awprot_exact_match, awprot_exact_match_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_awprot_one_bit_off, awprot_one_bit_off_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_arprot_exact_match, arprot_exact_match_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_arprot_one_bit_off, arprot_one_bit_off_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // JTAG2AXI through the alias remap and the inbound filter. The remap hit
  // debug is per-manager, so it attributes the remap to the JTAG path; the
  // filter decision is shared, so its point is qualified by the JTAG
  // manager being the one presenting a request.
  // ------------------------------------------------------------------
  wire jtag_active = (jtag_awvalid_i === 1'b1) || (jtag_arvalid_i === 1'b1);
  wire jtag_remap_hit = (remap_jtag_aw_hit_i !== 3'd0) || (remap_jtag_ar_hit_i !== 3'd0);
  wire jtag2axi_remapped_e = jtag_active && jtag_remap_hit
      && (^remap_jtag_aw_hit_i !== 1'bx) && (^remap_jtag_ar_hit_i !== 1'bx);

  wire filter_decided = (inb_write_hit_i !== 16'd0) || (inb_read_hit_i !== 16'd0)
      || (inb_isolate_write_i === 1'b1) || (inb_isolate_read_i === 1'b1);
  wire jtag2axi_filtered_e = jtag_active && filter_decided;
  `OCAH_FCOV_COVER(c_jtag2axi_remapped, jtag2axi_remapped_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_jtag2axi_filtered, jtag2axi_filtered_e, clk_smc_i, in_reset)

  // The filter blocking and admitting, kept as their own points so a run in
  // which nothing was ever blocked is visible rather than implied.
  wire inbound_blocked_e = (inb_isolate_write_i === 1'b1) || (inb_isolate_read_i === 1'b1);
  wire inbound_admitted_e = !inbound_blocked_e
      && ((inb_write_hit_i !== 16'd0) || (inb_read_hit_i !== 16'd0));
  `OCAH_FCOV_COVER(c_inbound_filter_blocked, inbound_blocked_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_inbound_filter_admitted, inbound_admitted_e, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the prot value against the programmed
  // requirement, which the flat list can only bucket by hamming distance.
  // ------------------------------------------------------------------
  covergroup cg_prot_filter with function sample (
      logic [2:0] prot, logic [2:0] requirement, logic enabled
  );
    option.per_instance = 1;
    cp_prot: coverpoint prot;
    cp_req: coverpoint requirement;
    cp_en: coverpoint enabled;
    x_prot_req: cross cp_prot, cp_req;
  endgroup

  cg_prot_filter u_cg_awprot = new();
  cg_prot_filter u_cg_arprot = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (gpio_awvalid_i) u_cg_awprot.sample(gpio_awprot_i, gpio_awprot_req_i, gpio_wr_filter_en_i);
      if (gpio_arvalid_i) u_cg_arprot.sample(gpio_arprot_i, gpio_arprot_req_i, gpio_rd_filter_en_i);
    end
  end
`endif

endmodule : smc_filt_fcov
