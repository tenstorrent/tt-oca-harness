// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Route the SMC local AXI crossbar.
//
// Connects the system, SEP and local initiators from the SMC input fabric to local SMC
// targets over full AXI, without atomic operations. The CSR targets are converted on the
// way out: the internal-register port to 64-bit AXI-Lite, the peripheral port to 32-bit
// AXI-Lite and the DFD port to 32-bit APB. Addresses outside every rule, including gaps
// between CPU-cluster resources, receive DECERR.
// Address rules are built here from smc_top_addrmap_pkg; types and crossbar
// configuration come from smc_local_xbar_pkg.

`include "axi/typedef.svh"
`include "axi/assign.svh"

module smc_local_xbar
  import axi_pkg::*;
  import smc_local_xbar_pkg::*;
(
  input  logic clk_i,                   // SMC core clock.
  input  logic rst_ni,                  // Primary reset, active-low, synchronized to the SMC core
                                        // clock.
  input  logic test_i,                  // Scan test mode enable, forwarded to the test input of the
                                        // AXI crossbar.

  input  axi64_req_t  system_req_i,     // System request from the input fabric, rebased into
                                        // the local SMC aperture.
  output axi64_resp_t system_resp_o,    // Response to the system initiator.

  input  axi64_req_t  sep_in_req_i,     // SEP request from the input fabric, rebased into the
                                        // local SMC aperture.
  output axi64_resp_t sep_in_resp_o,    // Response to the SEP initiator.

  input  axi64_req_t  local_in_req_i,   // Request from the input fabric's local port, rebased
                                        // into the local SMC aperture.
  output axi64_resp_t local_in_resp_o,  // Response to the input fabric's local port.

  output axi_out_req_t  front_port_req_o,  // Request to the CPU cluster front port for the
                                           // core watchdogs, CPU control, SPM ROM and SPM,
                                           // PLIC, CLINT and core bus-error units.
  input  axi_out_resp_t front_port_resp_i,  // Response from the CPU cluster front port.

  output axi_out_req_t  data_accel_ctrl_req_o,  // Request for the DMA and zeroer control
                                                // windows of the data accelerator.
  input  axi_out_resp_t data_accel_ctrl_resp_i,  // Response from the data accelerator
                                                 // control port.

  output axi_lite64_req_t  local_reg_req_o,  // Request to the internal CSR crossbar for the
                                             // base config through mailbox windows and the
                                             // DFX control window.
  input  axi_lite64_resp_t local_reg_resp_i,  // Response from the internal CSR crossbar.

  output axi_lite32_req_t  periph_reg_req_o,  // Request to the peripheral CSR crossbar for
                                              // the reset unit through DTP control windows,
                                              // the I3C wrapper and smc_external.
  input  axi_lite32_resp_t periph_reg_resp_i,  // Response from the peripheral CSR crossbar.

  output apb32_req_t  smc_dfd_reg_req_o,  // Request for the SMC CLA window.
  input  apb32_resp_t smc_dfd_reg_resp_i  // Response from the SMC CLA.
);

  // ===========================================================================
  // Address Map Configuration
  // ===========================================================================
  // Direct CPU-cluster resources use separate rules so gaps between them
  // decode-error here instead of reaching the cluster. The debug module's
  // hart-facing window has no rule: only the cluster's harts may reach it.
  localparam addr_rule_t [NumAddrRules-1:0] AddrMap = '{
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_WDT_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_WDT_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_WDT_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CPU_CTRL_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SPM_MEMORY_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_PLIC_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CLINT_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_BEU_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_BEU_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_BEU_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE1_BEU_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_BEU_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE2_BEU_SIZE)},
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_BEU_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE3_BEU_SIZE)},
    '{idx: 1,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_SIZE)},
    '{idx: 1,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_ZEROER_CTRL_SIZE)},
    // The internal and peripheral child xbars reject holes within these
    // generated aggregate bounds.
    '{idx: 2,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_MAILBOX_SIZE)},
    '{idx: 2,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_DFX_CTRL_SIZE)},
    '{idx: 3,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_DTP_CTRL_REG_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_DTP_CTRL_REG_SIZE)},
    '{idx: 3,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_OCA_I3C_WRAP_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_OCA_I3C_WRAP_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_OCA_I3C_WRAP_SIZE)},
    '{idx: 3,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_SIZE)},
    '{idx: 4,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_SIZE)}
  };

  // ===========================================================================
  // Input Protocol/Width Conversion (to match crossbar)
  // ===========================================================================
  xbar_slv_req_t  [2:0] xbar_slv_req;
  xbar_slv_resp_t [2:0] xbar_slv_resp;

  // Input system: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[0] = system_req_i;
  assign system_resp_o = xbar_slv_resp[0];

  // Input sep_in: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[1] = sep_in_req_i;
  assign sep_in_resp_o = xbar_slv_resp[1];

  // Input local_in: Direct connection (AXI4, 64-bit)
  assign xbar_slv_req[2] = local_in_req_i;
  assign local_in_resp_o = xbar_slv_resp[2];

  // ===========================================================================
  // Crossbar
  // ===========================================================================
  xbar_mst_req_t  [4:0] xbar_mst_req;
  xbar_mst_resp_t [4:0] xbar_mst_resp;

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
    .addr_map_i            (AddrMap),
    .en_default_mst_port_i ('0),
    .default_mst_port_i    ('0)
  );

  // ===========================================================================
  // Output Protocol/Width Conversion
  // ===========================================================================
  // ---------------------------------------------------------------------------
  // Output: front_port (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  assign front_port_req_o = xbar_mst_req[0];
  assign xbar_mst_resp[0] = front_port_resp_i;

  // ---------------------------------------------------------------------------
  // Output: data_accel_ctrl (AXI4, 64-bit)
  // ---------------------------------------------------------------------------
  assign data_accel_ctrl_req_o = xbar_mst_req[1];
  assign xbar_mst_resp[1] = data_accel_ctrl_resp_i;

  // ---------------------------------------------------------------------------
  // Output: local_reg (AXI4_LITE, 64-bit)
  // ---------------------------------------------------------------------------
  // Conversion chain: axi_to_axi_lite
  // Signal declarations
  xbar_out_local_reg_req_t  xbar_out_local_reg_req;
  xbar_out_local_reg_resp_t xbar_out_local_reg_resp;
  local_reg_req_t  local_reg_req;
  local_reg_resp_t local_reg_resp;

  // Xbar to chain connection
  assign xbar_out_local_reg_req = xbar_mst_req[2];
  assign xbar_mst_resp[2] = xbar_out_local_reg_resp;

  // Conversion instances
  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    (32),
    .AxiDataWidth    (64),
    .AxiIdWidth      (8),
    .AxiUserWidth    (12),
    .AxiMaxWriteTxns (8),
    .AxiMaxReadTxns  (8),
    .FallThrough     (1'b0),
    .full_req_t      (xbar_out_local_reg_req_t),
    .full_resp_t     (xbar_out_local_reg_resp_t),
    .lite_req_t      (local_reg_req_t),
    .lite_resp_t     (local_reg_resp_t)
  ) u_local_reg_a2l_1 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (xbar_out_local_reg_req),
    .slv_resp_o (xbar_out_local_reg_resp),
    .mst_req_o  (local_reg_req),
    .mst_resp_i (local_reg_resp)
  );

  // Chain to output port connection
  assign local_reg_req_o = local_reg_req;
  assign local_reg_resp = local_reg_resp_i;

  // ---------------------------------------------------------------------------
  // Output: periph_reg (AXI4_LITE, 32-bit)
  // ---------------------------------------------------------------------------
  // Conversion chain: axi_dw_converter -> axi_to_axi_lite
  // Signal declarations
  xbar_out_periph_reg_req_t  xbar_out_periph_reg_req;
  xbar_out_periph_reg_resp_t xbar_out_periph_reg_resp;
  periph_reg_stage1_req_t  periph_reg_stage1_req;
  periph_reg_stage1_resp_t periph_reg_stage1_resp;
  periph_reg_req_t  periph_reg_req;
  periph_reg_resp_t periph_reg_resp;

  // Xbar to chain connection
  assign xbar_out_periph_reg_req = xbar_mst_req[3];
  assign xbar_mst_resp[3] = xbar_out_periph_reg_resp;

  // Conversion instances
  // AXI Data Width Converter: 64-bit -> 32-bit
  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (64),
    .AxiMstPortDataWidth (32),
    .AxiAddrWidth        (32),
    .AxiIdWidth          (8),
    .aw_chan_t           (periph_reg_stage1_aw_chan_t),
    .mst_w_chan_t        (periph_reg_stage1_w_chan_t),
    .slv_w_chan_t        (xbar_out_periph_reg_w_chan_t),
    .b_chan_t            (periph_reg_stage1_b_chan_t),
    .ar_chan_t           (periph_reg_stage1_ar_chan_t),
    .mst_r_chan_t        (periph_reg_stage1_r_chan_t),
    .slv_r_chan_t        (xbar_out_periph_reg_r_chan_t),
    .axi_mst_req_t       (periph_reg_stage1_req_t),
    .axi_mst_resp_t      (periph_reg_stage1_resp_t),
    .axi_slv_req_t       (xbar_out_periph_reg_req_t),
    .axi_slv_resp_t      (xbar_out_periph_reg_resp_t)
  ) u_periph_reg_dw_1 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (xbar_out_periph_reg_req),
    .slv_resp_o (xbar_out_periph_reg_resp),
    .mst_req_o  (periph_reg_stage1_req),
    .mst_resp_i (periph_reg_stage1_resp)
  );

  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    (32),
    .AxiDataWidth    (32),
    .AxiIdWidth      (8),
    .AxiUserWidth    (12),
    .AxiMaxWriteTxns (8),
    .AxiMaxReadTxns  (8),
    .FallThrough     (1'b0),
    .full_req_t      (periph_reg_stage1_req_t),
    .full_resp_t     (periph_reg_stage1_resp_t),
    .lite_req_t      (periph_reg_req_t),
    .lite_resp_t     (periph_reg_resp_t)
  ) u_periph_reg_a2l_2 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (periph_reg_stage1_req),
    .slv_resp_o (periph_reg_stage1_resp),
    .mst_req_o  (periph_reg_req),
    .mst_resp_i (periph_reg_resp)
  );

  // Chain to output port connection
  assign periph_reg_req_o = periph_reg_req;
  assign periph_reg_resp = periph_reg_resp_i;

  // ---------------------------------------------------------------------------
  // Output: smc_dfd_reg (APB4, 32-bit)
  // ---------------------------------------------------------------------------
  // Conversion chain: axi_dw_converter -> axi_to_axi_lite -> axi_lite_to_apb
  // Signal declarations
  xbar_out_smc_dfd_reg_req_t  xbar_out_smc_dfd_reg_req;
  xbar_out_smc_dfd_reg_resp_t xbar_out_smc_dfd_reg_resp;
  smc_dfd_reg_stage1_req_t  smc_dfd_reg_stage1_req;
  smc_dfd_reg_stage1_resp_t smc_dfd_reg_stage1_resp;
  smc_dfd_reg_stage2_req_t  smc_dfd_reg_stage2_req;
  smc_dfd_reg_stage2_resp_t smc_dfd_reg_stage2_resp;
  smc_dfd_reg_req_t  smc_dfd_reg_req;
  smc_dfd_reg_resp_t smc_dfd_reg_resp;

  // Xbar to chain connection
  assign xbar_out_smc_dfd_reg_req = xbar_mst_req[4];
  assign xbar_mst_resp[4] = xbar_out_smc_dfd_reg_resp;

  // Conversion instances
  // AXI Data Width Converter: 64-bit -> 32-bit
  axi_dw_converter #(
    .AxiMaxReads         (8),
    .AxiSlvPortDataWidth (64),
    .AxiMstPortDataWidth (32),
    .AxiAddrWidth        (32),
    .AxiIdWidth          (8),
    .aw_chan_t           (smc_dfd_reg_stage1_aw_chan_t),
    .mst_w_chan_t        (smc_dfd_reg_stage1_w_chan_t),
    .slv_w_chan_t        (xbar_out_smc_dfd_reg_w_chan_t),
    .b_chan_t            (smc_dfd_reg_stage1_b_chan_t),
    .ar_chan_t           (smc_dfd_reg_stage1_ar_chan_t),
    .mst_r_chan_t        (smc_dfd_reg_stage1_r_chan_t),
    .slv_r_chan_t        (xbar_out_smc_dfd_reg_r_chan_t),
    .axi_mst_req_t       (smc_dfd_reg_stage1_req_t),
    .axi_mst_resp_t      (smc_dfd_reg_stage1_resp_t),
    .axi_slv_req_t       (xbar_out_smc_dfd_reg_req_t),
    .axi_slv_resp_t      (xbar_out_smc_dfd_reg_resp_t)
  ) u_smc_dfd_reg_dw_1 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .slv_req_i  (xbar_out_smc_dfd_reg_req),
    .slv_resp_o (xbar_out_smc_dfd_reg_resp),
    .mst_req_o  (smc_dfd_reg_stage1_req),
    .mst_resp_i (smc_dfd_reg_stage1_resp)
  );

  // AXI to AXI-Lite Protocol Converter
  axi_to_axi_lite #(
    .AxiAddrWidth    (32),
    .AxiDataWidth    (32),
    .AxiIdWidth      (8),
    .AxiUserWidth    (12),
    .AxiMaxWriteTxns (8),
    .AxiMaxReadTxns  (8),
    .FallThrough     (1'b0),
    .full_req_t      (smc_dfd_reg_stage1_req_t),
    .full_resp_t     (smc_dfd_reg_stage1_resp_t),
    .lite_req_t      (smc_dfd_reg_stage2_req_t),
    .lite_resp_t     (smc_dfd_reg_stage2_resp_t)
  ) u_smc_dfd_reg_a2l_2 (
    .clk_i      (clk_i),
    .rst_ni     (rst_ni),
    .test_i     (1'b0),
    .slv_req_i  (smc_dfd_reg_stage1_req),
    .slv_resp_o (smc_dfd_reg_stage1_resp),
    .mst_req_o  (smc_dfd_reg_stage2_req),
    .mst_resp_i (smc_dfd_reg_stage2_resp)
  );

  // AXI-Lite to APB Bridge (1 APB slave)
  localparam apb_addr_rule_t [0:0] SmcDfdRegApbAddrMap = '{
    '{idx: 0,
      start_addr: 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_BASE_ADDR),
      end_addr:   33'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_BASE_ADDR
                    + smc_top_addrmap_pkg::SMC_TOP_SMC_CLA_SIZE)}
  };

  axi_lite_to_apb #(
    .NoApbSlaves      (1),
    .NoRules          (1),
    .AddrWidth        (32),
    .DataWidth        (32),
    .PipelineRequest  (1'b1),
    .PipelineResponse (1'b1),
    .axi_lite_req_t   (smc_dfd_reg_stage2_req_t),
    .axi_lite_resp_t  (smc_dfd_reg_stage2_resp_t),
    .apb_req_t        (smc_dfd_reg_req_t),
    .apb_resp_t       (smc_dfd_reg_resp_t),
    .rule_t           (apb_addr_rule_t)
  ) u_smc_dfd_reg_l2apb_3 (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .axi_lite_req_i  (smc_dfd_reg_stage2_req),
    .axi_lite_resp_o (smc_dfd_reg_stage2_resp),
    .apb_req_o       (smc_dfd_reg_req),
    .apb_resp_i      (smc_dfd_reg_resp),
    .addr_map_i      (SmcDfdRegApbAddrMap)
  );

  // Chain to output port connection
  assign smc_dfd_reg_req_o = smc_dfd_reg_req;
  assign smc_dfd_reg_resp = smc_dfd_reg_resp_i;

endmodule : smc_local_xbar
