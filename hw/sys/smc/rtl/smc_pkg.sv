// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Share SMC types, address-map helpers, and fabric typedefs.
//
// Packages AXI and AXI-Lite request/response types used across the SMC hierarchy.
// Holds mailbox counts, GPIO wrap counts, and other constants the top-level and fabrics
// share.

`ifndef SMC_PACKAGE_DEFINED
`define SMC_PACKAGE_DEFINED

package smc_pkg;

  // Include register header file

  // Peripheral parameters
  localparam int unsigned NUM_BONDED_GPIO = 61;
  localparam int unsigned NUM_UNBONDED_GPIO = 4;
  localparam int unsigned NUM_GPIO_WRAPS = NUM_BONDED_GPIO + NUM_UNBONDED_GPIO;

  // DFD parameters
  localparam int unsigned XTRIGGER_WIDTH = 2;
  typedef logic [XTRIGGER_WIDTH-1:0] xtrigger_t;
  localparam int unsigned NUM_MAX_EXTERNAL_XTRIG_AGENTS = 6;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  //////////////////////////////
  // AXI Parameters - General //
  //////////////////////////////

  // Full AXI
  localparam int unsigned AXI_ADDR_WIDTH = 56;  // General AXI address width.
  localparam int unsigned SMC_LOCAL_ADDR_WIDTH = 32;  // Within SMC.

  localparam int unsigned AXI_DATA_WIDTH = 64;
  localparam int unsigned AXI_STRB_WIDTH = AXI_DATA_WIDTH / 8;
  localparam int unsigned AXI_USER_WIDTH = 12;

  localparam int unsigned AXI_32_DATA_WIDTH = 32;
  localparam int unsigned AXI_32_STRB_WIDTH = AXI_32_DATA_WIDTH / 8;

  // Input ID Width Parameters
  localparam int unsigned SYS_IN_ID_WIDTH = 6;
  localparam int unsigned JTAG_ID_WIDTH = 2;
  localparam int unsigned SEP_IN_ID_WIDTH = 6;

  // Output ID Width Parameters
  localparam int unsigned SYS_OUT_ID_WIDTH = 8;

  // Fabric ID Width Parameters
  localparam int unsigned SMC_INPUT_FABRIC_SLAVE_ID_WIDTH = 4;  // Into Input Fabric.
  localparam int unsigned SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH = 6; // Input to Local Fabric/Output Fabric.
  localparam int unsigned SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH  = 8; // Out of Local Fabric to CPU cluster + Peripherals.
  localparam int unsigned SMC_OUTPUT_FABRIC_MASTER_ID_WIDTH = 8;  // Out of Output Fabric.

  // MMIO AXI interface (output from DigitalTop)
  // - ID width: 3 bits, Address: 56 bits, Data: 64 bits
  localparam int unsigned SMC_CPU_MMIO_AXI_ID_WIDTH = 3;

  // L2 Frontend Bus AXI interface (input to DigitalTop)
  // - ID width: 8 bits, Address: 56 bits, Data: 64 bits
  localparam int unsigned SMC_CPU_L2_FRONTEND_AXI_ID_WIDTH = 8;

  // AXI-Lite
  localparam int unsigned AXI_LITE_64_DATA_WIDTH = 64;
  localparam int unsigned AXI_LITE_32_DATA_WIDTH = 32;

  //////////////////
  // AXI Typedefs //
  //////////////////

  typedef logic [AXI_ADDR_WIDTH-1:0] smc_axi_addr_t;
  typedef logic [SMC_LOCAL_ADDR_WIDTH-1:0] smc_axi_local_addr_t;

  typedef logic [AXI_DATA_WIDTH-1:0] smc_axi_data_t;
  typedef logic [AXI_STRB_WIDTH-1:0] smc_axi_strb_t;
  typedef logic [AXI_USER_WIDTH-1:0] smc_axi_user_t;

  typedef logic [AXI_32_DATA_WIDTH-1:0] smc_axi_32_data_t;
  typedef logic [AXI_32_STRB_WIDTH-1:0] smc_axi_32_strb_t;

  // SMC System Inputs
  typedef logic [SYS_IN_ID_WIDTH-1:0] smc_sys_in_id_t;
  typedef logic [JTAG_ID_WIDTH-1:0] smc_jtag_id_t;
  typedef logic [SEP_IN_ID_WIDTH-1:0] smc_sep_in_id_t;

  // Types follow naming convention: name_<addr_width>_<data_width>_<id_width>_<user_width>_axi
  `AXI_TYPEDEF_ALL(smc_sys_in_56_64_6_12_axi, smc_axi_addr_t, smc_sys_in_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_jtag_56_64_2_12_axi, smc_axi_addr_t, smc_jtag_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_sep_in_56_64_6_12_axi, smc_axi_addr_t, smc_sep_in_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // SMC System Outputs
  typedef logic [SYS_OUT_ID_WIDTH-1:0] smc_sys_out_id_t;
  `AXI_TYPEDEF_ALL(smc_sys_out_56_64_8_12_axi, smc_axi_addr_t, smc_sys_out_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // Input Fabric Inputs
  typedef logic [SMC_INPUT_FABRIC_SLAVE_ID_WIDTH-1:0] smc_input_fabric_slave_id_t;
  `AXI_TYPEDEF_ALL(smc_input_fabric_56_64_4_12_axi, smc_axi_addr_t, smc_input_fabric_slave_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // Input to Local Fabric/Output Fabric
  typedef logic [SMC_LOCAL_OUTPUT_FABRIC_SLAVE_ID_WIDTH-1:0] smc_local_output_fabric_slave_id_t;
  `AXI_TYPEDEF_ALL(smc_56_64_6_12_axi, smc_axi_addr_t, smc_local_output_fabric_slave_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_local_32_64_6_12_axi, smc_axi_local_addr_t,
                   smc_local_output_fabric_slave_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // Local Fabric to peripherals
  // one 64bit and one 32bit data version for internal and external peripherals
  typedef logic [SMC_LOCAL_FABRIC_XBAR_MASTER_ID_WIDTH-1:0] smc_local_fabric_xbar_master_id_t;
  `AXI_TYPEDEF_ALL(smc_local_32_64_8_12_axi, smc_axi_local_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_local_32_32_8_12_axi, smc_axi_local_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_32_data_t, smc_axi_32_strb_t,
                   smc_axi_user_t)

  // Output Fabric Output
  typedef logic [SMC_OUTPUT_FABRIC_MASTER_ID_WIDTH-1:0] smc_output_fabric_master_id_t;
  `AXI_TYPEDEF_ALL(smc_output_56_64_8_12_axi, smc_axi_addr_t, smc_output_fabric_master_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // MMIO AXI types
  typedef logic [SMC_CPU_MMIO_AXI_ID_WIDTH-1:0] smc_cpu_mmio_axi_id_t;
  `AXI_TYPEDEF_ALL(smc_cpu_mmio_axi, smc_axi_addr_t, smc_cpu_mmio_axi_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // L2 Frontend Bus AXI types
  typedef logic [SMC_CPU_L2_FRONTEND_AXI_ID_WIDTH-1:0] smc_cpu_l2_frontend_axi_id_t;
  `AXI_TYPEDEF_ALL(smc_cpu_l2_frontend_axi, smc_axi_local_addr_t, smc_cpu_l2_frontend_axi_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // AXI-Lite Typedefs
  typedef logic [AXI_ADDR_WIDTH-1:0] smc_axi_lite_56_addr_t;
  typedef logic [SMC_LOCAL_ADDR_WIDTH-1:0] smc_axi_lite_32_addr_t;
  typedef logic [AXI_LITE_64_DATA_WIDTH-1:0] smc_axi_lite_64_data_t;
  typedef logic [AXI_LITE_32_DATA_WIDTH-1:0] smc_axi_lite_32_data_t;
  typedef logic [AXI_LITE_64_DATA_WIDTH/8-1:0] smc_axi_lite_64_strb_t;
  typedef logic [AXI_LITE_32_DATA_WIDTH/8-1:0] smc_axi_lite_32_strb_t;
  // 56_64_0_0
  `AXI_LITE_TYPEDEF_ALL(smc_axil_56_64, smc_axi_lite_56_addr_t, smc_axi_lite_64_data_t,
                        smc_axi_lite_64_strb_t)
  // 32_64_0_0
  `AXI_LITE_TYPEDEF_ALL(smc_axil_32_64, smc_axi_lite_32_addr_t, smc_axi_lite_64_data_t,
                        smc_axi_lite_64_strb_t)
  // 32_32_0_0
  `AXI_LITE_TYPEDEF_ALL(smc_axil_32_32, smc_axi_lite_32_addr_t, smc_axi_lite_32_data_t,
                        smc_axi_lite_32_strb_t)

  ////////////////////////////
  // APB Parameters + Types //
  ////////////////////////////

  localparam int unsigned NUM_APB_TARGETS = 1;

  localparam int unsigned CPU_DEBUG_APB_ADDR_WIDTH = 32;
  localparam int unsigned CPU_DEBUG_APB_DATA_WIDTH = 32;
  localparam int unsigned CPU_DEBUG_APB_STRB_WIDTH = CPU_DEBUG_APB_DATA_WIDTH / 8;

  typedef logic [CPU_DEBUG_APB_ADDR_WIDTH-1:0] cpu_debug_apb_addr_t;
  typedef logic [CPU_DEBUG_APB_DATA_WIDTH-1:0] cpu_debug_apb_data_t;
  typedef logic [CPU_DEBUG_APB_STRB_WIDTH-1:0] cpu_debug_apb_strb_t;

  `APB_TYPEDEF_ALL(cpu_debug_apb, cpu_debug_apb_addr_t, cpu_debug_apb_data_t, cpu_debug_apb_strb_t)

  localparam int unsigned SMC_DFD_APB_ADDR_WIDTH = 32;
  localparam int unsigned SMC_DFD_APB_DATA_WIDTH = 32;
  localparam int unsigned SMC_DFD_APB_STRB_WIDTH = SMC_DFD_APB_DATA_WIDTH / 8;

  typedef logic [SMC_DFD_APB_ADDR_WIDTH-1:0] smc_dfd_apb_addr_t;
  typedef logic [SMC_DFD_APB_DATA_WIDTH-1:0] smc_dfd_apb_data_t;
  typedef logic [SMC_DFD_APB_STRB_WIDTH-1:0] smc_dfd_apb_strb_t;

  `APB_TYPEDEF_ALL(smc_dfd_apb, smc_dfd_apb_addr_t, smc_dfd_apb_data_t, smc_dfd_apb_strb_t)

  ////////////////////////////////////////
  // Transaction and Timeout Parameters //
  ////////////////////////////////////////

  // PER AXI ID BUCKET, for axi_demux.MaxTrans
  localparam int unsigned FABRIC_MAX_TRANS = 32;
  // For axi_demux.AxiLookBits
  localparam int unsigned FABRIC_ID_LOOKUP_BITS = 3;
  // ALL IDs, PER DIRECTION, for passive monitors (prim_axi_snoop via axi_cg_snoop, axi_hang_detector)
  localparam int unsigned FABRIC_ID_BUCKETS = 2 ** FABRIC_ID_LOOKUP_BITS;
  localparam int unsigned FABRIC_OUTSTANDING_TX = FABRIC_ID_BUCKETS * FABRIC_MAX_TRANS;
  // ALL IDs, to be used with axi_err_slv
  localparam int unsigned ERR_SLV_MAX_TRANS = 32;

  // Unique-ID table depth for axi_id_remap (prim_axi_id_converter)
  localparam int unsigned MAX_INFLIGHT_IDS = 4;
  localparam int unsigned TIMEOUT_COUNT_W = 48;  // 48 bits is enough for 78 hours at refclk.

  ////////////////////////////////////
  // Alias Remap Parameters + Types //
  ////////////////////////////////////

  localparam int unsigned INPUT_FABRIC_NUM_REG_MAPS = 3;
  localparam int unsigned NUM_ALIAS_REMAP_INPUTS = 4;

  localparam int unsigned NUM_CHUNKS_ALIAS_REMAP_CARRY_SELECT_ADDER = 5;  // 56-12+1 = 45, 45/5 = 9.

  typedef struct packed {
    logic [2:0] aw_remap_hit_debug;
    logic [2:0] ar_remap_hit_debug;
  } remap_debug_t;

  typedef struct packed {
    logic [AXI_ADDR_WIDTH-1:0] region_start;
    logic [AXI_ADDR_WIDTH-1:0] region_end;
    logic [AXI_ADDR_WIDTH-1:0] offset;
    logic cacheable;
    logic region_valid;
  } remap_region_t;

  typedef struct packed {
    smc_input_fabric_56_64_4_12_axi_req_t mmio;
    smc_input_fabric_56_64_4_12_axi_req_t jtag;
    smc_input_fabric_56_64_4_12_axi_req_t log;
    smc_input_fabric_56_64_4_12_axi_req_t data_accel;
  } input_fabric_mux_axi_req_t;

  typedef struct packed {
    smc_input_fabric_56_64_4_12_axi_resp_t mmio;
    smc_input_fabric_56_64_4_12_axi_resp_t jtag;
    smc_input_fabric_56_64_4_12_axi_resp_t log;
    smc_input_fabric_56_64_4_12_axi_resp_t data_accel;
  } input_fabric_mux_axi_resp_t;

  // Input fabric demux output structs (56-bit address width for both paths)
  // local_fabric path: gets address-converted to 32-bit downstream
  // output_fabric path: stays 56-bit to output fabric
  typedef struct packed {
    smc_56_64_6_12_axi_req_t local_fabric;
    smc_56_64_6_12_axi_req_t output_fabric;
  } input_fabric_demux_axi_req_t;

  typedef struct packed {
    smc_56_64_6_12_axi_resp_t local_fabric;
    smc_56_64_6_12_axi_resp_t output_fabric;
  } input_fabric_demux_axi_resp_t;

  //////////////////////////////////////
  // Output Fabric Parameters + Types //
  //////////////////////////////////////

  typedef struct packed {
    smc_56_64_6_12_axi_req_t xvisor;
    smc_56_64_6_12_axi_req_t mmode;
    smc_56_64_6_12_axi_req_t filter;
  } output_fabric_axi_struct_req_t;

  typedef struct packed {
    smc_56_64_6_12_axi_resp_t xvisor;
    smc_56_64_6_12_axi_resp_t mmode;
    smc_56_64_6_12_axi_resp_t filter;
  } output_fabric_axi_struct_resp_t;


  /////////////////////////////////////
  // Output Remap Parameters + Types //
  /////////////////////////////////////

  localparam int unsigned OUTPUT_REMAP_IDX_START = 20;

  localparam int unsigned NUM_MMODE_OUTPUT_REMAP_REGIONS = 8;
  localparam int unsigned MMODE_REMAP_SEL_W = $clog2(NUM_MMODE_OUTPUT_REMAP_REGIONS);
  localparam int unsigned NUM_XVISOR_OUTPUT_REMAP_REGIONS = 8;
  localparam int unsigned XVISOR_REMAP_SEL_W = $clog2(NUM_XVISOR_OUTPUT_REMAP_REGIONS);
  localparam int unsigned NUM_ALIAS_REMAP_REGIONS = 8;
  localparam int unsigned ALIAS_REMAP_SEL_W = $clog2(NUM_ALIAS_REMAP_REGIONS);
  localparam int unsigned ALIAS_REMAP_IDX_START = 12;
  localparam int unsigned ALIAS_REMAP_OFFSET_WIDTH = AXI_ADDR_WIDTH - ALIAS_REMAP_IDX_START;

  localparam int unsigned NUM_OUTPUT_REMAPS = 3;

  localparam longint unsigned MMODE_REMAP_BASE_ADDR = 64'h100_0000;
  localparam longint unsigned XVISOR_REMAP_BASE_ADDR = 64'h180_0000;

  // External Interface Parameters
  localparam int unsigned NUM_EXT_INTERFACES = 12;
  localparam int unsigned EXT_REG_ADDR_WIDTH = 32;
  localparam int unsigned EXT_REG_DATA_WIDTH = 32;
  localparam int unsigned EXT_REG_STRB_WIDTH = EXT_REG_DATA_WIDTH / 8;
  typedef logic [EXT_REG_ADDR_WIDTH-1:0] ext_reg_addr_t;
  typedef logic [EXT_REG_DATA_WIDTH-1:0] ext_reg_data_t;
  typedef logic [EXT_REG_STRB_WIDTH-1:0] ext_reg_strb_t;

  // Source ID Parameters
  localparam smc_axi_user_t OTHERS_SRC_ID = smc_axi_user_t'(0);
  localparam smc_axi_user_t SMC_SRC_ID = smc_axi_user_t'(3);
  localparam smc_axi_user_t MMODE_SRC_ID = smc_axi_user_t'('hC);
  localparam smc_axi_user_t SEP_SRC_ID = smc_axi_user_t'('hF);

  // Address Remap Parameters
  // The remap starts are offsets into the SMC register window, since the fabric adds them to a
  // runtime window base. SMC_TOP_BASE_ADDR is the addrmap root (0), not the window base, so the
  // window base is taken from the lowest-addressed block in the window instead.
  localparam smc_axi_addr_t REG_WINDOW_BASE      = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR);
  localparam smc_axi_addr_t MMODE_REMAP_START    = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_BASE_ADDR) - REG_WINDOW_BASE;
  localparam smc_axi_addr_t MMODE_REMAP_SIZE     = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_SIZE);
  localparam smc_axi_addr_t XVISOR_REMAP_START   = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_BASE_ADDR) - REG_WINDOW_BASE;
  localparam smc_axi_addr_t XVISOR_REMAP_SIZE    = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_SIZE);

  // Filter Parameters
  localparam int unsigned NumOutboundFilters = 16;
  localparam int unsigned NumInboundFilters = 16;

  /////////////////////
  // Misc Parameters //
  /////////////////////

  localparam int unsigned LC_STATE_WIDTH = 4;
  localparam int unsigned NUM_MAILBOXES = 32;
  localparam int unsigned MAILBOX_DEPTH = 2;

  /////////////////////////////////////
  // Data Accelerator Parameters     //
  /////////////////////////////////////

  localparam int unsigned F2M_FIFO_DEPTH = 4;
  localparam int unsigned M2B_FIFO_DEPTH = 0;

  typedef enum logic {
    DMA = 0,
    ZEROER = 1
  } data_accelerator_type_t;

  // DMA backend internal ID width (for axi_mux inside DMA backend)
  localparam int unsigned DMA_BACKEND_MST_ID_W = SMC_INPUT_FABRIC_SLAVE_ID_WIDTH - 2;  // 2.

  // DMA control interface (9-bit addr, reuses 64-bit data / 8-bit ID / 12-bit user)
  localparam int unsigned DMA_CTRL_ADDR_W = 9;
  typedef logic [DMA_CTRL_ADDR_W-1:0] smc_dma_ctrl_addr_t;
  `AXI_TYPEDEF_ALL(smc_dma_ctrl_9_64_8_12_axi, smc_dma_ctrl_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // Zeroer control interface (5-bit addr matches zeroer_ctrl_reg_pkg::ZEROER_CTRL_REG_MIN_ADDR_WIDTH)
  localparam int unsigned ZEROER_CTRL_ADDR_W = 5;
  typedef logic [ZEROER_CTRL_ADDR_W-1:0] smc_zeroer_ctrl_addr_t;
  `AXI_LITE_TYPEDEF_ALL(smc_zeroer_ctrl_axil_5_64, smc_zeroer_ctrl_addr_t, smc_axi_data_t,
                        smc_axi_strb_t)
  `AXI_TYPEDEF_ALL(smc_zeroer_ctrl_5_64_8_12_axi, smc_zeroer_ctrl_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // AXI data size for byte-lane calculations
  localparam int unsigned AXI_DATA_SIZE = $clog2(AXI_STRB_WIDTH);  // 3.

  // eFuse APB (AXI-Lite already exists as smc_axil_32_32)
  `APB_TYPEDEF_ALL(smc_efuse_apb, smc_axi_lite_32_addr_t, smc_axi_lite_32_data_t,
                   smc_axi_lite_32_strb_t)

  /////////////////////////////////////////
  // Address Width Adjustment Parameters //
  /////////////////////////////////////////

  // Macro for AXI-Lite address width adjustment assignments
  // Keep the macro header on one physical line for synthesis elaboration.
  // verilog_format: off
  `define AXI_LITE_ASSIGN_ADDR_WIDTH_ADJ_CASTING(dst_req, dst_resp, src_req, src_resp, dst_addr_type) \
        assign dst_req.aw_valid = src_req.aw_valid; \
        assign dst_req.aw.addr  = dst_addr_type'(src_req.aw.addr); \
        assign dst_req.aw.prot  = src_req.aw.prot; \
        assign dst_req.w_valid  = src_req.w_valid; \
        assign dst_req.w.data   = src_req.w.data; \
        assign dst_req.w.strb   = src_req.w.strb; \
        assign dst_req.b_ready  = src_req.b_ready; \
        assign dst_req.ar_valid = src_req.ar_valid; \
        assign dst_req.ar.addr  = dst_addr_type'(src_req.ar.addr); \
        assign dst_req.ar.prot  = src_req.ar.prot; \
        assign dst_req.r_ready  = src_req.r_ready; \
        assign src_resp.aw_ready = dst_resp.aw_ready; \
        assign src_resp.w_ready  = dst_resp.w_ready; \
        assign src_resp.b_valid  = dst_resp.b_valid; \
        assign src_resp.b.resp   = dst_resp.b.resp; \
        assign src_resp.ar_ready = dst_resp.ar_ready; \
        assign src_resp.r_valid  = dst_resp.r_valid; \
        assign src_resp.r.data   = dst_resp.r.data; \
        assign src_resp.r.resp   = dst_resp.r.resp;
  // verilog_format: on

  // Macro for AXI Address width adjustment assignments
  `define AXI_ASSIGN_ADDR_WIDTH_ADJ_CASTING(dst_req, dst_resp, src_req, src_resp, dst_addr_type) \
        assign dst_req.aw_valid   = src_req.aw_valid; \
        assign dst_req.aw.id      = src_req.aw.id; \
        assign dst_req.aw.addr    = dst_addr_type'(src_req.aw.addr); \
        assign dst_req.aw.len     = src_req.aw.len; \
        assign dst_req.aw.size    = src_req.aw.size; \
        assign dst_req.aw.burst   = src_req.aw.burst; \
        assign dst_req.aw.lock    = src_req.aw.lock; \
        assign dst_req.aw.cache   = src_req.aw.cache; \
        assign dst_req.aw.prot    = src_req.aw.prot; \
        assign dst_req.aw.qos     = src_req.aw.qos; \
        assign dst_req.aw.region  = src_req.aw.region; \
        assign dst_req.aw.atop    = src_req.aw.atop; \
        assign dst_req.aw.user    = src_req.aw.user; \
        assign dst_req.w_valid    = src_req.w_valid; \
        assign dst_req.w.data     = src_req.w.data; \
        assign dst_req.w.strb     = src_req.w.strb; \
        assign dst_req.w.last     = src_req.w.last; \
        assign dst_req.w.user     = src_req.w.user; \
        assign dst_req.b_ready    = src_req.b_ready; \
        assign dst_req.ar_valid   = src_req.ar_valid; \
        assign dst_req.ar.id      = src_req.ar.id; \
        assign dst_req.ar.addr    = dst_addr_type'(src_req.ar.addr); \
        assign dst_req.ar.len     = src_req.ar.len; \
        assign dst_req.ar.size    = src_req.ar.size; \
        assign dst_req.ar.burst   = src_req.ar.burst; \
        assign dst_req.ar.lock    = src_req.ar.lock; \
        assign dst_req.ar.cache   = src_req.ar.cache; \
        assign dst_req.ar.prot    = src_req.ar.prot; \
        assign dst_req.ar.qos     = src_req.ar.qos; \
        assign dst_req.ar.region  = src_req.ar.region; \
        assign dst_req.ar.user    = src_req.ar.user; \
        assign dst_req.r_ready    = src_req.r_ready; \
        assign src_resp.aw_ready  = dst_resp.aw_ready; \
        assign src_resp.w_ready   = dst_resp.w_ready; \
        assign src_resp.b_valid   = dst_resp.b_valid; \
        assign src_resp.b.id      = dst_resp.b.id; \
        assign src_resp.b.resp    = dst_resp.b.resp; \
        assign src_resp.b.user    = dst_resp.b.user; \
        assign src_resp.ar_ready  = dst_resp.ar_ready; \
        assign src_resp.r_valid   = dst_resp.r_valid; \
        assign src_resp.r.id      = dst_resp.r.id; \
        assign src_resp.r.data    = dst_resp.r.data; \
        assign src_resp.r.resp    = dst_resp.r.resp; \
        assign src_resp.r.last    = dst_resp.r.last; \
        assign src_resp.r.user    = dst_resp.r.user; \

  /////////
  // CLA //
  /////////

  typedef struct packed {
    logic dfd_cg_en;
    logic dfd_force_clk_en;
    logic dfd_gpio_en;
    logic dfd_dtb_ew_en;
    logic dfd_dtb_ns_en;
    logic [15:0] xtrig_clk_halt_mask;
    logic [7:0]  debug_marker;
  } dfd_enable_t;


  // clock gating parameters
  localparam int unsigned CG_HYSTERESIS_W = 6;
  typedef logic [CG_HYSTERESIS_W-1:0] cg_hyster_t;

  // CPU Specific Parameters
  localparam int unsigned DBG_ADDR_W = 12;  // smc_4core_cpu_pkg.
  localparam int unsigned DBG_DATA_W = 32;  // smc_4core_cpu_pkg.
  localparam int unsigned DBG_STRB_W = DBG_DATA_W / 8;  // smc_4core_cpu_pkg.


  typedef struct packed {
    logic [31:0] ss_warm_reset_n_ovrd;
    logic [31:0] ss_cold_reset_n_ovrd;
    logic cold_reset_n_ovrd;
    logic cool_reset_n_ovrd;
    logic warm_reset_n_ovrd;
    logic fuse_reset_n_ovrd;
  } jtag_smc_reset_ctrl_ovrd_t;

  typedef struct packed {
    logic [31:0] ss_warm_reset_n_val;
    logic [31:0] ss_cold_reset_n_val;
    logic cold_reset_n_val;
    logic cool_reset_n_val;
    logic warm_reset_n_val;
    logic fuse_reset_n_val;
  } jtag_smc_reset_ctrl_val_t;

  typedef struct packed {
    jtag_smc_reset_ctrl_ovrd_t ovrd;
    jtag_smc_reset_ctrl_val_t val;
  } jtag_smc_reset_ctrl_t;

  function automatic logic is_pow2(input logic [31:0] value);
    return (value != '0) && ((value & (value - 32'd1)) == '0);
  endfunction

endpackage
`endif  // SMC_PACKAGE_DEFINED
