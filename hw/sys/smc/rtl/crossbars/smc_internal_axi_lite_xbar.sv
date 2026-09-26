// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route the SMC internal AXI-Lite CSR crossbar.
//
// Steers one local AXI-Lite initiator to internal CSR targets such as base config,
// filters, remaps, mailbox, and DFX.
// Address rules derive from smc_top_addrmap_pkg; arrayed blocks use their generated total
// extents.

`include "axi/typedef.svh"
`include "axi/assign.svh"

module smc_internal_axi_lite_xbar
  import axi_pkg::*;
  import smc_internal_axi_lite_xbar_pkg::*;
(
  input  logic clk_i,                   // Clock.
  input  logic rst_ni,                  // Reset.
  input  logic test_i,                  // Test.

  input  axi_lite64_req_t  local_in_req_i,  // local_in (AXI4_LITE, 64-bit) request.
  output axi_lite64_resp_t local_in_resp_o,  // local_in (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  smc_base_config_req_o,  // smc_base_config (AXI4_LITE, 64-bit)
                                                   // request.
  input  axi_lite64_resp_t smc_base_config_resp_i,  // smc_base_config (AXI4_LITE, 64-bit)
                                                    // response.

  output axi_lite64_req_t  aR_ctrl_req_o,  // aR_ctrl (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t aR_ctrl_resp_i,  // aR_ctrl (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  mR_ctrl_req_o,  // mR_ctrl (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t mR_ctrl_resp_i,  // mR_ctrl (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  xR_ctrl_req_o,  // xR_ctrl (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t xR_ctrl_resp_i,  // xR_ctrl (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  inbound_filter_ctrl_req_o,  // inbound_filter_ctrl (AXI4_LITE,
                                                       // 64-bit) request.
  input  axi_lite64_resp_t inbound_filter_ctrl_resp_i,  // inbound_filter_ctrl (AXI4_LITE,
                                                        // 64-bit) response.

  output axi_lite64_req_t  outbound_filter_ctrl_req_o,  // outbound_filter_ctrl
                                                        // (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t outbound_filter_ctrl_resp_i,  // outbound_filter_ctrl
                                                         // (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  mailbox_req_o,  // mailbox (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t mailbox_resp_i,  // mailbox (AXI4_LITE, 64-bit) response.

  output axi_lite64_req_t  dfx_csr_req_o,  // dfx_csr (AXI4_LITE, 64-bit) request.
  input  axi_lite64_resp_t dfx_csr_resp_i  // dfx_csr (AXI4_LITE, 64-bit) response.

);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  // All boundaries come from smc_top_addrmap_pkg. Array-indexed blocks use
  // _TOTAL_SIZE from the first generated instance.
  localparam addr_rule_t [NumAddrRules-1:0] AddrMap = '{
    // smc_base_config: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_{BASE_ADDR,SIZE}
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_SIZE)},
    '{idx: 1,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_BASE_ADDR(0)),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_BASE_ADDR(0)
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_ALIAS_REMAP_TOTAL_SIZE)},
    '{idx: 2,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_MMODE_REMAP_BASE_ADDR(0)),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_MMODE_REMAP_BASE_ADDR(0)
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_MMODE_REMAP_TOTAL_SIZE)},
    '{idx: 3,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_XVISOR_REMAP_BASE_ADDR(0)),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_XVISOR_REMAP_BASE_ADDR(0)
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_XVISOR_REMAP_TOTAL_SIZE)},
    '{idx: 4,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_BASE_ADDR(0)),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_BASE_ADDR(0)
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_INBOUND_FILTER_CTRL_TOTAL_SIZE)},
    '{idx: 5,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_BASE_ADDR(0)
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_TOTAL_SIZE)},
    // mailbox: RDL — smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_{BASE_ADDR,SIZE}
    '{idx: 6,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_SIZE)},
    // dfx_csr: RDL — smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_{BASE_ADDR,SIZE}
    '{idx: 7,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_SIZE)}
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  xbar_slv_req_t  [0:0] xbar_slv_req;
  xbar_slv_resp_t [0:0] xbar_slv_resp;

  // Input local_in: Direct connection (AXI4_LITE, 64-bit)
  assign xbar_slv_req[0] = local_in_req_i;
  assign local_in_resp_o = xbar_slv_resp[0];

  // ===========================================================================
  // Crossbar
  // ===========================================================================
  xbar_mst_req_t  [7:0] xbar_mst_req;
  xbar_mst_resp_t [7:0] xbar_mst_resp;

  axi_lite_xbar #(
    .Cfg          (XbarCfg),
    .aw_chan_t    (xbar_slv_aw_chan_t),
    .w_chan_t     (xbar_slv_w_chan_t),
    .b_chan_t     (xbar_slv_b_chan_t),
    .ar_chan_t    (xbar_slv_ar_chan_t),
    .r_chan_t     (xbar_slv_r_chan_t),
    .axi_req_t    (xbar_slv_req_t),
    .axi_resp_t   (xbar_slv_resp_t),
    .rule_t       (addr_rule_t)
  ) u_axi_lite_xbar (
    .clk_i                 (clk_i),
    .rst_ni                (rst_ni),
    .test_i                (test_i),
    .slv_ports_req_i       (xbar_slv_req),
    .slv_ports_resp_o      (xbar_slv_resp),
    .mst_ports_req_o       (xbar_mst_req),
    .mst_ports_resp_i      (xbar_mst_resp),
    .addr_map_i            (AddrMap),
    .en_default_mst_port_i ('0),
    .default_mst_port_i    ('0)
  );

  // ===========================================================================
  // Output Protocol/Width Conversion
  // ===========================================================================
  // ---------------------------------------------------------------------------
  // Output: smc_base_config (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign smc_base_config_req_o = xbar_mst_req[0];
  assign xbar_mst_resp[0] = smc_base_config_resp_i;

  // ---------------------------------------------------------------------------
  // Output: aR_ctrl (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign aR_ctrl_req_o = xbar_mst_req[1];
  assign xbar_mst_resp[1] = aR_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: mR_ctrl (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign mR_ctrl_req_o = xbar_mst_req[2];
  assign xbar_mst_resp[2] = mR_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: xR_ctrl (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign xR_ctrl_req_o = xbar_mst_req[3];
  assign xbar_mst_resp[3] = xR_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: inbound_filter_ctrl (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign inbound_filter_ctrl_req_o = xbar_mst_req[4];
  assign xbar_mst_resp[4] = inbound_filter_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: outbound_filter_ctrl (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign outbound_filter_ctrl_req_o = xbar_mst_req[5];
  assign xbar_mst_resp[5] = outbound_filter_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: mailbox (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign mailbox_req_o = xbar_mst_req[6];
  assign xbar_mst_resp[6] = mailbox_resp_i;

  // ---------------------------------------------------------------------------
  // Output: dfx_csr (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  assign dfx_csr_req_o = xbar_mst_req[7];
  assign xbar_mst_resp[7] = dfx_csr_resp_i;

endmodule : smc_internal_axi_lite_xbar
