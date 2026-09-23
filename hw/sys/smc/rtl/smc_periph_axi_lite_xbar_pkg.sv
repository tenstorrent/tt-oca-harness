// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// SMC peripheral AXI-Lite crossbar types and address constants.
//
// Hand-maintained: the fabric_gen source configs for this crossbar were not
// carried into the open tree, so it cannot be regenerated. Rules that
// previously spanned the full spec aperture now derive their end addresses from
// smc_top_addrmap_pkg so the RDL remains authoritative for those extents.
// Rules left as literal apertures: uart, dtp_csr, i3c (RDL SIZE equals the
// window), efuse_shim (parametric on EFUSE_SHIM_SIZE), external (non-RDL
// vendor region).

`include "axi/typedef.svh"

package smc_periph_axi_lite_xbar_pkg;

  import axi_pkg::*;

  // ===========================================================================
  // Fabric Parameters
  // ===========================================================================
  localparam int unsigned NumInputs     = 1;
  localparam int unsigned NumOutputs    = 12;
  localparam int unsigned NumAddrRules  = 14;

  // ===========================================================================
  // Protocol Type Definitions
  // ===========================================================================

  // Protocol: axi_lite32 (AXI4_LITE)
  typedef logic [31:0] axi_lite32_addr_t;
  typedef logic [31:0] axi_lite32_data_t;
  typedef logic [3:0] axi_lite32_strb_t;

  `AXI_LITE_TYPEDEF_AW_CHAN_T(axi_lite32_aw_chan_t, axi_lite32_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(axi_lite32_w_chan_t, axi_lite32_data_t, axi_lite32_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(axi_lite32_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(axi_lite32_ar_chan_t, axi_lite32_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(axi_lite32_r_chan_t, axi_lite32_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(axi_lite32_req_t, axi_lite32_aw_chan_t, axi_lite32_w_chan_t, axi_lite32_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(axi_lite32_resp_t, axi_lite32_b_chan_t, axi_lite32_r_chan_t)
  // ===========================================================================
  // Crossbar Internal Types
  // ===========================================================================
  localparam int unsigned XbarDataWidth = 32;
  localparam int unsigned XbarStrbWidth = 4;
  localparam int unsigned XbarAddrWidth = 32;
  localparam int unsigned XbarUserWidth = 1;

  typedef logic [XbarAddrWidth-1:0] xbar_addr_t;
  typedef logic [XbarDataWidth-1:0] xbar_data_t;
  typedef logic [XbarStrbWidth-1:0] xbar_strb_t;

  // Crossbar slave port (input) types - AXI-Lite (no ID/user signals)
  `AXI_LITE_TYPEDEF_AW_CHAN_T(xbar_slv_aw_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_W_CHAN_T(xbar_slv_w_chan_t, xbar_data_t, xbar_strb_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(xbar_slv_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(xbar_slv_ar_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(xbar_slv_r_chan_t, xbar_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(xbar_slv_req_t, xbar_slv_aw_chan_t, xbar_slv_w_chan_t, xbar_slv_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(xbar_slv_resp_t, xbar_slv_b_chan_t, xbar_slv_r_chan_t)

  // Crossbar master port (output) types - AXI-Lite (same as slave, no ID expansion)
  `AXI_LITE_TYPEDEF_AW_CHAN_T(xbar_mst_aw_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_B_CHAN_T(xbar_mst_b_chan_t)
  `AXI_LITE_TYPEDEF_AR_CHAN_T(xbar_mst_ar_chan_t, xbar_addr_t)
  `AXI_LITE_TYPEDEF_R_CHAN_T(xbar_mst_r_chan_t, xbar_data_t)
  `AXI_LITE_TYPEDEF_REQ_T(xbar_mst_req_t, xbar_mst_aw_chan_t, xbar_slv_w_chan_t, xbar_mst_ar_chan_t)
  `AXI_LITE_TYPEDEF_RESP_T(xbar_mst_resp_t, xbar_mst_b_chan_t, xbar_mst_r_chan_t)

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
  // Output: reset_unit — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_RESET_UNIT_SIZE (0xCC)
  localparam logic [31:0] RESET_UNIT_RESET_UNIT_BASE = 32'hc0002000;
  localparam logic [31:0] RESET_UNIT_RESET_UNIT_SIZE = 32'hcc;
  localparam logic [32:0] RESET_UNIT_RESET_UNIT_END  = 33'hc00020cc;

  // Output: misc — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_MISC_WRAP_SIZE (0x20C)
  localparam logic [31:0] MISC_MISC_BASE = 32'hc0002800;
  localparam logic [31:0] MISC_MISC_SIZE = 32'h20c;
  localparam logic [32:0] MISC_MISC_END  = 33'hc0002a0c;

  // Output: gpio — narrowed to smc_top_addrmap_pkg::SMC_TOP_GPIO_INTF_TOTAL_SIZE (0x410)
  localparam logic [31:0] GPIO_GPIO_BASE = 32'hc0003000;
  localparam logic [31:0] GPIO_GPIO_SIZE = 32'h410;
  localparam logic [32:0] GPIO_GPIO_END  = 33'hc0003410;

  // Output: apb2avsbus — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_AVSBUS_CONTROLLER_SIZE (0x5C)
  localparam logic [31:0] APB2AVSBUS_APB2AVSBUS_BASE = 32'hc0004000;
  localparam logic [31:0] APB2AVSBUS_APB2AVSBUS_SIZE = 32'h5c;
  localparam logic [32:0] APB2AVSBUS_APB2AVSBUS_END  = 33'hc000405c;

  // Output: i2c — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_I2C_WRAP_SIZE (0xE0C)
  localparam logic [31:0] I2C_I2C_BASE = 32'hc0005000;
  localparam logic [31:0] I2C_I2C_SIZE = 32'he0c;
  localparam logic [32:0] I2C_I2C_END  = 33'hc0005e0c;

  // Output: uart — equal to RDL SIZE (0x1000); literal window retained
  localparam logic [31:0] UART_UART_BASE = 32'hc0006000;
  localparam logic [31:0] UART_UART_SIZE = 32'h1000;
  localparam logic [32:0] UART_UART_END  = 33'hc0007000;

  // Output: efuse — split into two rules (SMC_EFUSE_MAP + EFUSE_INTERFACE_CTRL)
  localparam logic [31:0] EFUSE_EFUSE_MAP_BASE = 32'hc0007000;
  localparam logic [31:0] EFUSE_EFUSE_MAP_SIZE = 32'h400;
  localparam logic [32:0] EFUSE_EFUSE_MAP_END  = 33'hc0007400;

  localparam logic [31:0] EFUSE_EFUSE_INTERFACE_CTRL_BASE = 32'hc0008000;
  localparam logic [31:0] EFUSE_EFUSE_INTERFACE_CTRL_SIZE = 32'h1c;
  localparam logic [32:0] EFUSE_EFUSE_INTERFACE_CTRL_END  = 33'hc000801c;

  // Output: telemetry — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_SIZE (0x300)
  localparam logic [31:0] TELEMETRY_TELEMETRY_BASE = 32'hc0009000;
  localparam logic [31:0] TELEMETRY_TELEMETRY_SIZE = 32'h300;
  localparam logic [32:0] TELEMETRY_TELEMETRY_END  = 33'hc0009300;

  // Output: system_timer_octs — narrowed to smc_top_addrmap_pkg::SMC_TOP_SMC_SYSTEM_TIMER_OCTS_SIZE (0x24)
  localparam logic [31:0] SYSTEM_TIMER_OCTS_SYSTEM_TIMER_OCTS_BASE = 32'hc000a000;
  localparam logic [31:0] SYSTEM_TIMER_OCTS_SYSTEM_TIMER_OCTS_SIZE = 32'h24;
  localparam logic [32:0] SYSTEM_TIMER_OCTS_SYSTEM_TIMER_OCTS_END  = 33'hc000a024;

  // Output: dtp_csr — equal to RDL SIZE (0x800); literal window retained
  localparam logic [31:0] DTP_CSR_DTP_CSR_BASE = 32'hc000b000;
  localparam logic [31:0] DTP_CSR_DTP_CSR_SIZE = 32'h800;
  localparam logic [32:0] DTP_CSR_DTP_CSR_END  = 33'hc000b800;

  // Output: i3c — equal to RDL TOTAL_SIZE (0x6000); literal window retained
  localparam logic [31:0] I3C_I3C_BASE = 32'hc003a000;
  localparam logic [31:0] I3C_I3C_SIZE = 32'h6000;
  localparam logic [32:0] I3C_I3C_END  = 33'hc0040000;

  // Output: external — non-RDL vendor region; literal window retained
  localparam logic [31:0] EXTERNAL_EXTERNAL_BASE = 32'hc0400000;
  localparam logic [31:0] EXTERNAL_EXTERNAL_SIZE = 32'h400000;
  localparam logic [32:0] EXTERNAL_EXTERNAL_END  = 33'hc0800000;

  // ===========================================================================
  // Crossbar Configuration
  // ===========================================================================
  localparam axi_pkg::xbar_cfg_t XbarCfg = '{
    NoSlvPorts:         NumInputs,
    NoMstPorts:         NumOutputs,
    MaxMstTrans:        4,
    MaxSlvTrans:        4,
    FallThrough:        1'b0,
    LatencyMode:        axi_pkg::CUT_ALL_PORTS,
    PipelineStages:     1,
    AxiIdWidthSlvPorts: 32'd1,
    AxiIdUsedSlvPorts:  32'd1,
    UniqueIds:          1'b0,
    AxiAddrWidth:       XbarAddrWidth,
    AxiDataWidth:       XbarDataWidth,
    NoAddrRules:        NumAddrRules,
    SelHashIds:         1'b0
  };

  // ===========================================================================
  // Connectivity Matrix
  // ===========================================================================
  localparam bit [NumInputs-1:0][NumOutputs-1:0] Connectivity = '{
    0: 12'b111111111111  // periph_in
  };

endpackage : smc_periph_axi_lite_xbar_pkg
