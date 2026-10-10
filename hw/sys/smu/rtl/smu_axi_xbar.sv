// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route AXI traffic among SEP, SMC, and the external system port.
//
// Connect sep_out, smc_out, and ext_in initiators to sep_in, smc_in, and ext_out targets. sep_out
// reaches smc_in and ext_out, smc_out reaches sep_in and ext_out, and ext_in reaches sep_in and
// smc_in. Each aperture covers [base, base + size) bytes; a zero size disables the aperture
// whatever its base. SEP and SMC apertures are runtime CSR inputs, synchronous to clk_i (SEP, SMC,
// and this xbar all run on clk_smu_i in the SMU). sep_out and smc_out traffic matching neither
// aperture goes to ext_out; unmatched ext_in traffic gets a decode error. Output ports carry wider
// IDs than the inputs so responses route back to their initiator.

`include "ocah_assert.svh"

module smu_axi_xbar
  import smu_axi_xbar_pkg::axi_56_64_req_t;
  import smu_axi_xbar_pkg::axi_56_64_resp_t;
  import smu_axi_xbar_pkg::axi_out_req_t;
  import smu_axi_xbar_pkg::axi_out_resp_t;
  import smu_axi_xbar_pkg::addr_rule_t;
  import smu_axi_xbar_pkg::NumAddrRules;
  import smu_axi_xbar_pkg::xbar_slv_req_t;
  import smu_axi_xbar_pkg::xbar_slv_resp_t;
  import smu_axi_xbar_pkg::xbar_mst_req_t;
  import smu_axi_xbar_pkg::xbar_mst_resp_t;
  import smu_axi_xbar_pkg::XbarCfg;
  import smu_axi_xbar_pkg::Connectivity;
  import smu_axi_xbar_pkg::xbar_slv_aw_chan_t;
  import smu_axi_xbar_pkg::xbar_mst_aw_chan_t;
  import smu_axi_xbar_pkg::xbar_slv_w_chan_t;
  import smu_axi_xbar_pkg::xbar_slv_b_chan_t;
  import smu_axi_xbar_pkg::xbar_mst_b_chan_t;
  import smu_axi_xbar_pkg::xbar_slv_ar_chan_t;
  import smu_axi_xbar_pkg::xbar_mst_ar_chan_t;
  import smu_axi_xbar_pkg::xbar_slv_r_chan_t;
  import smu_axi_xbar_pkg::xbar_mst_r_chan_t;
(
  input  wire logic clk_i,                      // SMU fabric clock.
  input  wire logic rst_ni,                     // Active-low reset.
  input  wire logic test_i,                     // DFT test enable for the crossbar.

  input  wire logic [55:0] sep_global_base_addr_i,  // SEP aperture base address; synchronous to
                                                    // clk_i. In smu, driven from the SEP CSRs.
  input  wire logic [31:0] sep_region_size_i,   // SEP aperture size in bytes.
                                                // Synchronous to clk_i. In smu, driven from
                                                // the SEP CSRs.
  input  wire logic [55:0] smc_global_base_addr_i,  // SMC aperture base address; synchronous to
                                                    // clk_i. In smu, driven from the SMC CSRs.
  input  wire logic [31:0] smc_region_size_i,   // SMC aperture size in bytes.
                                                // Synchronous to clk_i. In smu, driven from
                                                // the SMC CSRs.

  input  axi_56_64_req_t  sep_out_req_i,        // SEP initiator AXI4 request (64-bit) into the
                                                // crossbar.
  output axi_56_64_resp_t sep_out_resp_o,       // SEP initiator AXI4 response from the crossbar.

  input  axi_56_64_req_t  smc_out_req_i,        // SMC initiator AXI4 request (64-bit) into the
                                                // crossbar.
  output axi_56_64_resp_t smc_out_resp_o,       // SMC initiator AXI4 response from the crossbar.

  input  axi_56_64_req_t  ext_in_req_i,         // External initiator AXI4 request (64-bit) into the
                                                // crossbar.
  output axi_56_64_resp_t ext_in_resp_o,        // External initiator AXI4 response from the
                                                // crossbar.

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

  // reject when sep_region_size_i is 0 by setting to an arbitrary all 1s start and end address
  function automatic addr_rule_t aperture_rule(int unsigned idx, logic [55:0] base,
                                               logic [31:0] size);
    aperture_rule.idx = idx;
    if (size == '0) begin
      aperture_rule.start_addr = '1;
      aperture_rule.end_addr   = 57'(56'('1));
    end else begin
      aperture_rule.start_addr = base;
      aperture_rule.end_addr   = 57'(base) + 57'(size);
    end
  endfunction

  always_comb begin
    addr_map[0] = aperture_rule(32'd0, sep_global_base_addr_i, sep_region_size_i);
    addr_map[1] = aperture_rule(32'd1, smc_global_base_addr_i, smc_region_size_i);
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

`ifdef OCAH_DEBUG_LIVE
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
