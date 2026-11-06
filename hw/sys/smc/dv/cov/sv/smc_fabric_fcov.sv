// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC fabric functional coverage: the `axil_master` intent of SMC_FCOV.adoc
// plus the inbound/outbound AXI traffic it stands in for, and the covergroups
// smc_sys_out_error_cg and smc_outstanding_cg.
//
// Each downstream interface's activity is its own point, and each inbound AXI
// manager gets a smc_axi_chan_fcov instance carrying handshake, burst-shape
// and response-code points, so a response code the suite never produces is
// a named hole.
//
// smc_sys_out_error_cg attributes each SYS_OUT transaction to the manager
// that issued it from bench state: the DMA and zeroer busy nets and a shadow
// of their job registers as written over SEP_IN, or a JTAG request
// outstanding at the JTAG port with that address. smc_outstanding_cg keeps a
// per-port count of accepted requests less completions and grades each run
// of overlapping accesses by its peak and the response ready held under it.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal or a member of the u_output_axi_if instance.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_fabric_fcov (
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
  input wire [63:0] sep_wdata_i,
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
  // The DUT's R valid ahead of the bench R hold (tb_sep_axi_r_raw_valid).
  input wire sep_r_raw_valid_i,
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
  // The DUT's R valid ahead of the bench R hold (tb_sys_axi_r_raw_valid).
  input wire sys_r_raw_valid_i,

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
  // JTAG addresses and IDs, for the requests outstanding at the port.
  input wire [55:0] jtag_awaddr_i,
  input wire [55:0] jtag_araddr_i,
  input wire [1:0] jtag_awid_i,
  input wire [1:0] jtag_arid_i,
  input wire [1:0] jtag_bid_i,
  input wire [1:0] jtag_rid_i,

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

  // SYS_OUT outbound slave side: the handshakes and codes of the signal
  // list, and the addresses, IDs, lengths, sizes and last-beat flag of the
  // u_output_axi_if members (16-bit ID members carry the port's 8-bit ID).
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
  input wire [31:0] out_read_count_i,
  input wire [55:0] out_awaddr_i,
  input wire [55:0] out_araddr_i,
  input wire [15:0] out_awid_i,
  input wire [15:0] out_arid_i,
  input wire [15:0] out_bid_i,
  input wire [15:0] out_rid_i,
  input wire [7:0] out_awlen_i,
  input wire [2:0] out_awsize_i,
  input wire [7:0] out_arlen_i,
  input wire [2:0] out_arsize_i,
  input wire out_rlast_i,

  // Engine activity (tb_dma_busy, tb_zeroer_busy).
  input wire dma_busy_i,
  input wire zeroer_busy_i,

  // The primary reset, which holds the fabric and drops its outstanding
  // accesses.
  input wire rst_primary_ni,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i
);

  import smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SRC_ADDRESS_LO_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SRC_ADDRESS_HI_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_DST_ADDRESS_HI_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_LENGTH_LO_BASE_ADDR;
  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_LENGTH_HI_BASE_ADDR;

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
`ifdef SMC_FCOV_PHASE2
  // Phase 2 (SMC_FCOV.adoc): the DTP CSR port is served by the DTP, which
  // smc_wrapper leaves outside the bench with the port unterminated.
  `OCAH_FCOV_COVER(c_axil_dtp_csr_active, axil_dtp_csr_e, clk_smc_i, in_reset)
