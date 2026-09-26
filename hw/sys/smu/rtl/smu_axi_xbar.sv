// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route AXI traffic among SEP, SMC, and the external system port.
//
// Connect sep_out, smc_out, and ext_in initiators to sep_in, smc_in, and ext_out targets.
// SEP and SMC apertures are runtime CSR inputs, synchronous to clk_i (SEP, SMC, and this
// xbar all run on clk_smu_i in the SMU). Unmatched outbound traffic uses the external
// output.

module smu_axi_xbar
  import axi_pkg::*;
  import smu_axi_xbar_pkg::*;
(
  input  wire logic clk_i,                      // SMU fabric clock.
  input  wire logic rst_ni,                     // Active-low reset.
  input  wire logic test_i,                     // DFT test enable for the crossbar.

  input  wire logic [55:0] sep_global_base_addr_i,  // SEP aperture base from the SEP CSRs
                                                    // Synchronous to clk_i.
  input  wire logic [31:0] sep_region_size_i,   // SEP aperture size from the SEP CSRs
                                                // Synchronous to clk_i.
  input  wire logic [55:0] smc_global_base_addr_i,  // SMC aperture base from the SMC CSRs
                                                    // Synchronous to clk_i.
  input  wire logic [31:0] smc_region_size_i,   // SMC aperture size from the SMC CSRs
                                                // Synchronous to clk_i.

  input  axi_56_64_req_t  sep_out_req_i,        // SEP initiator AXI4 request (64-bit) into the crossbar.
  output axi_56_64_resp_t sep_out_resp_o,       // SEP initiator AXI4 response from the crossbar.

  input  axi_56_64_req_t  smc_out_req_i,        // SMC initiator AXI4 request (64-bit) into the crossbar.
  output axi_56_64_resp_t smc_out_resp_o,       // SMC initiator AXI4 response from the crossbar.

  input  axi_56_64_req_t  ext_in_req_i,         // External initiator AXI4 request (64-bit) into the crossbar.
  output axi_56_64_resp_t ext_in_resp_o,        // External initiator AXI4 response from the crossbar.

  output axi_out_req_t  sep_in_req_o,           // AXI4 request toward the SEP target port.
  input  axi_out_resp_t sep_in_resp_i,          // AXI4 response from the SEP target port.

  output axi_out_req_t  smc_in_req_o,           // AXI4 request toward the SMC target port.
  input  axi_out_resp_t smc_in_resp_i,          // AXI4 response from the SMC target port.

  output axi_out_req_t  ext_out_req_o,          // AXI4 request toward the external target port.
  input  axi_out_resp_t ext_out_resp_i          // AXI4 response from the external target port.
);

  // =========================================================================
  // Runtime Address Map
  // =========================================================================
  // idx 0 -> sep_in  (base+size from SEP CSR)
  // idx 1 -> smc_in  (base+size from SMC CSR)
  // ext_out (idx 2) has no rule: sep_out/smc_out reach it via the crossbar's
  // default master port for any address matching neither aperture. ext_in is
  // not connected to ext_out, so its unmatched accesses still decode-error.
  addr_rule_t [NumAddrRules-1:0] addr_map;

  always_comb begin
    addr_map[0].idx        = 32'd0;
    addr_map[0].start_addr = sep_global_base_addr_i;
    addr_map[0].end_addr   = 57'(sep_global_base_addr_i) + 57'(sep_region_size_i);

    addr_map[1].idx        = 32'd1;
    addr_map[1].start_addr = smc_global_base_addr_i;
    addr_map[1].end_addr   = 57'(smc_global_base_addr_i) + 57'(smc_region_size_i);
  end

  // =========================================================================
  // Input Adaptation to Crossbar Types
  // =========================================================================
  xbar_slv_req_t  [2:0] xbar_slv_req;
  xbar_slv_resp_t [2:0] xbar_slv_resp;

  // Input sep_out: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[0] = sep_out_req_i;
  assign sep_out_resp_o  = xbar_slv_resp[0];

  // Input smc_out: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[1] = smc_out_req_i;
  assign smc_out_resp_o  = xbar_slv_resp[1];

  // Input ext_in: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[2] = ext_in_req_i;
  assign ext_in_resp_o   = xbar_slv_resp[2];

  // =========================================================================
  // Crossbar
  // =========================================================================
  xbar_mst_req_t  [2:0] xbar_mst_req;
  xbar_mst_resp_t [2:0] xbar_mst_resp;

  axi_xbar #(
    .Cfg          (XbarCfg),
    .ATOPs        (1'b0),
    .Connectivity (Connectivity),
    .slv_aw_chan_t(xbar_slv_aw_chan_t),
    .mst_aw_chan_t(xbar_mst_aw_chan_t),
    .w_chan_t     (xbar_slv_w_chan_t),
    .slv_b_chan_t (xbar_slv_b_chan_t),
    .mst_b_chan_t (xbar_mst_b_chan_t),
    .slv_ar_chan_t(xbar_slv_ar_chan_t),
    .mst_ar_chan_t(xbar_mst_ar_chan_t),
    .slv_r_chan_t (xbar_slv_r_chan_t),
    .mst_r_chan_t (xbar_mst_r_chan_t),
    .slv_req_t    (xbar_slv_req_t),
    .slv_resp_t   (xbar_slv_resp_t),
    .mst_req_t    (xbar_mst_req_t),
    .mst_resp_t   (xbar_mst_resp_t),
    .rule_t       (addr_rule_t)
  ) u_axi_xbar (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .test_i                (test_i),
    .sel_hash_i            (2'b0),
    .slv_ports_req_i       (xbar_slv_req),
    .slv_ports_resp_o      (xbar_slv_resp),
    .mst_ports_req_o       (xbar_mst_req),
    .mst_ports_resp_i      (xbar_mst_resp),
    .addr_map_i            (addr_map),
    // Only sep_out (slv 0) and smc_out (slv 1) are connected to ext_out, so
    // only they fall through to it; ext_in (slv 2) keeps decode-erroring.
    .en_default_mst_port_i (3'b011),
    .default_mst_port_i    ({2'd0, 2'd2, 2'd2})
  );

  // =========================================================================
  // Output Direct Connections
  // =========================================================================
  assign sep_in_req_o      = xbar_mst_req[0];
  assign xbar_mst_resp[0]  = sep_in_resp_i;

  assign smc_in_req_o      = xbar_mst_req[1];
  assign xbar_mst_resp[1]  = smc_in_resp_i;

  assign ext_out_req_o     = xbar_mst_req[2];
  assign xbar_mst_resp[2]  = ext_out_resp_i;

`ifndef SYNTHESIS
  // SVA: SEP and SMC apertures must not overlap once programmed.
  // Ignore the trivial case where either aperture size is zero.
  logic [56:0] sep_end;
  logic [56:0] smc_end;
  assign sep_end = 57'(sep_global_base_addr_i) + 57'(sep_region_size_i);
  assign smc_end = 57'(smc_global_base_addr_i) + 57'(smc_region_size_i);

  sep_smc_no_overlap_a:
  assert property (
        @(posedge clk_i) disable iff (!rst_ni)
        (sep_region_size_i == '0) || (smc_region_size_i == '0) ||
        (sep_end <= 57'(smc_global_base_addr_i)) ||
        (smc_end <= 57'(sep_global_base_addr_i))
    )
  else $error("smu_axi_xbar: SEP and SMC apertures overlap");
`endif

endmodule : smu_axi_xbar
