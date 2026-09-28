// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMU external-boundary functional coverage, from the SMU-EXT-SMN,
// SMU-MBOX-IRQ-OUT, SMU-SSRESET, SMU-EFUSE-SHIM-SMC and SMU-EFUSE-SHIM-SEP
// scenarios of the feature list: the SMN port ID widths, the mailbox
// interrupt vector, the eFuse bank-control AXI-Lite shims, and the outputs
// the chiplet presents to external systems.
//
// One passive, signal-driven module. Every port is a signal the bench
// exposes at its top level; the port
// widths come from the DUT packages, so a width point is unhittable when
// the bench's signal does not match them.
//
// A width point fires on activity through the port, a presence point at the
// event that first presents the output (primary release, fuse sense done);
// neither is true in the quiescent state. Presence is X-aware.
//
// SEP PRESENCE: the SEP eFuse shim points sit in the `g_sep` generate block,
// so a SEP=0 build carries no unhittable point and one coverage policy can
// grade both elaborations.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use. Every register
// carries a reset branch.

`include "ocah_fcov_macros.svh"

module smu_ext_fcov #(
  // 0 on an elaboration without SEP. The SEP eFuse bank-control shim is
  // driven from the SEP subsystem, so smu.sv's gen_no_sep branch ties the
  // request port to '0 and the bench ties the response pins off; the two
  // points on that shim are dropped rather than carried unhittable.
  parameter bit SepPresent = 1'b1
) (
  input wire clk_smu_i,
  input wire rst_cold_ni,
  input wire rst_primary_smc_clk_ni,
  input wire fuse_sense_done_i,

  // Inbound SMN AW handshake and ID; outbound SMN AW handshake and ID.
  input wire s_axi_awvalid_i,
  input wire s_axi_awready_i,
  input wire [7:0] s_axi_awid_i,
  input wire axi_out_aw_valid_i,
  input wire axi_out_aw_ready_i,
  input wire [9:0] axi_out_aw_id_i,

  // eFuse bank-control AXI-Lite shims at the SMU boundary, one per subsystem.
  input wire smc_efuse_bank_ctrl_awvalid_i,
  input wire smc_efuse_bank_ctrl_arvalid_i,
  input wire smc_efuse_bank_ctrl_bvalid_i,
  input wire smc_efuse_bank_ctrl_bready_i,
  input wire smc_efuse_bank_ctrl_rvalid_i,
  input wire smc_efuse_bank_ctrl_rready_i,
  input wire sep_efuse_bank_ctrl_awvalid_i,
  input wire sep_efuse_bank_ctrl_arvalid_i,
  input wire sep_efuse_bank_ctrl_bvalid_i,
  input wire sep_efuse_bank_ctrl_bready_i,
  input wire sep_efuse_bank_ctrl_rvalid_i,
  input wire sep_efuse_bank_ctrl_rready_i,

  // Outputs to external systems.
  input wire [smc_pkg::NUM_MAILBOXES-1:0] ext_mailbox_interrupts_i,
  input wire [31:0] ss_config_i,
  input smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_i[31:0],
  input smc_efuse_pkg::efuse_map_t smc_shadow_regs_i
);

  localparam int unsigned MbxMsb = smc_pkg::NUM_MAILBOXES - 1;

  wire in_reset = (rst_cold_ni !== 1'b1);

  wire smc_efuse_req = (smc_efuse_bank_ctrl_awvalid_i === 1'b1)
      || (smc_efuse_bank_ctrl_arvalid_i === 1'b1);

  logic primary_q, fuse_sense_q, mbx_msb_q;
  logic smc_efuse_req_q;
  always_ff @(posedge clk_smu_i) begin
    if (in_reset) begin
      primary_q <= 1'b0;
      fuse_sense_q <= 1'b0;
      mbx_msb_q <= 1'b0;
      smc_efuse_req_q <= 1'b0;
    end else begin
      primary_q <= rst_primary_smc_clk_ni;
      fuse_sense_q <= fuse_sense_done_i;
      mbx_msb_q <= ext_mailbox_interrupts_i[MbxMsb];
      smc_efuse_req_q <= smc_efuse_req;
    end
  end

  wire primary_rose_e = (rst_primary_smc_clk_ni === 1'b1) && (primary_q === 1'b0);
  wire fuse_sense_done_e = (fuse_sense_done_i === 1'b1) && (fuse_sense_q === 1'b0);

  // ------------------------------------------------------------------
  // SMN port ID widths, on the address handshake that carries the ID.
  // ------------------------------------------------------------------
  wire aw_in_accept_e = (s_axi_awvalid_i === 1'b1) && (s_axi_awready_i === 1'b1);
  wire aw_out_fire_e = (axi_out_aw_valid_i === 1'b1) && (axi_out_aw_ready_i === 1'b1);
  wire inbound_id_width_8_e = aw_in_accept_e && ($bits(s_axi_awid_i) == 8);
  `OCAH_FCOV_COVER(c_inbound_id_width_8, inbound_id_width_8_e, clk_smu_i, in_reset)
  // The 10-bit outbound ID is the SEP=0 converter path; with SEP present the
  // crossbar widens it.
  if (!SepPresent) begin : g_nosep
    wire outbound_id_width_10_e = aw_out_fire_e && ($bits(axi_out_aw_id_i) == 10);
    `OCAH_FCOV_COVER(c_outbound_id_width_10, outbound_id_width_10_e, clk_smu_i, in_reset)
  end

  // ------------------------------------------------------------------
  // Mailbox interrupt vector: its top bit, index NUM_MAILBOXES-1, rising.
  // ------------------------------------------------------------------
  wire mailbox_irq_out_width_32_e = (ext_mailbox_interrupts_i[MbxMsb] === 1'b1)
      && (mbx_msb_q === 1'b0) && (smc_pkg::NUM_MAILBOXES == 32);
  `OCAH_FCOV_COVER(c_mailbox_irq_out_width_32, mailbox_irq_out_width_32_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // Subsystem reset-unit outputs at primary release; the eFuse shadow map
  // once the fuses have been sensed.
  // ------------------------------------------------------------------
  wire ss_reset_ctrl_array_32_e = primary_rose_e && ($size(ss_reset_ctrl_i) == 32)
      && !$isunknown(ss_reset_ctrl_i[0]) && !$isunknown(ss_reset_ctrl_i[31]);
  wire ss_config_present_e = primary_rose_e && !$isunknown(ss_config_i);
  wire smc_shadow_regs_present_e = fuse_sense_done_e && !$isunknown(smc_shadow_regs_i);
  `OCAH_FCOV_COVER(c_ss_reset_ctrl_array_32, ss_reset_ctrl_array_32_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_ss_config_present, ss_config_present_e, clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_shadow_regs_present, smc_shadow_regs_present_e, clk_smu_i, in_reset)

  // ------------------------------------------------------------------
  // eFuse bank-control shims: the request appearing at the boundary, and
  // the response coming back on the same AXI-Lite port.
  // ------------------------------------------------------------------
  wire smc_efuse_bank_ctrl_request_observed_e = smc_efuse_req && (smc_efuse_req_q === 1'b0);
  wire smc_efuse_bank_ctrl_response_returned_e =
      ((smc_efuse_bank_ctrl_bvalid_i === 1'b1) && (smc_efuse_bank_ctrl_bready_i === 1'b1))
      || ((smc_efuse_bank_ctrl_rvalid_i === 1'b1) && (smc_efuse_bank_ctrl_rready_i === 1'b1));
  `OCAH_FCOV_COVER(c_smc_efuse_bank_ctrl_request_observed, smc_efuse_bank_ctrl_request_observed_e,
                   clk_smu_i, in_reset)
  `OCAH_FCOV_COVER(c_smc_efuse_bank_ctrl_response_returned,
                   smc_efuse_bank_ctrl_response_returned_e, clk_smu_i, in_reset)

  // The SEP-side shim, observed the same way. Only elaborated with SEP
  // present: the request port is tied to '0 without it, so nothing is ever
  // launched and nothing comes back.
  if (SepPresent) begin : g_sep
    wire sep_efuse_req = (sep_efuse_bank_ctrl_awvalid_i === 1'b1)
        || (sep_efuse_bank_ctrl_arvalid_i === 1'b1);

    logic sep_efuse_req_q;
    always_ff @(posedge clk_smu_i) begin
      if (in_reset) sep_efuse_req_q <= 1'b0;
      else sep_efuse_req_q <= sep_efuse_req;
    end

    wire sep_efuse_bank_ctrl_request_observed_e = sep_efuse_req && (sep_efuse_req_q === 1'b0);
    wire sep_efuse_bank_ctrl_response_returned_e =
        ((sep_efuse_bank_ctrl_bvalid_i === 1'b1) && (sep_efuse_bank_ctrl_bready_i === 1'b1))
        || ((sep_efuse_bank_ctrl_rvalid_i === 1'b1) && (sep_efuse_bank_ctrl_rready_i === 1'b1));
    `OCAH_FCOV_COVER(c_sep_efuse_bank_ctrl_request_observed, sep_efuse_bank_ctrl_request_observed_e,
                     clk_smu_i, in_reset)
    `OCAH_FCOV_COVER(c_sep_efuse_bank_ctrl_response_returned,
                     sep_efuse_bank_ctrl_response_returned_e, clk_smu_i, in_reset)
  end

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the ID values carried on each port.
  // ------------------------------------------------------------------
  covergroup cg_smn_ids with function sample (logic [7:0] in_id, logic [9:0] out_id);
    option.per_instance = 1;
    cp_in_id: coverpoint in_id {bins zero = {8'h00}; bins max = {8'hff}; bins other = default;}
    // The crossbar prefixes each outbound ID with its 2-bit slave-port index.
    // ext_out is reachable from sep_out (index 0) and smc_out (index 1) only,
    // so an outbound ID above 10'h1ff never appears on this port.
    cp_out_id: coverpoint out_id {
      bins from_sep = {[10'h000 : 10'h0ff]};
      bins from_smc = {[10'h100 : 10'h1ff]};
      ignore_bins unrouted_ports = {[10'h200 : 10'h3ff]};
    }
  endgroup

  cg_smn_ids u_cg_smn_ids = new();

  always_ff @(posedge clk_smu_i) begin
    if (!in_reset && (aw_in_accept_e || aw_out_fire_e)) begin
      u_cg_smn_ids.sample(s_axi_awid_i, axi_out_aw_id_i);
    end
  end
`endif

endmodule : smu_ext_fcov
