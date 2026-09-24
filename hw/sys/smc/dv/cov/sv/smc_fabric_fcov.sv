// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC fabric functional coverage: the `axil_master` intent of SMC_FCOV.adoc
// plus the inbound/outbound AXI traffic it stands in for.
//
// The Python `axil_master` bin is the 1-tuple (any_master_active,), which
// saturates at unique=1 and cannot say which downstream interface moved.
// The per-interface actives are separate points here, and each inbound AXI
// manager gets a smc_axi_chan_fcov instance carrying handshake, burst-shape
// and response-code points, so a response code the suite never produces is
// a named hole rather than invisible inside an OR reduction.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_fabric_fcov #(
  // 1 when the bench answers the SMC's DTP CSR AXI-Lite port. The SMC bench
  // ties that response port off, so no access to it completes and none is
  // issued; the DTP-active bins are dropped rather than carried unhittable.
  parameter bit DtpCsrResponder = 1'b0
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // Downstream AXI-Lite master activity (OR of aw/w/ar valid per interface).
  input wire axil_dtp_csr_active_i,
  input wire axil_external_active_i,
  input wire axil_efuse_bank_active_i,
  input wire axil_any_master_active_i,

  // SEP_IN inbound manager.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [7:0] sep_awlen_i,
  input wire [2:0] sep_awsize_i,
  input wire [1:0] sep_awburst_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [7:0] sep_wstrb_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [7:0] sep_arlen_i,
  input wire [2:0] sep_arsize_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,
  input wire sep_r_hold_i,
  // SEP_IN address and ID, for the internal-address-range and
  // response-ID-matches-request-port points.
  input wire [55:0] sep_awaddr_i,
  input wire [55:0] sep_araddr_i,
  input wire [5:0] sep_awid_i,
  input wire [5:0] sep_arid_i,
  input wire [5:0] sep_bid_i,
  input wire [5:0] sep_rid_i,

  // SYS_IN inbound manager.
  input wire sys_awvalid_i,
  input wire sys_awready_i,
  input wire [7:0] sys_awlen_i,
  input wire sys_wvalid_i,
  input wire sys_wready_i,
  input wire sys_wlast_i,
  input wire sys_bvalid_i,
  input wire sys_bready_i,
  input wire [1:0] sys_bresp_i,
  input wire sys_arvalid_i,
  input wire sys_arready_i,
  input wire [7:0] sys_arlen_i,
  input wire sys_rvalid_i,
  input wire sys_rready_i,
  input wire sys_rlast_i,
  input wire [1:0] sys_rresp_i,
  input wire sys_r_hold_i,

  // JTAG AXI manager (output-fabric VIP path).
  input wire jtag_awvalid_i,
  input wire jtag_awready_i,
  input wire [7:0] jtag_awlen_i,
  input wire jtag_wvalid_i,
  input wire jtag_wready_i,
  input wire jtag_wlast_i,
  input wire jtag_bvalid_i,
  input wire jtag_bready_i,
  input wire [1:0] jtag_bresp_i,
  input wire jtag_arvalid_i,
  input wire jtag_arready_i,
  input wire [7:0] jtag_arlen_i,
  input wire jtag_rvalid_i,
  input wire jtag_rready_i,
  input wire jtag_rlast_i,
  input wire [1:0] jtag_rresp_i,

  // eFuse JTAG AXI-Lite master (SMC-OTP access-control path).
  input wire ej_awvalid_i,
  input wire ej_awready_i,
  input wire ej_wvalid_i,
  input wire ej_wready_i,
  input wire ej_bvalid_i,
  input wire ej_bready_i,
  input wire [1:0] ej_bresp_i,
  input wire ej_arvalid_i,
  input wire ej_arready_i,
  input wire ej_rvalid_i,
  input wire ej_rready_i,
  input wire [1:0] ej_rresp_i,

  // SYS_OUT outbound slave side. No rlast: the TB publishes rvalid/rready
  // and rresp for this bus, not the last-beat flag.
  input wire out_awvalid_i,
  input wire out_awready_i,
  input wire out_wvalid_i,
  input wire out_wready_i,
  input wire out_bvalid_i,
  input wire out_bready_i,
  input wire [1:0] out_bresp_i,
  input wire out_arvalid_i,
  input wire out_arready_i,
  input wire out_rvalid_i,
  input wire out_rready_i,
  input wire [1:0] out_rresp_i,
  input wire out_resp_hold_i,
  input wire [31:0] out_write_count_i,
  input wire [31:0] out_read_count_i
);

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Per-interface AXI-Lite master activity. `any_master_active` is kept
  // as its own point so the OR and its members can be compared, but it is
  // the three members that carry the information.
  // ------------------------------------------------------------------
  wire axil_dtp_csr_e = (axil_dtp_csr_active_i === 1'b1);
  wire axil_external_e = (axil_external_active_i === 1'b1);
  wire axil_efuse_bank_e = (axil_efuse_bank_active_i === 1'b1);
  // No all-idle point: idle is the quiescent state, true from reset release
  // with no stimulus, so it would be covered by construction.
  wire axil_any_e = (axil_any_master_active_i === 1'b1);
  `OCAH_FCOV_COVER(c_axil_dtp_csr_active, axil_dtp_csr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_external_active, axil_external_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_efuse_bank_active, axil_efuse_bank_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_axil_any_master_active, axil_any_e, clk_smc_i, in_reset)

  // Concurrency: two downstream interfaces active in the same cycle.
  wire [2:0] axil_actives = {axil_dtp_csr_e, axil_external_e, axil_efuse_bank_e};
  wire axil_concurrent_e = (axil_actives != 3'b000)
      && ((axil_actives & (axil_actives - 3'b001)) != 3'b000);
  `OCAH_FCOV_COVER(c_axil_concurrent_masters, axil_concurrent_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Inbound AXI managers. One smc_axi_chan_fcov per manager; the points
  // land under u_<manager> so the policy selector names the bus.
  // ------------------------------------------------------------------
  smc_axi_chan_fcov u_sep_in (
    .clk_i     (clk_smc_i),
    .rst_ni    (rst_cold_ni),
    .awvalid_i (sep_awvalid_i),
    .awready_i (sep_awready_i),
    .awlen_i   (sep_awlen_i),
    .wvalid_i  (sep_wvalid_i),
    .wready_i  (sep_wready_i),
    .wlast_i   (sep_wlast_i),
    .bvalid_i  (sep_bvalid_i),
    .bready_i  (sep_bready_i),
    .bresp_i   (sep_bresp_i),
    .arvalid_i (sep_arvalid_i),
    .arready_i (sep_arready_i),
    .arlen_i   (sep_arlen_i),
    .rvalid_i  (sep_rvalid_i),
    .rready_i  (sep_rready_i),
    .rlast_i   (sep_rlast_i),
    .rresp_i   (sep_rresp_i)
  );

  smc_axi_chan_fcov u_sys_in (
    .clk_i     (clk_smc_i),
    .rst_ni    (rst_cold_ni),
    .awvalid_i (sys_awvalid_i),
    .awready_i (sys_awready_i),
    .awlen_i   (sys_awlen_i),
    .wvalid_i  (sys_wvalid_i),
    .wready_i  (sys_wready_i),
    .wlast_i   (sys_wlast_i),
    .bvalid_i  (sys_bvalid_i),
    .bready_i  (sys_bready_i),
    .bresp_i   (sys_bresp_i),
    .arvalid_i (sys_arvalid_i),
    .arready_i (sys_arready_i),
    .arlen_i   (sys_arlen_i),
    .rvalid_i  (sys_rvalid_i),
    .rready_i  (sys_rready_i),
    .rlast_i   (sys_rlast_i),
    .rresp_i   (sys_rresp_i)
  );

  smc_axi_chan_fcov u_jtag_axi (
    .clk_i     (clk_smc_i),
    .rst_ni    (rst_cold_ni),
    .awvalid_i (jtag_awvalid_i),
    .awready_i (jtag_awready_i),
    .awlen_i   (jtag_awlen_i),
    .wvalid_i  (jtag_wvalid_i),
    .wready_i  (jtag_wready_i),
    .wlast_i   (jtag_wlast_i),
    .bvalid_i  (jtag_bvalid_i),
    .bready_i  (jtag_bready_i),
    .bresp_i   (jtag_bresp_i),
    .arvalid_i (jtag_arvalid_i),
    .arready_i (jtag_arready_i),
    .arlen_i   (jtag_arlen_i),
    .rvalid_i  (jtag_rvalid_i),
    .rready_i  (jtag_rready_i),
    .rlast_i   (jtag_rlast_i),
    .rresp_i   (jtag_rresp_i)
  );

  // ------------------------------------------------------------------
  // Transfer size / strobe shape on SEP_IN, the manager the CSR suite
  // drives. A suite that only ever issues full-width aligned words is a
  // different level of proof from one that exercises partial strobes.
  // ------------------------------------------------------------------
  wire sep_aw_accept = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_size_byte_e = sep_aw_accept && (sep_awsize_i == 3'd0);
  wire sep_size_half_e = sep_aw_accept && (sep_awsize_i == 3'd1);
  wire sep_size_word_e = sep_aw_accept && (sep_awsize_i == 3'd2);
  wire sep_size_dword_e = sep_aw_accept && (sep_awsize_i == 3'd3);
  `OCAH_FCOV_COVER(c_sep_in_awsize_byte, sep_size_byte_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_awsize_half, sep_size_half_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_awsize_word, sep_size_word_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_awsize_dword, sep_size_dword_e, clk_smc_i, in_reset)

  wire sep_burst_fixed_e = sep_aw_accept && (sep_awburst_i == 2'b00);
  wire sep_burst_incr_e = sep_aw_accept && (sep_awburst_i == 2'b01);
  wire sep_burst_wrap_e = sep_aw_accept && (sep_awburst_i == 2'b10);
  `OCAH_FCOV_COVER(c_sep_in_awburst_fixed, sep_burst_fixed_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_awburst_incr, sep_burst_incr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_awburst_wrap, sep_burst_wrap_e, clk_smc_i, in_reset)

  wire sep_w_accept = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1);
  wire sep_ar_accept = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire sep_ar_size_word_e = sep_ar_accept && (sep_arsize_i == 3'd2);
  wire sep_strb_full_e = sep_w_accept && (sep_wstrb_i == 8'hFF);
  wire sep_strb_partial_e = sep_w_accept && (sep_wstrb_i != 8'hFF) && (sep_wstrb_i != 8'h00);
  wire sep_strb_none_e = sep_w_accept && (sep_wstrb_i == 8'h00);
  `OCAH_FCOV_COVER(c_sep_in_arsize_word, sep_ar_size_word_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_wstrb_full, sep_strb_full_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_wstrb_partial, sep_strb_partial_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sep_in_wstrb_none, sep_strb_none_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // TB-owned response holds. These are the stimulus the hang detector
  // needs; a hold never engaged means the hang-irq points in
  // smc_periph_fcov cannot have been reached by the intended path.
  // ------------------------------------------------------------------
  wire sep_r_hold_e = (sep_r_hold_i === 1'b1);
  wire sys_r_hold_e = (sys_r_hold_i === 1'b1);
  wire out_resp_hold_e = (out_resp_hold_i === 1'b1);
  `OCAH_FCOV_COVER(c_sep_in_r_hold_engaged, sep_r_hold_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_in_r_hold_engaged, sys_r_hold_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_resp_hold_engaged, out_resp_hold_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // eFuse JTAG AXI-Lite (SMC-OTP access control). Lite has no burst or
  // last, so it gets handshake and response-code points only. The error
  // responses are the access-control product behaviour.
  // ------------------------------------------------------------------
  wire ej_aw_accept_e = (ej_awvalid_i === 1'b1) && (ej_awready_i === 1'b1);
  wire ej_w_accept_e = (ej_wvalid_i === 1'b1) && (ej_wready_i === 1'b1);
  wire ej_b_accept = (ej_bvalid_i === 1'b1) && (ej_bready_i === 1'b1);
  wire ej_ar_accept_e = (ej_arvalid_i === 1'b1) && (ej_arready_i === 1'b1);
  wire ej_r_accept = (ej_rvalid_i === 1'b1) && (ej_rready_i === 1'b1);
  `OCAH_FCOV_COVER(c_efuse_jtag_aw_accept, ej_aw_accept_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_w_accept, ej_w_accept_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_ar_accept, ej_ar_accept_e, clk_smc_i, in_reset)

  wire ej_bresp_okay_e = ej_b_accept && (ej_bresp_i == 2'b00);
  wire ej_bresp_slverr_e = ej_b_accept && (ej_bresp_i == 2'b10);
  wire ej_bresp_decerr_e = ej_b_accept && (ej_bresp_i == 2'b11);
  wire ej_rresp_okay_e = ej_r_accept && (ej_rresp_i == 2'b00);
  wire ej_rresp_slverr_e = ej_r_accept && (ej_rresp_i == 2'b10);
  wire ej_rresp_decerr_e = ej_r_accept && (ej_rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_efuse_jtag_bresp_okay, ej_bresp_okay_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_bresp_slverr, ej_bresp_slverr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_bresp_decerr, ej_bresp_decerr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_rresp_okay, ej_rresp_okay_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_rresp_slverr, ej_rresp_slverr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_rresp_decerr, ej_rresp_decerr_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // SYS_OUT outbound side. SLVERR here comes from the SYS_OUT slave agent's
  // fault programming, not a DUT force.
  // ------------------------------------------------------------------
  wire out_aw_accept_e = (out_awvalid_i === 1'b1) && (out_awready_i === 1'b1);
  wire out_w_accept_e = (out_wvalid_i === 1'b1) && (out_wready_i === 1'b1);
  wire out_b_accept = (out_bvalid_i === 1'b1) && (out_bready_i === 1'b1);
  wire out_ar_accept_e = (out_arvalid_i === 1'b1) && (out_arready_i === 1'b1);
  wire out_r_accept = (out_rvalid_i === 1'b1) && (out_rready_i === 1'b1);
  `OCAH_FCOV_COVER(c_sys_out_aw_accept, out_aw_accept_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_w_accept, out_w_accept_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_ar_accept, out_ar_accept_e, clk_smc_i, in_reset)

  wire out_bresp_okay_e = out_b_accept && (out_bresp_i == 2'b00);
  wire out_bresp_slverr_e = out_b_accept && (out_bresp_i == 2'b10);
  wire out_bresp_decerr_e = out_b_accept && (out_bresp_i == 2'b11);
  wire out_rresp_okay_e = out_r_accept && (out_rresp_i == 2'b00);
  wire out_rresp_slverr_e = out_r_accept && (out_rresp_i == 2'b10);
  wire out_rresp_decerr_e = out_r_accept && (out_rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_sys_out_bresp_okay, out_bresp_okay_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_bresp_slverr, out_bresp_slverr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_bresp_decerr, out_bresp_decerr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_rresp_okay, out_rresp_okay_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_rresp_slverr, out_rresp_slverr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_rresp_decerr, out_rresp_decerr_e, clk_smc_i, in_reset)

  // Traffic actually reached the outbound memory (counter advanced), which
  // is independent of a handshake being seen in any single cycle.
  logic [31:0] out_write_count_q, out_read_count_q;
  always_ff @(posedge clk_smc_i) begin
    out_write_count_q <= out_write_count_i;
    out_read_count_q <= out_read_count_i;
  end
  wire out_write_advanced_e = (out_write_count_i != out_write_count_q);
  wire out_read_advanced_e = (out_read_count_i != out_read_count_q);
  `OCAH_FCOV_COVER(c_sys_out_write_count_advanced, out_write_advanced_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_sys_out_read_count_advanced, out_read_advanced_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Data width on the AXI4 network. A full 64-bit beat is every strobe set;
  // a partial beat is some but not all, which is the half that shows the
  // strobes are honoured rather than tied.
  // ------------------------------------------------------------------
  wire sep_w_accept_beat = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1);
  wire full_64bit_beat_e = sep_w_accept_beat && (sep_wstrb_i === 8'hFF);
  wire partial_strobe_beat_e = sep_w_accept_beat && (sep_wstrb_i !== 8'hFF)
      && (sep_wstrb_i !== 8'h00) && (^sep_wstrb_i !== 1'bx);
  `OCAH_FCOV_COVER(c_full_64bit_beat, full_64bit_beat_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_partial_strobe_beat, partial_strobe_beat_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // SMC-internal 32-bit address range. Bit 31 of the internal address picks
  // the half, so both points together say the whole declared width was
  // presented rather than only the alias window.
  // ------------------------------------------------------------------
  wire sep_aw_acc_addr = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_ar_acc_addr = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire internal_addr_low_e = (sep_aw_acc_addr && (sep_awaddr_i[31] === 1'b0))
      || (sep_ar_acc_addr && (sep_araddr_i[31] === 1'b0));
  wire internal_addr_high_e = (sep_aw_acc_addr && (sep_awaddr_i[31] === 1'b1))
      || (sep_ar_acc_addr && (sep_araddr_i[31] === 1'b1));
  `OCAH_FCOV_COVER(c_internal_addr_low, internal_addr_low_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_internal_addr_high, internal_addr_high_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Response ID against the request that opened the transaction. The
  // tracker latches an ID only while it is the only transaction in flight,
  // so a match is attributed rather than coincidental.
  // ------------------------------------------------------------------
  logic [7:0] wr_out_id_q, rd_out_id_q;
  logic [5:0] wr_id_q, rd_id_q;
  logic wr_id_single_q, rd_id_single_q;
  wire sep_b_acc_id = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire sep_r_last_acc_id = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1)
      && (sep_rlast_i === 1'b1);

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      wr_out_id_q <= '0;
      rd_out_id_q <= '0;
      wr_id_q <= '0;
      rd_id_q <= '0;
      wr_id_single_q <= 1'b0;
      rd_id_single_q <= 1'b0;
    end else begin
      wr_out_id_q <= wr_out_id_q + 8'(sep_aw_acc_addr) - 8'(sep_b_acc_id);
      rd_out_id_q <= rd_out_id_q + 8'(sep_ar_acc_addr) - 8'(sep_r_last_acc_id);
      if (sep_aw_acc_addr) begin
        wr_id_q <= sep_awid_i;
        wr_id_single_q <= (wr_out_id_q == 8'd0) || ((wr_out_id_q == 8'd1) && sep_b_acc_id);
      end
      if (sep_ar_acc_addr) begin
        rd_id_q <= sep_arid_i;
        rd_id_single_q <= (rd_out_id_q == 8'd0) || ((rd_out_id_q == 8'd1) && sep_r_last_acc_id);
      end
    end
  end

  wire response_id_matches_e =
      (sep_b_acc_id && (wr_out_id_q == 8'd1) && wr_id_single_q && (sep_bid_i === wr_id_q))
      || (sep_r_last_acc_id && (rd_out_id_q == 8'd1) && rd_id_single_q
          && (sep_rid_i === rd_id_q));
  `OCAH_FCOV_COVER(c_response_id_matches_request_port, response_id_matches_e, clk_smc_i, in_reset)

`ifndef VERILATOR
  // ------------------------------------------------------------------
  // Commercial-simulator covergroup: the downstream AXI-Lite interface
  // concurrency cross. Per-manager AXI crosses live in smc_axi_chan_fcov.
  // ------------------------------------------------------------------
  covergroup cg_axil_masters with function sample (logic dtp_csr, logic external, logic efuse_bank);
    option.per_instance = 1;
    cp_dtp_csr: coverpoint dtp_csr {ignore_bins no_responder = {1'b1} with (!DtpCsrResponder);}
    cp_external: coverpoint external;
    cp_efuse_bank: coverpoint efuse_bank;
    x_concurrency: cross cp_dtp_csr, cp_external, cp_efuse_bank;
  endgroup

  covergroup cg_sep_in_shape with function sample (
      logic [2:0] awsize, logic [1:0] awburst, logic [7:0] wstrb
  );
    option.per_instance = 1;
    // SEP_IN is a 64-bit port, so AxSIZE above 3 names a beat wider than the
    // bus and no manager may drive it.
    cp_awsize: coverpoint awsize {
      bins sizes[] = {[0 : 3]}; ignore_bins wide = {[4 : 7]};
    }
    // 2'b11 is the reserved AxBURST encoding, which no manager drives. An
    // ignore bin, not illegal_bins: an illegal bin turns a hit into a runtime
    // error, which would let this coverage module end a simulation and change
    // a test's verdict. Rejecting the encoding is an assertion's job.
    cp_awburst: coverpoint awburst {
      bins fixed = {2'b00};
      bins incr = {2'b01};
      bins wrap = {2'b10};
      ignore_bins reserved = {2'b11};
    }
    cp_wstrb: coverpoint wstrb {bins none = {8'h00}; bins full = {8'hFF}; bins partial = default;}
    x_size_burst: cross cp_awsize, cp_awburst;
  endgroup

  cg_axil_masters u_cg_axil_masters = new();
  cg_sep_in_shape u_cg_sep_in_shape = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      u_cg_axil_masters.sample(axil_dtp_csr_active_i, axil_external_active_i,
                               axil_efuse_bank_active_i);
      if (sep_aw_accept) u_cg_sep_in_shape.sample(sep_awsize_i, sep_awburst_i, sep_wstrb_i);
    end
  end
`endif

endmodule : smc_fabric_fcov