`endif
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
`ifdef SMC_FCOV_PHASE2
  // Phase 2 (SMC_FCOV.adoc): a zero-strobe beat is legal AXI, but the bench
  // AXI manager derives WSTRB from the bytes a payload covers and cannot
  // present one.
  `OCAH_FCOV_COVER(c_sep_in_wstrb_none, sep_strb_none_e, clk_smc_i, in_reset)
`endif

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

  // A request the lifecycle policy blocks gets "an error response" from the
  // port's error slave (efuse architecture.adoc, JTAG Access Control Based on
  // LC_STATE), which the DECERR points record; an admitted request is
  // answered OKAY.
  wire ej_bresp_okay_e = ej_b_accept && (ej_bresp_i == 2'b00);
  wire ej_bresp_decerr_e = ej_b_accept && (ej_bresp_i == 2'b11);
  wire ej_rresp_okay_e = ej_r_accept && (ej_rresp_i == 2'b00);
  wire ej_rresp_decerr_e = ej_r_accept && (ej_rresp_i == 2'b11);
  `OCAH_FCOV_COVER(c_efuse_jtag_bresp_okay, ej_bresp_okay_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_bresp_decerr, ej_bresp_decerr_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_efuse_jtag_rresp_okay, ej_rresp_okay_e, clk_smc_i, in_reset)
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

  // ------------------------------------------------------------------
  // Covergroups: the downstream AXI-Lite interface concurrency cross and the
  // SEP_IN write shape. The per-manager burst-length and response groups
  // live in smc_axi_chan_fcov.
  // ------------------------------------------------------------------
  covergroup cg_axil_masters with function sample (logic dtp_csr, logic external, logic efuse_bank);
    option.per_instance = 1;
    // The SMC bench ties the DTP CSR AXI-Lite response port off, so no access
    // to it completes and none is issued.
    cp_dtp_csr: coverpoint dtp_csr {
      ignore_bins no_responder = {1'b1};
    }
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
    // A zero-strobe beat is legal AXI, but the bench AXI manager derives WSTRB
    // from the bytes a payload covers and cannot present one; it is in the
    // Phase 2 set with c_sep_in_wstrb_none.
    cp_wstrb: coverpoint wstrb {
      bins full = {8'hFF}; bins partial = default; ignore_bins none = {8'h00};
    }
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

  // ------------------------------------------------------------------
  // Graded-window gate, shared by the two covergroups below.
  // ------------------------------------------------------------------
  wire gate_on = (fcov_gate_i === 1'b1);
  logic gate_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) gate_q <= 1'b0;
    else gate_q <= gate_on;
  end
  wire gate_rise = gate_on && !gate_q;

  // ------------------------------------------------------------------
  // Shadow of the zeroer and DMA job registers (SMC_FCOV.adoc,
  // smc_sys_out_error_cg): the last SEP_IN write that completed OKAY at
  // each, from the single beat. The 64-bit zeroer registers take the whole
  // beat with every strobe set; the 32-bit DMA registers take the lane their
  // address selects with its four strobes set. One SEP_IN write is
  // outstanding at a time. The shadow follows the cold reset only.
  // ------------------------------------------------------------------
  localparam logic [55:0] ZeroerDestAddr = 56'(SMC_TOP_ZEROER_CTRL_DEST_ADDR_BASE_ADDR);
  localparam logic [55:0] ZeroerSizeAddr = 56'(SMC_TOP_ZEROER_CTRL_SIZE_BASE_ADDR);
  localparam logic [55:0] DmaSrcLoAddr = 56'(SMC_TOP_DMA_CTRL_SRC_ADDRESS_LO_BASE_ADDR);
  localparam logic [55:0] DmaSrcHiAddr = 56'(SMC_TOP_DMA_CTRL_SRC_ADDRESS_HI_BASE_ADDR);
  localparam logic [55:0] DmaDstLoAddr = 56'(SMC_TOP_DMA_CTRL_DST_ADDRESS_LO_BASE_ADDR);
  localparam logic [55:0] DmaDstHiAddr = 56'(SMC_TOP_DMA_CTRL_DST_ADDRESS_HI_BASE_ADDR);
  localparam logic [55:0] DmaLenLoAddr = 56'(SMC_TOP_DMA_CTRL_LENGTH_LO_BASE_ADDR);
  localparam logic [55:0] DmaLenHiAddr = 56'(SMC_TOP_DMA_CTRL_LENGTH_HI_BASE_ADDR);

  wire job_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire job_b_okay = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1)
      && (sep_bresp_i === 2'b00);
  logic [55:0] job_waddr_q;
  logic [63:0] job_wdata_q;
  logic [7:0] job_wstrb_q;
  wire job_full = (job_wstrb_q === 8'hFF);
  wire job_lane_hi = job_waddr_q[2];
  wire [31:0] job_lane = job_lane_hi ? job_wdata_q[63:32] : job_wdata_q[31:0];
  wire job_lane_full = job_lane_hi ? (job_wstrb_q[7:4] === 4'hF) : (job_wstrb_q[3:0] === 4'hF);
  wire job_zeroer_w = job_b_okay && job_full
      && ((job_waddr_q == ZeroerDestAddr) || (job_waddr_q == ZeroerSizeAddr));

  logic [63:0] zeroer_dest_q, zeroer_size_q, dma_src_q, dma_dst_q, dma_len_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      job_waddr_q <= '0;
      job_wdata_q <= '0;
      job_wstrb_q <= '0;
      zeroer_dest_q <= '0;
      zeroer_size_q <= '0;
      dma_src_q <= '0;
      dma_dst_q <= '0;
      dma_len_q <= '0;
    end else begin
      if (sep_aw_accept) job_waddr_q <= sep_awaddr_i;
      if (job_w_last_acc) begin
        job_wdata_q <= sep_wdata_i;
        job_wstrb_q <= sep_wstrb_i;
      end
      if (job_b_okay && job_full) begin
        // DEST_ADDR[63:56] are ignored by the 56-bit master (zeroer.adoc).
        if (job_waddr_q == ZeroerDestAddr) zeroer_dest_q <= 64'(job_wdata_q[55:0]);
        if (job_waddr_q == ZeroerSizeAddr) zeroer_size_q <= job_wdata_q;
      end
      if (job_b_okay && job_lane_full) begin
        case (job_waddr_q)
          DmaSrcLoAddr: dma_src_q[31:0] <= job_lane;
          DmaSrcHiAddr: dma_src_q[63:32] <= job_lane;
          DmaDstLoAddr: dma_dst_q[31:0] <= job_lane;
          DmaDstHiAddr: dma_dst_q[63:32] <= job_lane;
          DmaLenLoAddr: dma_len_q[31:0] <= job_lane;
          DmaLenHiAddr: dma_len_q[63:32] <= job_lane;
          default: ;
        endcase
      end
    end
  end

  // ------------------------------------------------------------------
  // JTAG port: the requests outstanding per direction (address and ID, kept
  // from the AW or AR accept to the B or R-last accept of that ID, oldest
  // first; the port's ID is 2 bits and same-ID completions are in order), the
  // accepts less completions, the address of an access issued alone, and the
  // first non-OKAY beat of a read per ID.
  // ------------------------------------------------------------------
  wire jt_aw_acc = (jtag_awvalid_i === 1'b1) && (jtag_awready_i === 1'b1);
  wire jt_ar_acc = (jtag_arvalid_i === 1'b1) && (jtag_arready_i === 1'b1);
  wire jt_b_acc = (jtag_bvalid_i === 1'b1) && (jtag_bready_i === 1'b1);
  wire jt_r_acc = (jtag_rvalid_i === 1'b1) && (jtag_rready_i === 1'b1);
  wire jt_r_last_acc = jt_r_acc && (jtag_rlast_i === 1'b1);

  // Saturating count: a completion of an access accepted before the last
  // clear does not take the count below zero.
  function automatic logic [7:0] count_step(input logic [7:0] cnt, input logic inc,
                                            input logic dec);
    logic [8:0] next;
    next = {1'b0, cnt} + {8'd0, inc};
    if (dec && (next != 9'd0)) next = next - 9'd1;
    return (next > 9'd255) ? 8'd255 : next[7:0];
  endfunction

  localparam int unsigned JtDepth = 32;
  typedef struct packed {
    logic valid;
    logic [1:0] id;
    logic [55:0] addr;
    logic [15:0] seq;
  } jt_req_t;

  jt_req_t jt_wr_tbl_q[JtDepth];
  jt_req_t jt_rd_tbl_q[JtDepth];
  logic [15:0] jt_seq_q;
  logic jt_wr_free_v, jt_rd_free_v, jt_wr_pop_v, jt_rd_pop_v;
  logic [4:0] jt_wr_free, jt_rd_free, jt_wr_pop, jt_rd_pop;
  always_comb begin
    jt_wr_free_v = 1'b0;
    jt_rd_free_v = 1'b0;
    jt_wr_pop_v = 1'b0;
    jt_rd_pop_v = 1'b0;
    jt_wr_free = '0;
    jt_rd_free = '0;
    jt_wr_pop = '0;
    jt_rd_pop = '0;
    for (int unsigned i = 0; i < JtDepth; i++) begin
      if (!jt_wr_tbl_q[i].valid && !jt_wr_free_v) begin
        jt_wr_free_v = 1'b1;
        jt_wr_free = 5'(i);
      end
      if (!jt_rd_tbl_q[i].valid && !jt_rd_free_v) begin
        jt_rd_free_v = 1'b1;
        jt_rd_free = 5'(i);
      end
      if (jt_wr_tbl_q[i].valid && (jt_wr_tbl_q[i].id == jtag_bid_i)
          && (!jt_wr_pop_v || (jt_wr_tbl_q[i].seq < jt_wr_tbl_q[jt_wr_pop].seq))) begin
        jt_wr_pop_v = 1'b1;
        jt_wr_pop = 5'(i);
      end
      if (jt_rd_tbl_q[i].valid && (jt_rd_tbl_q[i].id == jtag_rid_i)
          && (!jt_rd_pop_v || (jt_rd_tbl_q[i].seq < jt_rd_tbl_q[jt_rd_pop].seq))) begin
        jt_rd_pop_v = 1'b1;
        jt_rd_pop = 5'(i);
      end
    end
  end

  logic [7:0] jt_wr_q, jt_rd_q;
  logic [55:0] jt_wr_addr_q, jt_rd_addr_q;
  logic jt_wr_single_q, jt_rd_single_q;
  logic [1:0] jt_rd_err_q[4];
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < JtDepth; i++) begin
        jt_wr_tbl_q[i] <= '0;
        jt_rd_tbl_q[i] <= '0;
      end
      jt_seq_q <= '0;
      jt_wr_q <= '0;
      jt_rd_q <= '0;
      jt_wr_addr_q <= '0;
      jt_rd_addr_q <= '0;
      jt_wr_single_q <= 1'b0;
      jt_rd_single_q <= 1'b0;
      for (int unsigned i = 0; i < 4; i++) jt_rd_err_q[i] <= 2'b00;
    end else begin
      if (jt_b_acc && jt_wr_pop_v) jt_wr_tbl_q[jt_wr_pop].valid <= 1'b0;
      if (jt_r_last_acc && jt_rd_pop_v) jt_rd_tbl_q[jt_rd_pop].valid <= 1'b0;
      if (jt_aw_acc && jt_wr_free_v) begin
        jt_wr_tbl_q[jt_wr_free] <= '{
            valid: 1'b1,
            id: jtag_awid_i,
            addr: jtag_awaddr_i,
            seq: jt_seq_q
        };
      end
      if (jt_ar_acc && jt_rd_free_v) begin
        jt_rd_tbl_q[jt_rd_free] <= '{
            valid: 1'b1,
            id: jtag_arid_i,
            addr: jtag_araddr_i,
            seq: jt_seq_q + 16'd1
        };
      end
      jt_seq_q <= jt_seq_q + 16'(jt_aw_acc) + 16'(jt_ar_acc);
      jt_wr_q <= count_step(jt_wr_q, jt_aw_acc, jt_b_acc);
      jt_rd_q <= count_step(jt_rd_q, jt_ar_acc, jt_r_last_acc);
      if (jt_aw_acc) begin
        jt_wr_addr_q <= jtag_awaddr_i;
        jt_wr_single_q <= (jt_wr_q == 8'd0) || ((jt_wr_q == 8'd1) && jt_b_acc);
      end
      if (jt_ar_acc) begin
        jt_rd_addr_q <= jtag_araddr_i;
        jt_rd_single_q <= (jt_rd_q == 8'd0) || ((jt_rd_q == 8'd1) && jt_r_last_acc);
      end
      if (jt_r_acc) begin
        if (jt_r_last_acc) jt_rd_err_q[jtag_rid_i] <= 2'b00;
        else if ((jtag_rresp_i[1] === 1'b1) && (jt_rd_err_q[jtag_rid_i] == 2'b00)) begin
          jt_rd_err_q[jtag_rid_i] <= jtag_rresp_i;
        end
      end
    end
  end
  // A SYS_OUT address equal to that of a JTAG request outstanding at the port.
  logic jt_wr_match, jt_rd_match;
  always_comb begin
    jt_wr_match = 1'b0;
    jt_rd_match = 1'b0;
    for (int unsigned i = 0; i < JtDepth; i++) begin
      if (jt_wr_tbl_q[i].valid && (jt_wr_tbl_q[i].addr == out_awaddr_i)) jt_wr_match = 1'b1;
      if (jt_rd_tbl_q[i].valid && (jt_rd_tbl_q[i].addr == out_araddr_i)) jt_rd_match = 1'b1;
    end
  end
  wire [1:0] jt_rd_code = (jt_rd_err_q[jtag_rid_i] != 2'b00) ? jt_rd_err_q[jtag_rid_i]
                                                              : jtag_rresp_i;

  // ------------------------------------------------------------------
  // smc_sys_out_error_cg: the issuing manager and direction of every SYS_OUT
  // transaction, from bench state at its address handshake. A zeroer write
  // lies inside the shadowed zeroer job while tb_zeroer_busy is high; a DMA
  // read or write inside the shadowed copy's source or destination while
  // tb_dma_busy is high; a JTAG access when a JTAG request of the same
  // direction with that address is outstanding at the JTAG port (the alias
  // remap and the outbound filter leave the address unchanged under the
  // owner's reset regions and pass-all entry). The burst position
  // is read against the job range: first at its base, last when the burst
  // reaches its end, middle otherwise, which is the position of the same
  // burst in the uninjected reference job the owner keys its injection to.
  // Transactions are kept per direction in a table of 32, matched to their
  // response by ID, oldest first; the code of a read is its first non-OKAY
  // beat. The table runs ungated.
  // ------------------------------------------------------------------
  localparam logic [2:0] MgrNone = 3'd0;
  localparam logic [2:0] MgrJtagRd = 3'd1;
  localparam logic [2:0] MgrJtagWr = 3'd2;
  localparam logic [2:0] MgrDmaRd = 3'd3;
  localparam logic [2:0] MgrDmaWr = 3'd4;
  localparam logic [2:0] MgrZeroerWr = 3'd5;
  localparam logic [1:0] BurstFirst = 2'd0;
  localparam logic [1:0] BurstMiddle = 2'd1;
  localparam logic [1:0] BurstLast = 2'd2;
  localparam int unsigned OutDepth = 32;

  typedef struct packed {
    logic valid;
    logic [15:0] id;
    logic [2:0] mgr;
    logic [1:0] pos;
    logic [1:0] code;
    logic [31:0] seq;
  } out_txn_t;

  function automatic logic in_win(input logic [63:0] addr, input logic [63:0] lo,
                                  input logic [63:0] hi);
    return (addr >= lo) && (addr < hi);
  endfunction

  function automatic logic [1:0] burst_pos(input logic [63:0] addr, input logic [63:0] bytes,
                                           input logic [63:0] lo, input logic [63:0] hi);
    if (addr == lo) return BurstFirst;
    if (addr + bytes == hi) return BurstLast;
    return BurstMiddle;
  endfunction

  wire [63:0] out_aw_addr = 64'(out_awaddr_i);
  wire [63:0] out_ar_addr = 64'(out_araddr_i);
  wire [63:0] out_aw_bytes = (64'(out_awlen_i) + 64'd1) << out_awsize_i;
  wire [63:0] out_ar_bytes = (64'(out_arlen_i) + 64'd1) << out_arsize_i;
  wire [63:0] zeroer_top = zeroer_dest_q + zeroer_size_q;
  wire [63:0] dma_src_top = dma_src_q + dma_len_q;
  wire [63:0] dma_dst_top = dma_dst_q + dma_len_q;
  wire aw_zeroer = (zeroer_busy_i === 1'b1) && in_win(out_aw_addr, zeroer_dest_q, zeroer_top);
  wire aw_dma = (dma_busy_i === 1'b1) && in_win(out_aw_addr, dma_dst_q, dma_dst_top);
  wire ar_dma = (dma_busy_i === 1'b1) && in_win(out_ar_addr, dma_src_q, dma_src_top);
  wire [2:0] aw_mgr = aw_zeroer ? MgrZeroerWr : aw_dma ? MgrDmaWr
                    : jt_wr_match ? MgrJtagWr : MgrNone;
  wire [2:0] ar_mgr = ar_dma ? MgrDmaRd : jt_rd_match ? MgrJtagRd : MgrNone;
  wire [1:0] aw_pos = aw_zeroer ? burst_pos(out_aw_addr, out_aw_bytes, zeroer_dest_q, zeroer_top)
                    : burst_pos(out_aw_addr, out_aw_bytes, dma_dst_q, dma_dst_top);
  wire [1:0] ar_pos = burst_pos(out_ar_addr, out_ar_bytes, dma_src_q, dma_src_top);

  out_txn_t out_wr_q[OutDepth];
  out_txn_t out_rd_q[OutDepth];
  logic [31:0] out_seq_q;
  // The free slot a push takes and the oldest entry of the responding ID.
  logic wr_free_v, rd_free_v, wr_pop_v, rd_pop_v;
  logic [4:0] wr_free, rd_free, wr_pop, rd_pop;
  always_comb begin
    wr_free_v = 1'b0;
    rd_free_v = 1'b0;
    wr_pop_v = 1'b0;
    rd_pop_v = 1'b0;
    wr_free = '0;
    rd_free = '0;
    wr_pop = '0;
    rd_pop = '0;
    for (int unsigned i = 0; i < OutDepth; i++) begin
      if (!out_wr_q[i].valid && !wr_free_v) begin
        wr_free_v = 1'b1;
        wr_free = 5'(i);
      end
      if (!out_rd_q[i].valid && !rd_free_v) begin
        rd_free_v = 1'b1;
        rd_free = 5'(i);
      end
      if (out_wr_q[i].valid && (out_wr_q[i].id == out_bid_i)
          && (!wr_pop_v || (out_wr_q[i].seq < out_wr_q[wr_pop].seq))) begin
        wr_pop_v = 1'b1;
        wr_pop = 5'(i);
      end
      if (out_rd_q[i].valid && (out_rd_q[i].id == out_rid_i)
          && (!rd_pop_v || (out_rd_q[i].seq < out_rd_q[rd_pop].seq))) begin
        rd_pop_v = 1'b1;
        rd_pop = 5'(i);
      end
    end
  end

  wire wr_pop_e = out_b_accept && wr_pop_v;
  wire rd_pop_e = out_r_accept && (out_rlast_i === 1'b1) && rd_pop_v;
  wire [1:0] rd_pop_code = (out_rd_q[rd_pop].code != 2'b00) ? out_rd_q[rd_pop].code : out_rresp_i;

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < OutDepth; i++) begin
        out_wr_q[i] <= '0;
        out_rd_q[i] <= '0;
      end
      out_seq_q <= '0;
    end else begin
      if (wr_pop_e) out_wr_q[wr_pop].valid <= 1'b0;
      if (rd_pop_e) begin
        out_rd_q[rd_pop].valid <= 1'b0;
      end else if (out_r_accept && rd_pop_v && (out_rresp_i[1] === 1'b1)
                   && (out_rd_q[rd_pop].code == 2'b00)) begin
        out_rd_q[rd_pop].code <= out_rresp_i;
      end
      if (out_aw_accept_e && wr_free_v) begin
        out_wr_q[wr_free] <= '{
            valid: 1'b1,
            id: out_awid_i,
            mgr: aw_mgr,
            pos: aw_pos,
            code: 2'b00,
            seq: out_seq_q
        };
      end
      if (out_ar_accept_e && rd_free_v) begin
        out_rd_q[rd_free] <= '{
            valid: 1'b1,
            id: out_arid_i,
            mgr: ar_mgr,
            pos: ar_pos,
            code: 2'b00,
            seq: out_seq_q + 32'd1
        };
      end
      out_seq_q <= out_seq_q + 32'(out_aw_accept_e) + 32'(out_ar_accept_e);
    end
  end

  // Owner-specific qualifier beside the gate: the group samples once the
  // zeroer DEST_ADDR or SIZE register has been written over SEP_IN while the
  // gate was high, and stays open until the next cold reset: the owning leaf
  // holds the gate low over each DMA launch it issues (the NEXT_ID_0 read is
  // the sample event of smc_dma_geometry_cg), so the flag survives those
  // dips. No other owner writes a zeroer register under its gate.
  logic soe_live_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) soe_live_q <= 1'b0;
    else if (gate_on && job_zeroer_w) soe_live_q <= 1'b1;
  end

  wire soe_wr_err = wr_pop_e && (out_bresp_i[1] === 1'b1);
  wire soe_rd_err = rd_pop_e && (rd_pop_code[1] === 1'b1);
  wire soe_err_e = gate_on && soe_live_q && (soe_wr_err || soe_rd_err);
  // A read and a write completing with an error in the same cycle sample the
  // write only; the owner injects one error per pass.
  out_txn_t soe_txn;
  assign soe_txn = soe_wr_err ? out_wr_q[wr_pop] : out_rd_q[rd_pop];
  wire soe_code = soe_wr_err ? out_bresp_i[0] : rd_pop_code[0];
  wire soe_graded = soe_err_e && (soe_txn.mgr != MgrNone);
  wire soe_job = soe_graded && (soe_txn.mgr == MgrDmaRd || soe_txn.mgr == MgrDmaWr
                                || soe_txn.mgr == MgrZeroerWr);
  wire [1:0] soe_job_kind = (soe_txn.mgr == MgrDmaRd) ? 2'd0
                          : (soe_txn.mgr == MgrDmaWr) ? 2'd1 : 2'd2;

  // The code at the JTAG port, the issuer's view.
  wire soe_jt_wr_err = jt_b_acc && (jtag_bresp_i[1] === 1'b1);
  wire soe_jt_rd_err = jt_r_last_acc && (jt_rd_code[1] === 1'b1);
  wire soe_jt_e = gate_on && soe_live_q && (soe_jt_wr_err || soe_jt_rd_err);
  wire soe_jt_code = soe_jt_wr_err ? jtag_bresp_i[0] : jt_rd_code[0];

  // The recovery pair: after an injected error, a JTAG write issued alone at
  // an address inside no shadowed job completing OKAY, then a JTAG read of
  // that address, issued alone, completing OKAY on every beat.
  logic err_seen_q, rec_pend_q;
  logic [55:0] rec_addr_q;
  wire [63:0] jt_wr_addr = 64'(jt_wr_addr_q);
  wire rec_addr_free = !in_win(jt_wr_addr, zeroer_dest_q, zeroer_top)
      && !in_win(jt_wr_addr, dma_src_q, dma_src_top) && !in_win(jt_wr_addr, dma_dst_q, dma_dst_top);
  wire rec_wr_e = jt_b_acc && (jtag_bresp_i === 2'b00) && err_seen_q && jt_wr_single_q
      && rec_addr_free;
  wire rec_rd_e = jt_r_last_acc && (jt_rd_code === 2'b00) && rec_pend_q && jt_rd_single_q
      && (jt_rd_addr_q == rec_addr_q);
  wire soe_rec_e = gate_on && soe_live_q && rec_rd_e;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      err_seen_q <= 1'b0;
      rec_pend_q <= 1'b0;
      rec_addr_q <= '0;
    end else begin
      if (soe_err_e) err_seen_q <= 1'b1;
      else if (soe_rec_e) err_seen_q <= 1'b0;
      if (rec_wr_e) begin
        rec_pend_q <= 1'b1;
        rec_addr_q <= jt_wr_addr_q;
      end else if (soe_rec_e) begin
        rec_pend_q <= 1'b0;
      end
    end
  end

  // Each sample fills the coverpoints of its event and passes the others a
  // value no bin lists. The 12 DMA cells are recorded bins (rec_*).
  covergroup smc_sys_out_error_cg with function sample (
      logic mgr_graded,
      logic [2:0] mgr,
      logic job_graded,
      logic [1:0] job,
      logic code,
      logic [1:0] pos,
      logic jtag_graded,
      logic jtag_write,
      logic jtag_code,
      logic recovery
  );
    option.per_instance = 1;
    // {graded, manager and direction}: 5 cells.
    cp_mgr_dir: coverpoint {
      mgr_graded, mgr
    } {
      bins jtag_read = {{1'b1, MgrJtagRd}};
      bins jtag_write = {{1'b1, MgrJtagWr}};
      bins dma_read = {{1'b1, MgrDmaRd}};
      bins dma_write = {{1'b1, MgrDmaWr}};
      bins zeroer_write = {{1'b1, MgrZeroerWr}};
    }
    // {graded, job manager, code (0 SLVERR, 1 DECERR), burst}: the 6 zeroer
    // cells and the 12 DMA recorded bins.
    cp_job_code_burst: coverpoint {
      job_graded, job, code, pos
    } {
      bins zw_slverr_first = {{1'b1, 2'd2, 1'b0, BurstFirst}};
      bins zw_slverr_middle = {{1'b1, 2'd2, 1'b0, BurstMiddle}};
      bins zw_slverr_last = {{1'b1, 2'd2, 1'b0, BurstLast}};
      bins zw_decerr_first = {{1'b1, 2'd2, 1'b1, BurstFirst}};
      bins zw_decerr_middle = {{1'b1, 2'd2, 1'b1, BurstMiddle}};
      bins zw_decerr_last = {{1'b1, 2'd2, 1'b1, BurstLast}};
      bins rec_dr_slverr_first = {{1'b1, 2'd0, 1'b0, BurstFirst}};
      bins rec_dr_slverr_middle = {{1'b1, 2'd0, 1'b0, BurstMiddle}};
      bins rec_dr_slverr_last = {{1'b1, 2'd0, 1'b0, BurstLast}};
      bins rec_dr_decerr_first = {{1'b1, 2'd0, 1'b1, BurstFirst}};
      bins rec_dr_decerr_middle = {{1'b1, 2'd0, 1'b1, BurstMiddle}};
      bins rec_dr_decerr_last = {{1'b1, 2'd0, 1'b1, BurstLast}};
      bins rec_dw_slverr_first = {{1'b1, 2'd1, 1'b0, BurstFirst}};
      bins rec_dw_slverr_middle = {{1'b1, 2'd1, 1'b0, BurstMiddle}};
      bins rec_dw_slverr_last = {{1'b1, 2'd1, 1'b0, BurstLast}};
      bins rec_dw_decerr_first = {{1'b1, 2'd1, 1'b1, BurstFirst}};
      bins rec_dw_decerr_middle = {{1'b1, 2'd1, 1'b1, BurstMiddle}};
      bins rec_dw_decerr_last = {{1'b1, 2'd1, 1'b1, BurstLast}};
    }
    // {graded, direction, code} at the JTAG port: 4 cells.
    cp_jtag_code: coverpoint {
      jtag_graded, jtag_write, jtag_code
    } {
      bins rd_slverr = {3'b1_0_0};
      bins rd_decerr = {3'b1_0_1};
      bins wr_slverr = {3'b1_1_0};
      bins wr_decerr = {3'b1_1_1};
    }
    // The recovery write then read answering OKAY after an error: 1 cell.
    cp_recovery: coverpoint recovery {
      bins okay_pair = {1'b1};
    }
  endgroup

  smc_sys_out_error_cg u_cg_sys_out_error = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (soe_err_e) begin
        u_cg_sys_out_error.sample(soe_graded, soe_graded ? soe_txn.mgr : MgrNone, soe_job,
                                  soe_job ? soe_job_kind : 2'd3, soe_job && soe_code,
                                  soe_job ? soe_txn.pos : 2'd3, 1'b0, 1'b0, 1'b0, 1'b0);
      end
      if (soe_jt_e) begin
        u_cg_sys_out_error.sample(1'b0, MgrNone, 1'b0, 2'd3, 1'b0, 2'd3, 1'b1, soe_jt_wr_err,
                                  soe_jt_code, 1'b0);
      end
      if (soe_rec_e) begin
        u_cg_sys_out_error.sample(1'b0, MgrNone, 1'b0, 2'd3, 1'b0, 2'd3, 1'b0, 1'b0, 1'b0, 1'b1);
      end
    end
  end

  // ------------------------------------------------------------------
  // smc_outstanding_cg: per inbound port, accepted requests less completions
  // (AW and AR accepts less B and R-last accepts), cleared by the cold and
  // the primary reset and on every rise of the gate, so the count holds the
  // window's own accesses; a completion before the port's first accept of
  // the window is not subtracted. An episode opens on the accept that takes
  // the count from zero and closes on the completion that returns it there;
  // its peak and the response ready held inside it are sampled at the close:
  // BVALID high with BREADY low at the port, and on R the DUT's raw R valid
  // high without a handshake where the bench gates R toward the manager
  // (SEP_IN, SYS_IN; the gate hides RVALID while it holds), RVALID high with
  // RREADY low on JTAG.
  // ------------------------------------------------------------------
  localparam int unsigned NumPorts = 3;
  localparam logic [1:0] PortSepIn = 2'd0;
  localparam logic [1:0] PortSysIn = 2'd1;
  localparam logic [1:0] PortJtag = 2'd2;
  localparam logic [1:0] HoldNone = 2'd0;
  localparam logic [1:0] HoldBready = 2'd1;
  localparam logic [1:0] HoldRready = 2'd2;

  wire sys_aw_acc = (sys_awvalid_i === 1'b1) && (sys_awready_i === 1'b1);
  wire sys_ar_acc = (sys_arvalid_i === 1'b1) && (sys_arready_i === 1'b1);
  wire sys_b_acc = (sys_bvalid_i === 1'b1) && (sys_bready_i === 1'b1);
  wire sys_r_last_acc = (sys_rvalid_i === 1'b1) && (sys_rready_i === 1'b1)
      && (sys_rlast_i === 1'b1);
  wire [NumPorts-1:0] po_aw_acc = {jt_aw_acc, sys_aw_acc, sep_aw_accept};
  wire [NumPorts-1:0] po_ar_acc = {jt_ar_acc, sys_ar_acc, sep_ar_accept};
  wire [NumPorts-1:0] po_b_acc = {jt_b_acc, sys_b_acc, sep_b_acc_id};
  wire [NumPorts-1:0] po_r_last_acc = {jt_r_last_acc, sys_r_last_acc, sep_r_last_acc_id};
  wire [NumPorts-1:0] po_b_stall = {
    (jtag_bvalid_i === 1'b1) && (jtag_bready_i !== 1'b1),
    (sys_bvalid_i === 1'b1) && (sys_bready_i !== 1'b1),
    (sep_bvalid_i === 1'b1) && (sep_bready_i !== 1'b1)
  };
  wire [NumPorts-1:0] po_r_stall = {
    (jtag_rvalid_i === 1'b1) && (jtag_rready_i !== 1'b1),
    (sys_r_raw_valid_i === 1'b1) && !((sys_rvalid_i === 1'b1) && (sys_rready_i === 1'b1)),
    (sep_r_raw_valid_i === 1'b1) && !((sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1))
  };

  wire trk_clear = in_reset || (rst_primary_ni !== 1'b1) || gate_rise;
  logic [7:0] po_n_q[NumPorts];
  logic [7:0] po_peak_q[NumPorts];
  logic po_armed_q[NumPorts];
  logic po_ep_q[NumPorts];
  logic po_held_b_q[NumPorts];
  logic po_held_r_q[NumPorts];
  logic [7:0] po_n_next[NumPorts];
  logic [1:0] po_inc[NumPorts];
  logic [1:0] po_dec[NumPorts];
  always_comb begin
    for (int unsigned i = 0; i < NumPorts; i++) begin
      po_inc[i] = {1'b0, po_aw_acc[i]} + {1'b0, po_ar_acc[i]};
      po_dec[i] = po_armed_q[i] ? ({1'b0, po_b_acc[i]} + {1'b0, po_r_last_acc[i]}) : 2'd0;
      po_n_next[i] = po_n_q[i] + 8'(po_inc[i]);
      po_n_next[i] = (po_n_next[i] >= 8'(po_dec[i])) ? po_n_next[i] - 8'(po_dec[i]) : 8'd0;
    end
  end

  always_ff @(posedge clk_smc_i) begin
    for (int unsigned i = 0; i < NumPorts; i++) begin
      if (trk_clear) begin
        po_n_q[i] <= '0;
        po_peak_q[i] <= '0;
        po_armed_q[i] <= 1'b0;
        po_ep_q[i] <= 1'b0;
        po_held_b_q[i] <= 1'b0;
        po_held_r_q[i] <= 1'b0;
      end else begin
        po_n_q[i] <= po_n_next[i];
        if (po_inc[i] != 2'd0) po_armed_q[i] <= 1'b1;
        if (!po_ep_q[i] && (po_inc[i] != 2'd0)) begin
          po_ep_q[i] <= 1'b1;
          po_peak_q[i] <= po_n_next[i];
          po_held_b_q[i] <= po_b_stall[i];
          po_held_r_q[i] <= po_r_stall[i];
        end else if (po_ep_q[i]) begin
          if (po_n_next[i] > po_peak_q[i]) po_peak_q[i] <= po_n_next[i];
          if (po_b_stall[i]) po_held_b_q[i] <= 1'b1;
          if (po_r_stall[i]) po_held_r_q[i] <= 1'b1;
          if (po_n_next[i] == 8'd0) po_ep_q[i] <= 1'b0;
        end
      end
    end
  end

  // Owner-specific qualifier beside the gate: the group samples once two of
  // the window's accesses have been outstanding together on SEP_IN or SYS_IN
  // since the gate rose (a group of the owner or the co-owner; every other
  // owner issues its accesses on those ports one at a time), until the gate
  // falls.
  logic out_live_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset || !gate_on) out_live_q <= 1'b0;
    else if ((po_n_next[PortSepIn] >= 8'd2) || (po_n_next[PortSysIn] >= 8'd2)) begin
      out_live_q <= 1'b1;
    end
  end

  // Depth buckets of the row: 1, 2 to 4, 5 to 8, 9 to 16, 17 to 24; another
  // value maps to code 7, which no bin lists.
  function automatic logic [2:0] depth_bucket(input logic [7:0] n);
    if (n == 8'd1) return 3'd0;
    if (n >= 8'd2 && n <= 8'd4) return 3'd1;
    if (n >= 8'd5 && n <= 8'd8) return 3'd2;
    if (n >= 8'd9 && n <= 8'd16) return 3'd3;
    if (n >= 8'd17 && n <= 8'd24) return 3'd4;
    return 3'd7;
  endfunction

  // The 5 depth bins of one port; every bin leads with the graded flag.
  `define SMC_OUT_DEPTH_BINS(name, port) \
      bins name``_d1 = {{1'b1, port, 3'd0}}; \
      bins name``_d2_4 = {{1'b1, port, 3'd1}}; \
      bins name``_d5_8 = {{1'b1, port, 3'd2}}; \
      bins name``_d9_16 = {{1'b1, port, 3'd3}}; \
      bins name``_d17_24 = {{1'b1, port, 3'd4}};

  covergroup smc_outstanding_cg with function sample (
      logic graded, logic [1:0] port, logic [2:0] bucket, logic [1:0] hold
  );
    option.per_instance = 1;
    // {graded, port, depth bucket}: 15 cells.
    cp_depth: coverpoint {
      graded, port, bucket
    } {
      `SMC_OUT_DEPTH_BINS(sep_in, PortSepIn)
      `SMC_OUT_DEPTH_BINS(sys_in, PortSysIn)
      `SMC_OUT_DEPTH_BINS(jtag, PortJtag)
    }
    // {graded, port, held ready, depth bucket}: the 13 cells the co-owner's
    // walk puts under each hold.
    cp_hold: coverpoint {
      graded, port, hold, bucket
    } {
      bins sep_in_none_d1 = {{1'b1, PortSepIn, HoldNone, 3'd0}};
      bins sys_in_none_d1 = {{1'b1, PortSysIn, HoldNone, 3'd0}};
      bins jtag_none_d1 = {{1'b1, PortJtag, HoldNone, 3'd0}};
      bins sep_in_none_d9_16 = {{1'b1, PortSepIn, HoldNone, 3'd3}};
      bins sys_in_none_d9_16 = {{1'b1, PortSysIn, HoldNone, 3'd3}};
      bins jtag_none_d9_16 = {{1'b1, PortJtag, HoldNone, 3'd3}};
      bins sep_in_none_d2_4 = {{1'b1, PortSepIn, HoldNone, 3'd1}};
      bins sep_in_bready_d5_8 = {{1'b1, PortSepIn, HoldBready, 3'd2}};
      bins sys_in_bready_d5_8 = {{1'b1, PortSysIn, HoldBready, 3'd2}};
      bins jtag_bready_d5_8 = {{1'b1, PortJtag, HoldBready, 3'd2}};
      bins sep_in_rready_d1 = {{1'b1, PortSepIn, HoldRready, 3'd0}};
      bins sys_in_rready_d1 = {{1'b1, PortSysIn, HoldRready, 3'd0}};
      bins jtag_rready_d1 = {{1'b1, PortJtag, HoldRready, 3'd0}};
    }
  endgroup
  `undef SMC_OUT_DEPTH_BINS

  smc_outstanding_cg u_cg_outstanding = new();

  logic [NumPorts-1:0] po_close;
  logic [1:0] po_hold[NumPorts];
  always_comb begin
    for (int unsigned i = 0; i < NumPorts; i++) begin
      po_close[i] = po_ep_q[i] && (po_n_next[i] == 8'd0);
      po_hold[i] = {po_held_r_q[i] || po_r_stall[i], po_held_b_q[i] || po_b_stall[i]};
    end
  end

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset && gate_on && out_live_q) begin
      for (int unsigned i = 0; i < NumPorts; i++) begin
        if (po_close[i]) begin
          u_cg_outstanding.sample(1'b1, 2'(i), depth_bucket(po_peak_q[i]), po_hold[i]);
        end
      end
    end
  end

endmodule : smc_fabric_fcov
