// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SEP local AXI crossbar types and address constants.
//
// Hand-maintained: fabric_gen's static config cannot express this crossbar, so
// it is not regenerated. The in-scope constants (dma_csr, sep_wdt) derive their
// windows from sep_top_addrmap_pkg so the RDL stays authoritative for
// those extents; the remaining constants are still literal apertures.

`include "axi/typedef.svh"

package sep_local_axi_xbar_pkg;

  import axi_pkg::*;

  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs = 5;
  localparam int unsigned NumOutputs = 10;
  localparam int unsigned NumAddrRules = 15;
  localparam int unsigned MaxInputIdW = 3;
  localparam int unsigned XbarOutputIdW = 6;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi64 (AXI4)
  typedef logic [31:0] axi64_addr_t;
  typedef logic [63:0] axi64_data_t;
  typedef logic [7:0] axi64_strb_t;
  typedef logic [2:0] axi64_id_t;
  typedef logic [11:0] axi64_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi64_aw_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi64_w_chan_t, axi64_data_t, axi64_strb_t, axi64_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi64_b_chan_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi64_ar_chan_t, axi64_addr_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi64_r_chan_t, axi64_data_t, axi64_id_t, axi64_user_t)
  `AXI_TYPEDEF_REQ_T(axi64_req_t, axi64_aw_chan_t, axi64_w_chan_t, axi64_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi64_resp_t, axi64_b_chan_t, axi64_r_chan_t)
  // ===========================================================================
  // Crossbar Internal Types
  // ===========================================================================
  localparam int unsigned XbarDataWidth = 64;
  localparam int unsigned XbarStrbWidth = 8;
  localparam int unsigned XbarAddrWidth = 32;
  localparam int unsigned XbarUserWidth = 12;

  // ===========================================================================
  // AXI4 Output Type Definition (unified type with expanded ID width)
  // ===========================================================================
  // All AXI4 outputs use this type with xbar-expanded ID width
  typedef logic [XbarAddrWidth-1:0] axi_out_addr_t;
  typedef logic [XbarDataWidth-1:0] axi_out_data_t;
  typedef logic [XbarStrbWidth-1:0] axi_out_strb_t;
  typedef logic [XbarOutputIdW-1:0] axi_out_id_t;
  typedef logic [XbarUserWidth-1:0] axi_out_user_t;

  `AXI_TYPEDEF_AW_CHAN_T(axi_out_aw_chan_t, axi_out_addr_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_W_CHAN_T(axi_out_w_chan_t, axi_out_data_t, axi_out_strb_t, axi_out_user_t)
  `AXI_TYPEDEF_B_CHAN_T(axi_out_b_chan_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(axi_out_ar_chan_t, axi_out_addr_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_R_CHAN_T(axi_out_r_chan_t, axi_out_data_t, axi_out_id_t, axi_out_user_t)
  `AXI_TYPEDEF_REQ_T(axi_out_req_t, axi_out_aw_chan_t, axi_out_w_chan_t, axi_out_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(axi_out_resp_t, axi_out_b_chan_t, axi_out_r_chan_t)

  typedef logic [XbarAddrWidth-1:0] xbar_addr_t;
  typedef logic [XbarDataWidth-1:0] xbar_data_t;
  typedef logic [XbarStrbWidth-1:0] xbar_strb_t;
  typedef logic [MaxInputIdW-1:0] xbar_slv_id_t;
  typedef logic [XbarOutputIdW-1:0] xbar_mst_id_t;
  typedef logic [XbarUserWidth-1:0] xbar_user_t;

  // Crossbar slave port (input) types - Full AXI
  `AXI_TYPEDEF_AW_CHAN_T(xbar_slv_aw_chan_t, xbar_addr_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_W_CHAN_T(xbar_slv_w_chan_t, xbar_data_t, xbar_strb_t, xbar_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_slv_b_chan_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_slv_ar_chan_t, xbar_addr_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_slv_r_chan_t, xbar_data_t, xbar_slv_id_t, xbar_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_slv_req_t, xbar_slv_aw_chan_t, xbar_slv_w_chan_t, xbar_slv_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_slv_resp_t, xbar_slv_b_chan_t, xbar_slv_r_chan_t)

  // Crossbar master port (output) types - Full AXI
  `AXI_TYPEDEF_AW_CHAN_T(xbar_mst_aw_chan_t, xbar_addr_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_B_CHAN_T(xbar_mst_b_chan_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_AR_CHAN_T(xbar_mst_ar_chan_t, xbar_addr_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_R_CHAN_T(xbar_mst_r_chan_t, xbar_data_t, xbar_mst_id_t, xbar_user_t)
  `AXI_TYPEDEF_REQ_T(xbar_mst_req_t, xbar_mst_aw_chan_t, xbar_slv_w_chan_t, xbar_mst_ar_chan_t)
  `AXI_TYPEDEF_RESP_T(xbar_mst_resp_t, xbar_mst_b_chan_t, xbar_mst_r_chan_t)

  // ===========================================================================
  // Input Conversion Intermediate Types
  // ===========================================================================
  // ===========================================================================
  // Output Conversion Chain Intermediate Types
  // ===========================================================================

  // ===========================================================================
  // Address Mapping
  // ===========================================================================
  // Custom address rule type with end_addr 1 bit wider to handle overflow
  typedef struct packed {
    int unsigned idx;
    logic [31:0] start_addr;
    logic [32:0] end_addr;
  } addr_rule_t;

  // APB address rule type for AXI-Lite to APB bridges (decode width = xbar AXI-Lite width)
  typedef struct packed {
    int unsigned idx;
    logic [31:0] start_addr;
    logic [32:0] end_addr;
  } apb_addr_rule_t;

  // ===========================================================================
  // Address Range Constants (Named)
  // ===========================================================================
  // Output: cpu_tcm
  localparam logic [31:0] CPU_TCM_ICCM_BASE = 32'hc0000000;
  localparam logic [31:0] CPU_TCM_ICCM_SIZE = 32'h40000;
  localparam logic [32:0] CPU_TCM_ICCM_END = 33'hc0040000;
  localparam logic [31:0] CPU_TCM_DCCM_BASE = 32'hc0040000;
  localparam logic [31:0] CPU_TCM_DCCM_SIZE = 32'h20000;
  localparam logic [32:0] CPU_TCM_DCCM_END = 33'hc0060000;

  // Output: sram
  localparam logic [31:0] SRAM_MAIN_BASE = 32'h10000000;
  localparam logic [31:0] SRAM_MAIN_SIZE = 32'h40000;
  localparam logic [32:0] SRAM_MAIN_END = 33'h10040000;

  // Output: dma_csr
  localparam logic [31:0] DMA_CSR_MAIN_BASE =
      32'(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_BASE_ADDR);
  localparam logic [31:0] DMA_CSR_MAIN_SIZE = 32'(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_SIZE);
  localparam logic [32:0] DMA_CSR_MAIN_END  =
      33'(sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_BASE_ADDR +
          sep_top_addrmap_pkg::SEP_TOP_SECURE_DMA_SIZE);

  // Output: sep_wdt
  localparam logic [31:0] SEP_WDT_MAIN_BASE = 32'(sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_BASE_ADDR);
  localparam logic [31:0] SEP_WDT_MAIN_SIZE = 32'(sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_SIZE);
  localparam logic [32:0] SEP_WDT_MAIN_END  =
      33'(sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_BASE_ADDR +
          sep_top_addrmap_pkg::SEP_TOP_WDT_TIMER_SIZE);

  // Output: sep_reset_ctrl
  localparam logic [31:0] SEP_RESET_CTRL_MAIN_BASE = 32'h10803000;
  localparam logic [31:0] SEP_RESET_CTRL_MAIN_SIZE = 32'h8;
  localparam logic [32:0] SEP_RESET_CTRL_MAIN_END = 33'h10803008;

  // Output: sep_crypto
  localparam logic [31:0] SEP_CRYPTO_MAIN_BASE = 32'h10900000;
  localparam logic [31:0] SEP_CRYPTO_MAIN_SIZE = 32'h50000;
  localparam logic [32:0] SEP_CRYPTO_MAIN_END = 33'h10950000;

  // Output: sep_system_peripherals
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_SCRATCH_REGION_BASE = 32'h10802000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_SCRATCH_REGION_SIZE = 32'h100;
  localparam logic [32:0] SEP_SYSTEM_PERIPHERALS_SCRATCH_REGION_END = 33'h10802100;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_CSR_REGION_BASE = 32'h10a00000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_CSR_REGION_SIZE = 32'h60000;
  localparam logic [32:0] SEP_SYSTEM_PERIPHERALS_CSR_REGION_END = 33'h10a60000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_REMAP_REGION_BASE = 32'h11000000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_REMAP_REGION_SIZE = 32'h1000000;
  localparam logic [32:0] SEP_SYSTEM_PERIPHERALS_REMAP_REGION_END = 33'h12000000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_CHIPLET_BASE = 32'h0;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_CHIPLET_SIZE = 32'h10000000;
  localparam logic [32:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_CHIPLET_END = 33'h10000000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_SMU_BASE = 32'h40000000;
  localparam logic [31:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_SMU_SIZE = 32'h80000000;
  localparam logic [32:0] SEP_SYSTEM_PERIPHERALS_EXTERNAL_SMU_END = 33'hc0000000;

  // Output: sep_io
  localparam logic [31:0] SEP_IO_MAIN_BASE = 32'h10b00000;
  localparam logic [31:0] SEP_IO_MAIN_SIZE = 32'hfffff;
  localparam logic [32:0] SEP_IO_MAIN_END = 33'h10bfffff;

  // Output: entropy_fifo
  localparam logic [31:0] ENTROPY_FIFO_MAIN_BASE = 32'h10950000;
  localparam logic [31:0] ENTROPY_FIFO_MAIN_SIZE = 32'h10000;
  localparam logic [32:0] ENTROPY_FIFO_MAIN_END = 33'h10960000;

  // Output: sep_external
  localparam logic [31:0] SEP_EXTERNAL_MAIN_BASE = 32'h20000000;
  localparam logic [31:0] SEP_EXTERNAL_MAIN_SIZE = 32'h20000000;
  localparam logic [32:0] SEP_EXTERNAL_MAIN_END = 33'h40000000;

  // ===========================================================================
  // Crossbar Configuration
  // ===========================================================================
  localparam axi_pkg::xbar_cfg_t XbarCfg = '{
      NoSlvPorts: NumInputs,
      NoMstPorts: NumOutputs,
      MaxMstTrans: 4,
      MaxSlvTrans: 4,
      FallThrough: 1'b0,
      LatencyMode: axi_pkg::CUT_ALL_PORTS,
      PipelineStages: 1,
      AxiIdWidthSlvPorts: MaxInputIdW,
      AxiIdUsedSlvPorts: MaxInputIdW,
      UniqueIds: 1'b0,
      AxiAddrWidth: XbarAddrWidth,
      AxiDataWidth: XbarDataWidth,
      NoAddrRules: NumAddrRules,
      SelHashIds: 1'b0
  };

  // ===========================================================================
  // Connectivity Matrix
  // ===========================================================================
  localparam bit [NumInputs-1:0][NumOutputs-1:0] Connectivity = '{
      0: 10'b0000000010,  // ifu_sram
      1: 10'b1111111110,  // lsu
      2: 10'b1111111110,  // dbg
      3: 10'b1011111011,  // dma
      4: 10'b1110101110  // ext
  };

endpackage : sep_local_axi_xbar_pkg
