// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Define top-level SEP AXI, IRQ, and subsystem typedefs.
//
// Shared widths, mailbox counts, lockstep structs, and SMN AXI types used across SEP RTL.

package sep_pkg;

  `include "axi/typedef.svh"

  // sep_top_reg.svh is intentionally not included here due to an efuse
  // register naming collision: sep_efuse_map_reg.svh uses the same identifier
  // names with offset-based addresses, whereas sep_top_reg.svh uses
  // absolute addresses.

  parameter bit EN_EXTERNAL_MST = 1'b1;

  //////////
  // AXI4 main types (decoupled from old xbar config)
  //////////

  // Consolidated 32/64/3/1 (used by CPU masters, external inbound, sysperiph inbound)
  // No usecase in name since multiple logically different things share these params
  parameter int unsigned SEP_32_64_3_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_64_3_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_32_64_3_12_STRB_WIDTH = SEP_32_64_3_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_64_3_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_64_3_12_ID_WIDTH = 3;

  typedef logic [SEP_32_64_3_12_ADDR_WIDTH-1:0] sep_32_64_3_12_axi_addr_t;
  typedef logic [SEP_32_64_3_12_DATA_WIDTH-1:0] sep_32_64_3_12_axi_data_t;
  typedef logic [SEP_32_64_3_12_STRB_WIDTH-1:0] sep_32_64_3_12_axi_strb_t;
  typedef logic [SEP_32_64_3_12_USER_WIDTH-1:0] sep_32_64_3_12_axi_user_t;
  typedef logic [SEP_32_64_3_12_ID_WIDTH-1:0] sep_32_64_3_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_64_3_12_axi, sep_32_64_3_12_axi_addr_t, sep_32_64_3_12_axi_id_t,
                   sep_32_64_3_12_axi_data_t, sep_32_64_3_12_axi_strb_t, sep_32_64_3_12_axi_user_t)

  // 32/64/4/12 (boot ROM port: IFU+LSU muxed, ID widened by 1 bit)
  parameter int unsigned SEP_32_64_4_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_64_4_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_32_64_4_12_STRB_WIDTH = SEP_32_64_4_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_64_4_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_64_4_12_ID_WIDTH = 4;

  typedef logic [SEP_32_64_4_12_ADDR_WIDTH-1:0] sep_32_64_4_12_axi_addr_t;
  typedef logic [SEP_32_64_4_12_DATA_WIDTH-1:0] sep_32_64_4_12_axi_data_t;
  typedef logic [SEP_32_64_4_12_STRB_WIDTH-1:0] sep_32_64_4_12_axi_strb_t;
  typedef logic [SEP_32_64_4_12_USER_WIDTH-1:0] sep_32_64_4_12_axi_user_t;
  typedef logic [SEP_32_64_4_12_ID_WIDTH-1:0] sep_32_64_4_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_64_4_12_axi, sep_32_64_4_12_axi_addr_t, sep_32_64_4_12_axi_id_t,
                   sep_32_64_4_12_axi_data_t, sep_32_64_4_12_axi_strb_t, sep_32_64_4_12_axi_user_t)

  // Consolidated 32/64/6/1 (used by all local xbar slaves)
  // No usecase in name - just params
  parameter int unsigned SEP_32_64_6_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_64_6_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_32_64_6_12_STRB_WIDTH = SEP_32_64_6_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_64_6_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_64_6_12_ID_WIDTH = 6;

  typedef logic [SEP_32_64_6_12_ADDR_WIDTH-1:0] sep_32_64_6_12_axi_addr_t;
  typedef logic [SEP_32_64_6_12_DATA_WIDTH-1:0] sep_32_64_6_12_axi_data_t;
  typedef logic [SEP_32_64_6_12_STRB_WIDTH-1:0] sep_32_64_6_12_axi_strb_t;
  typedef logic [SEP_32_64_6_12_USER_WIDTH-1:0] sep_32_64_6_12_axi_user_t;
  typedef logic [SEP_32_64_6_12_ID_WIDTH-1:0] sep_32_64_6_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_64_6_12_axi, sep_32_64_6_12_axi_addr_t, sep_32_64_6_12_axi_id_t,
                   sep_32_64_6_12_axi_data_t, sep_32_64_6_12_axi_strb_t, sep_32_64_6_12_axi_user_t)

  // 56/64/6/1 (system peripherals internal)
  parameter int unsigned SEP_56_64_6_12_ADDR_WIDTH = 56;
  parameter int unsigned SEP_56_64_6_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_56_64_6_12_STRB_WIDTH = SEP_56_64_6_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_56_64_6_12_USER_WIDTH = 12;
  parameter int unsigned SEP_56_64_6_12_ID_WIDTH = 6;

  typedef logic [SEP_56_64_6_12_ADDR_WIDTH-1:0] sep_56_64_6_12_axi_addr_t;
  typedef logic [SEP_56_64_6_12_DATA_WIDTH-1:0] sep_56_64_6_12_axi_data_t;
  typedef logic [SEP_56_64_6_12_STRB_WIDTH-1:0] sep_56_64_6_12_axi_strb_t;
  typedef logic [SEP_56_64_6_12_USER_WIDTH-1:0] sep_56_64_6_12_axi_user_t;
  typedef logic [SEP_56_64_6_12_ID_WIDTH-1:0] sep_56_64_6_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_56_64_6_12_axi, sep_56_64_6_12_axi_addr_t, sep_56_64_6_12_axi_id_t,
                   sep_56_64_6_12_axi_data_t, sep_56_64_6_12_axi_strb_t, sep_56_64_6_12_axi_user_t)

  // 56/64/7/1 (system peripherals xbar slave)
  parameter int unsigned SEP_56_64_7_12_ADDR_WIDTH = 56;
  parameter int unsigned SEP_56_64_7_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_56_64_7_12_STRB_WIDTH = SEP_56_64_7_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_56_64_7_12_USER_WIDTH = 12;
  parameter int unsigned SEP_56_64_7_12_ID_WIDTH = 7;

  typedef logic [SEP_56_64_7_12_ADDR_WIDTH-1:0] sep_56_64_7_12_axi_addr_t;
  typedef logic [SEP_56_64_7_12_DATA_WIDTH-1:0] sep_56_64_7_12_axi_data_t;
  typedef logic [SEP_56_64_7_12_STRB_WIDTH-1:0] sep_56_64_7_12_axi_strb_t;
  typedef logic [SEP_56_64_7_12_USER_WIDTH-1:0] sep_56_64_7_12_axi_user_t;
  typedef logic [SEP_56_64_7_12_ID_WIDTH-1:0] sep_56_64_7_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_56_64_7_12_axi, sep_56_64_7_12_axi_addr_t, sep_56_64_7_12_axi_id_t,
                   sep_56_64_7_12_axi_data_t, sep_56_64_7_12_axi_strb_t, sep_56_64_7_12_axi_user_t)

  // 32/64/7/1 (system peripherals xbar slave 32-bit addr)
  parameter int unsigned SEP_32_64_7_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_64_7_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_32_64_7_12_STRB_WIDTH = SEP_32_64_7_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_64_7_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_64_7_12_ID_WIDTH = 7;

  typedef logic [SEP_32_64_7_12_ADDR_WIDTH-1:0] sep_32_64_7_12_axi_addr_t;
  typedef logic [SEP_32_64_7_12_DATA_WIDTH-1:0] sep_32_64_7_12_axi_data_t;
  typedef logic [SEP_32_64_7_12_STRB_WIDTH-1:0] sep_32_64_7_12_axi_strb_t;
  typedef logic [SEP_32_64_7_12_USER_WIDTH-1:0] sep_32_64_7_12_axi_user_t;
  typedef logic [SEP_32_64_7_12_ID_WIDTH-1:0] sep_32_64_7_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_64_7_12_axi, sep_32_64_7_12_axi_addr_t, sep_32_64_7_12_axi_id_t,
                   sep_32_64_7_12_axi_data_t, sep_32_64_7_12_axi_strb_t, sep_32_64_7_12_axi_user_t)

  // 56/64/8/1 (system peripherals outbound)
  parameter int unsigned SEP_56_64_8_12_ADDR_WIDTH = 56;
  parameter int unsigned SEP_56_64_8_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_56_64_8_12_STRB_WIDTH = SEP_56_64_8_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_56_64_8_12_USER_WIDTH = 12;
  parameter int unsigned SEP_56_64_8_12_ID_WIDTH = 8;

  typedef logic [SEP_56_64_8_12_ADDR_WIDTH-1:0] sep_56_64_8_12_axi_addr_t;
  typedef logic [SEP_56_64_8_12_DATA_WIDTH-1:0] sep_56_64_8_12_axi_data_t;
  typedef logic [SEP_56_64_8_12_STRB_WIDTH-1:0] sep_56_64_8_12_axi_strb_t;
  typedef logic [SEP_56_64_8_12_USER_WIDTH-1:0] sep_56_64_8_12_axi_user_t;
  typedef logic [SEP_56_64_8_12_ID_WIDTH-1:0] sep_56_64_8_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_56_64_8_12_axi, sep_56_64_8_12_axi_addr_t, sep_56_64_8_12_axi_id_t,
                   sep_56_64_8_12_axi_data_t, sep_56_64_8_12_axi_strb_t, sep_56_64_8_12_axi_user_t)

  // AXI-Lite types
  typedef logic [56-1:0] sep_56_64_axil_addr_t;
  typedef logic [64-1:0] sep_56_64_axil_data_t;
  typedef logic [64/8-1:0] sep_56_64_axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL(sep_56_64_axil, sep_56_64_axil_addr_t, sep_56_64_axil_data_t,
                        sep_56_64_axil_strb_t)

  typedef logic [32-1:0] sep_32_64_axil_addr_t;
  typedef logic [64-1:0] sep_32_64_axil_data_t;
  typedef logic [64/8-1:0] sep_32_64_axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL(sep_32_64_axil, sep_32_64_axil_addr_t, sep_32_64_axil_data_t,
                        sep_32_64_axil_strb_t)

  // 56/64/3/1 (system peripherals 56-bit addressing with 3-bit ID)
  parameter int unsigned SEP_56_64_3_12_ADDR_WIDTH = 56;
  parameter int unsigned SEP_56_64_3_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_56_64_3_12_STRB_WIDTH = SEP_56_64_3_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_56_64_3_12_USER_WIDTH = 12;
  parameter int unsigned SEP_56_64_3_12_ID_WIDTH = 3;

  typedef logic [SEP_56_64_3_12_ADDR_WIDTH-1:0] sep_56_64_3_12_axi_addr_t;
  typedef logic [SEP_56_64_3_12_DATA_WIDTH-1:0] sep_56_64_3_12_axi_data_t;
  typedef logic [SEP_56_64_3_12_STRB_WIDTH-1:0] sep_56_64_3_12_axi_strb_t;
  typedef logic [SEP_56_64_3_12_USER_WIDTH-1:0] sep_56_64_3_12_axi_user_t;
  typedef logic [SEP_56_64_3_12_ID_WIDTH-1:0] sep_56_64_3_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_56_64_3_12_axi, sep_56_64_3_12_axi_addr_t, sep_56_64_3_12_axi_id_t,
                   sep_56_64_3_12_axi_data_t, sep_56_64_3_12_axi_strb_t, sep_56_64_3_12_axi_user_t)

  // 56/64/5/1 (system peripherals outbound mux with 5-bit ID)
  parameter int unsigned SEP_56_64_5_12_ADDR_WIDTH = 56;
  parameter int unsigned SEP_56_64_5_12_DATA_WIDTH = 64;
  parameter int unsigned SEP_56_64_5_12_STRB_WIDTH = SEP_56_64_5_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_56_64_5_12_USER_WIDTH = 12;
  parameter int unsigned SEP_56_64_5_12_ID_WIDTH = 5;

  typedef logic [SEP_56_64_5_12_ADDR_WIDTH-1:0] sep_56_64_5_12_axi_addr_t;
  typedef logic [SEP_56_64_5_12_DATA_WIDTH-1:0] sep_56_64_5_12_axi_data_t;
  typedef logic [SEP_56_64_5_12_STRB_WIDTH-1:0] sep_56_64_5_12_axi_strb_t;
  typedef logic [SEP_56_64_5_12_USER_WIDTH-1:0] sep_56_64_5_12_axi_user_t;
  typedef logic [SEP_56_64_5_12_ID_WIDTH-1:0] sep_56_64_5_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_56_64_5_12_axi, sep_56_64_5_12_axi_addr_t, sep_56_64_5_12_axi_id_t,
                   sep_56_64_5_12_axi_data_t, sep_56_64_5_12_axi_strb_t, sep_56_64_5_12_axi_user_t)

  // 32/32/6/1 (WDT TLUL bridge with 32-bit data width)
  parameter int unsigned SEP_32_32_6_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_32_6_12_DATA_WIDTH = 32;  // 32-bit data!
  parameter int unsigned SEP_32_32_6_12_STRB_WIDTH = SEP_32_32_6_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_32_6_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_32_6_12_ID_WIDTH = 6;

  typedef logic [SEP_32_32_6_12_ADDR_WIDTH-1:0] sep_32_32_6_12_axi_addr_t;
  typedef logic [SEP_32_32_6_12_DATA_WIDTH-1:0] sep_32_32_6_12_axi_data_t;
  typedef logic [SEP_32_32_6_12_STRB_WIDTH-1:0] sep_32_32_6_12_axi_strb_t;
  typedef logic [SEP_32_32_6_12_USER_WIDTH-1:0] sep_32_32_6_12_axi_user_t;
  typedef logic [SEP_32_32_6_12_ID_WIDTH-1:0] sep_32_32_6_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_32_6_12_axi, sep_32_32_6_12_axi_addr_t, sep_32_32_6_12_axi_id_t,
                   sep_32_32_6_12_axi_data_t, sep_32_32_6_12_axi_strb_t, sep_32_32_6_12_axi_user_t)

  // 32/32/3/1 (DMA master path with 32-bit data width and 3-bit ID)
  parameter int unsigned SEP_32_32_3_12_ADDR_WIDTH = 32;
  parameter int unsigned SEP_32_32_3_12_DATA_WIDTH = 32;  // 32-bit data!
  parameter int unsigned SEP_32_32_3_12_STRB_WIDTH = SEP_32_32_3_12_DATA_WIDTH / 8;
  parameter int unsigned SEP_32_32_3_12_USER_WIDTH = 12;
  parameter int unsigned SEP_32_32_3_12_ID_WIDTH = 3;

  typedef logic [SEP_32_32_3_12_ADDR_WIDTH-1:0] sep_32_32_3_12_axi_addr_t;
  typedef logic [SEP_32_32_3_12_DATA_WIDTH-1:0] sep_32_32_3_12_axi_data_t;
  typedef logic [SEP_32_32_3_12_STRB_WIDTH-1:0] sep_32_32_3_12_axi_strb_t;
  typedef logic [SEP_32_32_3_12_USER_WIDTH-1:0] sep_32_32_3_12_axi_user_t;
  typedef logic [SEP_32_32_3_12_ID_WIDTH-1:0] sep_32_32_3_12_axi_id_t;

  `AXI_TYPEDEF_ALL(sep_32_32_3_12_axi, sep_32_32_3_12_axi_addr_t, sep_32_32_3_12_axi_id_t,
                   sep_32_32_3_12_axi_data_t, sep_32_32_3_12_axi_strb_t, sep_32_32_3_12_axi_user_t)

  // 32-bit data width AXI-Lite types (for DMA wrapper conversions)
  typedef logic [32-1:0] sep_32_32_axil_addr_t;
  typedef logic [32-1:0] sep_32_32_axil_data_t;
  typedef logic [32/8-1:0] sep_32_32_axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL(sep_32_32_axil, sep_32_32_axil_addr_t, sep_32_32_axil_data_t,
                        sep_32_32_axil_strb_t)

  parameter int unsigned AXI_LITE_BRIDGE_AXI_ADDR_WIDTH = 32;
  parameter int unsigned AXI_LITE_BRIDGE_AXI_DATA_WIDTH = 64;
  parameter int unsigned AXI_LITE_BRIDGE_AXI_STRB_WIDTH = AXI_LITE_BRIDGE_AXI_DATA_WIDTH / 8;
  parameter int unsigned AXI_LITE_BRIDGE_AXI_USER_WIDTH = 12;
  parameter int unsigned AXI_LITE_BRIDGE_AXI_ID_WIDTH = 6;

  // For convenience in legacy typedefs
  parameter int unsigned CPU_ADDR_WIDTH = 32;
  parameter int unsigned CPU_DATA_WIDTH = 64;
  parameter int unsigned CPU_USER_WIDTH = 12;
  parameter int unsigned CPU_MST_ID_WIDTH = SEP_32_64_3_12_ID_WIDTH;  // 3-bit.
  parameter int unsigned CPU_SLV_ID_WIDTH = SEP_32_64_6_12_ID_WIDTH;  // 6-bit.

  // Misc parameters
  localparam int unsigned LC_STATE_BIT_POSITION = 96;
  localparam int unsigned LC_STATE_BIT_WIDTH = 4;

  //////////////////////////////////
  // SEP System Peripherals Types //
  //////////////////////////////////

  // Address Remap (from local masters)
  localparam int unsigned ADDRESS_REMAP_DEMUX_PORTS = 5;

  typedef enum logic [$clog2(
ADDRESS_REMAP_DEMUX_PORTS
)-1:0] {
    SEP_EXT_TO_SMC     = 0,
    SEP_EXT_TO_SMU     = 1,
    SEP_EXT_AP_REMAP   = 2,
    SEP_EXT_STEE_REMAP = 3,
    SEP_LOCAL          = 4
  } address_remap_demux_select_t;

  // External To Chiplet Address Range
  localparam logic [SEP_56_64_5_12_ADDR_WIDTH-1:0] EXTERNAL_TO_CHIPLET_BASE_ADDR = 56'h1_0000_0000;

  // Outbound Filter Mux
  localparam int unsigned OUTBOUND_FILTER_MUX_PORTS = 3;

  typedef enum logic [$clog2(
OUTBOUND_FILTER_MUX_PORTS
)-1:0] {
    OUTBOUND_FILTER_LOCAL_MASTER = 0,
    OUTBOUND_FILTER_AP = 1,
    OUTBOUND_FILTER_STEE = 2
  } outbound_filter_mux_select_t;

  // Outbound Filter
  localparam int unsigned OUTBOUND_FILTER_NUM_FILTERS = 32;

  typedef logic [$clog2(OUTBOUND_FILTER_NUM_FILTERS)-1:0] outbound_filter_select_t;

  // Inbound Filter
  localparam int unsigned INBOUND_FILTER_NUM_FILTERS = 16;

  typedef logic [$clog2(INBOUND_FILTER_NUM_FILTERS)-1:0] inbound_filter_select_t;

  // Mailbox
  localparam int unsigned NUM_MAILBOXES = 8;
  localparam int unsigned MAILBOX_DEPTH = 8;
  localparam int unsigned MAILBOX_SIZE = sep_top_addrmap_pkg::SEP_TOP_AXIL_MAILBOX_INBOUND_MAILBOX_0_BASE_ADDR - sep_top_addrmap_pkg::SEP_TOP_AXIL_MAILBOX_OUTBOUND_MAILBOX_0_BASE_ADDR; // 0x800 -> 2kb.

  // System CSRs
  localparam int unsigned SYSTEM_CSR_DEMUX_PORTS = 9;

  typedef enum logic [$clog2(
SYSTEM_CSR_DEMUX_PORTS
)-1:0] {
    LOCAL_MASTER_ALIAS_REMAP = 0,
    AP_OUTPUT_REMAP = 1,
    STEE_OUTPUT_REMAP = 2,
    OUTBOUND_FILTER = 3,
    INBOUND_FILTER = 4,
    SEP_CPU_CTRL = 5,
    SEP_SCRATCH_COLD = 6,
    SEP_SCRATCH_WARM = 7,
    ERR_SLV = 8
  } system_csr_demux_select_t;

  //////////
  // AXI4-Lite definitions
  //////////

  parameter int unsigned AXILITE_XBAR_EXTERNAL_SLV_IDX = 0;

  parameter int unsigned AXILITE_XBAR_N_MST = 32'd4;  // Crypto/security + IO + SEP system peripherals + external master.

  typedef logic [CPU_ADDR_WIDTH  -1:0] sep_axilite_xbar_addr_t;
  typedef logic [CPU_DATA_WIDTH  -1:0] sep_axilite_xbar_data_t;
  typedef logic [CPU_DATA_WIDTH/8-1:0] sep_axilite_xbar_strb_t;

  // Define the types:
  //   sep_axilite_xbar_aw_chan_t
  //   sep_axilite_xbar_w_chan_t
  //   sep_axilite_xbar_b_chan_t
  //   sep_axilite_xbar_ar_chan_t
  //   sep_axilite_xbar_r_chan_t
  //   sep_axilite_xbar_req_t
  //   sep_axilite_xbar_resp_t
  `AXI_LITE_TYPEDEF_ALL(sep_axilite_xbar, sep_axilite_xbar_addr_t, sep_axilite_xbar_data_t,
                        sep_axilite_xbar_strb_t)

  //////////
  // External interface types (mostly placeholders for now)
  //////////

  typedef logic sep_private_io_req_t;
  typedef logic sep_private_io_rsp_t;

  // Memory interface parameters (matches axi_to_mem output format)
  parameter int unsigned SEP_MEM_ADDR_WIDTH = 32;
  parameter int unsigned SEP_MEM_DATA_WIDTH = 64;
  parameter int unsigned SEP_MEM_STRB_WIDTH = SEP_MEM_DATA_WIDTH / 8;

  // SRAM memory interface (axi_to_mem format)
  typedef struct packed {
    logic                           req;
    logic [SEP_MEM_ADDR_WIDTH-1:0]  addr;
    logic [SEP_MEM_DATA_WIDTH-1:0]  wdata;
    logic [SEP_MEM_STRB_WIDTH-1:0]  strb;
    axi_pkg::atop_t                 atop;
    logic                           wenable;
  } sep_sram_req_t;

  typedef struct packed {
    logic                           gnt;
    logic                           rvalid;
    logic [SEP_MEM_DATA_WIDTH-1:0]  rdata;
  } sep_sram_rsp_t;

  // EL2 specific values (computed based on "pt" struct)
  // To use another core, modify the internals of these typedefs but keep the type names

  import el2_pkg::*;
  `include "el2_param.vh"
  ;

  parameter int unsigned SEP_CPU_IRQ_WIDTH = pt.PIC_TOTAL_INT;

  typedef el2_trace_pkt_t sep_cpu_trace_t;

  // VeeR lockstep control/status. These are carried unconditionally through the
  // hierarchy above sep_cpu so the port footprint does not change with
  // RV_LOCKSTEP_ENABLE; sep_cpu zeroes the status and sinks the control when the
  // core is built without lockstep.
  typedef struct packed {
    logic disable_corruption_detection;
    logic err_injection_en;
  } sep_lockstep_ctrl_t;

  typedef struct packed {logic corruption_detected;} sep_lockstep_status_t;

  // TCM (ICCM/DCCM) memory interface types
  // Request struct: from CPU to TCM macros (active-high signals from EL2 core)
  typedef struct packed {
    logic                                                               clk;

    logic [pt.ICCM_NUM_BANKS-1:0]                                       iccm_clken;
    logic [pt.ICCM_NUM_BANKS-1:0]                                       iccm_wren_bank;
    logic [pt.ICCM_NUM_BANKS-1:0][pt.ICCM_BITS-1:pt.ICCM_BANK_INDEX_LO] iccm_addr_bank;

    logic [pt.ICCM_NUM_BANKS-1:0][31:0]                                 iccm_bank_wr_data;
    logic [pt.ICCM_NUM_BANKS-1:0][pt.ICCM_ECC_WIDTH-1:0]                iccm_bank_wr_ecc;

    logic [pt.DCCM_NUM_BANKS-1:0]                                       dccm_clken;
    logic [pt.DCCM_NUM_BANKS-1:0]                                       dccm_wren_bank;
    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_BITS-1:(pt.DCCM_BANK_BITS+2)] dccm_addr_bank;

    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_DATA_WIDTH-1:0]               dccm_wr_data_bank;
    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_ECC_WIDTH-1:0]                dccm_wr_ecc_bank;
  } sep_cpu_tcm_req_t;

  // Response struct: from TCM macros back to CPU
  typedef struct packed {
    logic [pt.ICCM_NUM_BANKS-1:0][31:0]                                 iccm_bank_dout;
    logic [pt.ICCM_NUM_BANKS-1:0][pt.ICCM_ECC_WIDTH-1:0]                iccm_bank_ecc;

    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_DATA_WIDTH-1:0]               dccm_bank_dout;
    logic [pt.DCCM_NUM_BANKS-1:0][pt.DCCM_ECC_WIDTH-1:0]                dccm_bank_ecc;
  } sep_cpu_tcm_rsp_t;

  /////////////
  // SEP CPU //
  /////////////

  // IFU Demux
  parameter int unsigned SEP_IFU_DEMUX_NUM_PORTS = 3;
  typedef enum logic [$clog2(
SEP_IFU_DEMUX_NUM_PORTS
)-1:0] {
    SEP_IFU_DEMUX_PORT_ROM     = 0,
    SEP_IFU_DEMUX_PORT_SRAM    = 1,
    SEP_IFU_DEMUX_PORT_ERR_SLV = 2
  } sep_ifu_demux_port_t;

  // LSU Demux
  parameter int unsigned SEP_LSU_DEMUX_NUM_PORTS = 2;
  typedef enum logic [$clog2(
SEP_LSU_DEMUX_NUM_PORTS
)-1:0] {
    SEP_LSU_DEMUX_PORT_ROM  = 0,
    SEP_LSU_DEMUX_PORT_XBAR = 1
  } sep_lsu_demux_port_t;

  // Boot ROM Mux (merges IFU and LSU ROM streams onto the single ROM port)
  parameter int unsigned SEP_ROM_MUX_NUM_PORTS = 2;
  typedef enum logic [$clog2(
SEP_ROM_MUX_NUM_PORTS
)-1:0] {
    SEP_ROM_MUX_PORT_IFU = 0,
    SEP_ROM_MUX_PORT_LSU = 1
  } sep_rom_mux_port_t;

  typedef logic sep_mailbox_slv_req_t;
  typedef logic sep_mailbox_slv_rsp_t;

  // Internal SEP interrupt sources occupying the low PIC slots; see the
  // sep_internal_interrupts aggregation in sep.sv for the slot map. Growing this
  // shifts the external sources up and narrows NUM_EXTERNAL_IRQS accordingly.
  // 34,35 = Adams Bridge error / notif; 36,37,38 = entropy pool low / fill stall /
  // pointer-integrity fault; 39 = eFuse token comparator redundancy fault; 40,41 = Secure DMA
  // register-path bus error / host-path integrity fault (level, cleared via
  // DMA_BUS_ERR_CLEAR); 42 = aggregated peripheral register-bridge fault (level,
  // per-block source identified by PERIPH_BUS_ERR_STATUS and cleared via
  // PERIPH_BUS_ERR_CLEAR).
  parameter int unsigned NUM_INTERNAL_IRQS = 43;
  parameter int unsigned NUM_EXTERNAL_IRQS = pt.PIC_TOTAL_INT - NUM_INTERNAL_IRQS;

  // Peripheral register-bridge fault bit map. This ordering is shared by the
  // periph_bus_err vector assembled in sep.sv and the PERIPH_BUS_ERR_STATUS /
  // PERIPH_BUS_ERR_CLEAR fields in sep_cpu_ctrl.rdl; changing one without the other
  // silently misattributes faults to the wrong block.
  parameter int unsigned NUM_PERIPH_BUS_ERRS = 7;
  typedef enum int unsigned {
    PERIPH_BUS_ERR_AES   = 0,
    PERIPH_BUS_ERR_HMAC  = 1,
    PERIPH_BUS_ERR_KMAC  = 2,
    PERIPH_BUS_ERR_OTBN  = 3,
    PERIPH_BUS_ERR_CSRNG = 4,
    PERIPH_BUS_ERR_EDN   = 5,
    PERIPH_BUS_ERR_WDT   = 6
  } periph_bus_err_e;

  /////////////////////////////////////////////
  // Alias + Output Remap parameters + types //
  /////////////////////////////////////////////

  parameter int unsigned NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS = 16;
  parameter int unsigned ALIAS_REMAP_SEL_W = $clog2(NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS);
  parameter int unsigned NUM_AP_OUTPUT_REMAP_REGIONS = 16;
  parameter int unsigned AP_REMAP_SEL_W = $clog2(NUM_AP_OUTPUT_REMAP_REGIONS);
  parameter int unsigned NUM_STEE_OUTPUT_REMAP_REGIONS = 16;
  parameter int unsigned STEE_REMAP_SEL_W = $clog2(NUM_STEE_OUTPUT_REMAP_REGIONS);
  parameter int unsigned ALIAS_REMAP_IDX_START = 12;  // 4KB region granularity.
  parameter int unsigned AP_OUTPUT_REMAP_IDX_START = 19;  // 512KB region granularity.
  parameter int unsigned STEE_OUTPUT_REMAP_IDX_START = 19;  // 512KB region granularity.

  // Fixed size of the SEP local alias remap window. This is decoupled from the
  // SMU-programmable SEP_REGION_SIZE CSR (exported as sep_region_size_o to size the
  // SMU-visible aperture); the local alias window is a fixed architectural constant.
  localparam logic [55:0] SEP_LOCAL_ALIAS_REGION_SIZE = 56'h3000_0000;  // 768 MiB.
  localparam logic [55:0] SEP_LOCAL_ALIAS_REGION_BASE = 56'h1000_0000;  // 0x1000_0000 - 0x3FFF_FFFF.
  localparam logic [55:0] SEP_GLOBAL_REGION_SIZE = 56'h4000_0000;  // 1 GiB.

  localparam logic [3:0] SEP_SOURCE_ID = 4'b1111;
  localparam logic [3:0] MMODE_SOURCE_ID = 4'b1100;
  localparam logic [3:0] SMC_SOURCE_ID = 4'b0011;
  localparam logic [3:0] OTHERS_SOURCE_ID = 4'b0000;

  typedef struct packed {
    logic [$clog2(NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS)-1:0] aw_remap_hit_debug;
    logic [$clog2(NUM_LOCAL_MASTER_ALIAS_REMAP_REGIONS)-1:0] ar_remap_hit_debug;
  } remap_debug_t;

  typedef struct packed {
    logic [SEP_56_64_3_12_ADDR_WIDTH-1:0] region_start;
    logic [SEP_56_64_3_12_ADDR_WIDTH-1:0] region_end;
    logic [SEP_56_64_3_12_ADDR_WIDTH-1:0] offset;
    axi_pkg::cache_t cacheable;
    logic region_valid;
  } remap_region_t;

  /////////////////////////////////////
  // SEP Software Reset Controller   //
  /////////////////////////////////////

  typedef struct packed {
    logic abr;
    logic trng;
    logic kmac;
    logic hmac;
    logic aes;
    logic otbn;
    logic km;
  } sep_sw_rst_t;

  // One bit per isolatable AXI path in sep_crypto. trng_* are the converted
  // CSR paths to the internal TRNG complex; host_* are the SEP host paths to
  // the accelerator wrappers; km_* are the Key Manager master paths to its
  // slaves. ABR's host path is full AXI; the other paths are AXI-Lite. The
  // same layout is used for isolate_req and isolated.
  typedef struct packed {
    logic trng_entropy_source;
    logic trng_csrng;
    logic trng_edn;
    logic host_otbn;
    logic host_aes;
    logic host_hmac;
    logic host_kmac;
    logic host_abr;
    logic km_otbn;
    logic km_aes;
    logic km_hmac;
    logic km_kmac;
    logic km_abr;
    logic km_efuse;
  } sep_crypto_isolate_t;

  ////////////////////////////
  // SEP System Peripherals //
  ////////////////////////////

  // Legacy 56-bit address width parameter (to be removed in module updates)
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_56_ADDR_WIDTH = 56;

  // System Peripherals Xbar Slave 56 Addr-Width AXI (legacy - to be removed in module updates)
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_ADDR_WIDTH = 56;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_DATA_WIDTH / 8;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_ID_WIDTH = 7;

  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_ADDR_WIDTH-1:0] sep_system_peripherals_xbar_slv_axi_addr_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_DATA_WIDTH-1:0] sep_system_peripherals_xbar_slv_axi_data_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_STRB_WIDTH-1:0] sep_system_peripherals_xbar_slv_axi_strb_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_USER_WIDTH-1:0] sep_system_peripherals_xbar_slv_axi_user_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_AXI_ID_WIDTH-1:0]   sep_system_peripherals_xbar_slv_axi_id_t;

  `AXI_TYPEDEF_ALL(
      sep_system_peripherals_xbar_slv_axi, sep_system_peripherals_xbar_slv_axi_addr_t,
      sep_system_peripherals_xbar_slv_axi_id_t, sep_system_peripherals_xbar_slv_axi_data_t,
      sep_system_peripherals_xbar_slv_axi_strb_t, sep_system_peripherals_xbar_slv_axi_user_t)

  // System Peripherals Xbar Slave 32 Addr-Width AXI
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ADDR_WIDTH = 32;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_DATA_WIDTH / 8;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ID_WIDTH = 7;

  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ADDR_WIDTH-1:0] sep_system_peripherals_xbar_slv_32_axi_addr_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_DATA_WIDTH-1:0] sep_system_peripherals_xbar_slv_32_axi_data_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_STRB_WIDTH-1:0] sep_system_peripherals_xbar_slv_32_axi_strb_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_USER_WIDTH-1:0] sep_system_peripherals_xbar_slv_32_axi_user_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_XBAR_SLV_32_AXI_ID_WIDTH-1:0]   sep_system_peripherals_xbar_slv_32_axi_id_t;

  `AXI_TYPEDEF_ALL(
      sep_system_peripherals_xbar_slv_32_axi, sep_system_peripherals_xbar_slv_32_axi_addr_t,
      sep_system_peripherals_xbar_slv_32_axi_id_t, sep_system_peripherals_xbar_slv_32_axi_data_t,
      sep_system_peripherals_xbar_slv_32_axi_strb_t, sep_system_peripherals_xbar_slv_32_axi_user_t)

  // System CSR AXI4-Lite
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH = 56;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH / 8;

  typedef logic [SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_ADDR_WIDTH-1:0] sep_system_peripherals_system_csr_axi_lite_addr_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_DATA_WIDTH-1:0] sep_system_peripherals_system_csr_axi_lite_data_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_SYSTEM_CSR_AXI_LITE_STRB_WIDTH-1:0] sep_system_peripherals_system_csr_axi_lite_strb_t;

  `AXI_LITE_TYPEDEF_ALL(sep_system_peripherals_system_csr_axi_lite,
                        sep_system_peripherals_system_csr_axi_lite_addr_t,
                        sep_system_peripherals_system_csr_axi_lite_data_t,
                        sep_system_peripherals_system_csr_axi_lite_strb_t)

  // Mailbox AXI4-Lite
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_ADDR_WIDTH = 32;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_DATA_WIDTH / 8;

  typedef logic [SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_ADDR_WIDTH-1:0] sep_system_peripherals_mailbox_axi_lite_addr_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_DATA_WIDTH-1:0] sep_system_peripherals_mailbox_axi_lite_data_t;
  typedef logic [SEP_SYSTEM_PERIPHERALS_MAILBOX_AXI_LITE_STRB_WIDTH-1:0] sep_system_peripherals_mailbox_axi_lite_strb_t;

  `AXI_LITE_TYPEDEF_ALL(sep_system_peripherals_mailbox_axi_lite,
                        sep_system_peripherals_mailbox_axi_lite_addr_t,
                        sep_system_peripherals_mailbox_axi_lite_data_t,
                        sep_system_peripherals_mailbox_axi_lite_strb_t)

  // System Peripherals Internal AXI (legacy - to be removed in module updates)
  // Maps to sep_56_64_6_12_axi types
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ADDR_WIDTH = 56;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_DATA_WIDTH / 8;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INTERNAL_AXI_ID_WIDTH = 6;

  typedef sep_56_64_6_12_axi_aw_chan_t sep_system_peripherals_internal_axi_aw_chan_t;
  typedef sep_56_64_6_12_axi_w_chan_t sep_system_peripherals_internal_axi_w_chan_t;
  typedef sep_56_64_6_12_axi_b_chan_t sep_system_peripherals_internal_axi_b_chan_t;
  typedef sep_56_64_6_12_axi_ar_chan_t sep_system_peripherals_internal_axi_ar_chan_t;
  typedef sep_56_64_6_12_axi_r_chan_t sep_system_peripherals_internal_axi_r_chan_t;
  typedef sep_56_64_6_12_axi_req_t sep_system_peripherals_internal_axi_req_t;
  typedef sep_56_64_6_12_axi_resp_t sep_system_peripherals_internal_axi_resp_t;

  // System Peripherals Outbound AXI (legacy - to be removed in module updates)
  // Maps to sep_56_64_8_12_axi types
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_ADDR_WIDTH = 56;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_DATA_WIDTH / 8;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_OUTBOUND_AXI_ID_WIDTH = 8;

  typedef sep_56_64_8_12_axi_aw_chan_t sep_system_peripherals_outbound_axi_aw_chan_t;
  typedef sep_56_64_8_12_axi_w_chan_t sep_system_peripherals_outbound_axi_w_chan_t;
  typedef sep_56_64_8_12_axi_b_chan_t sep_system_peripherals_outbound_axi_b_chan_t;
  typedef sep_56_64_8_12_axi_ar_chan_t sep_system_peripherals_outbound_axi_ar_chan_t;
  typedef sep_56_64_8_12_axi_r_chan_t sep_system_peripherals_outbound_axi_r_chan_t;
  typedef sep_56_64_8_12_axi_req_t sep_system_peripherals_outbound_axi_req_t;
  typedef sep_56_64_8_12_axi_resp_t sep_system_peripherals_outbound_axi_resp_t;

  // System Peripherals Inbound to SEP AXI (legacy - to be removed in module updates)
  // Maps to sep_32_64_3_12_axi types
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_ADDR_WIDTH = 32;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_STRB_WIDTH = SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_DATA_WIDTH / 8;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_SYSTEM_PERIPHERALS_INBOUND_TO_SEP_AXI_ID_WIDTH = 3;

  typedef sep_32_64_3_12_axi_aw_chan_t sep_system_peripherals_inbound_to_sep_axi_aw_chan_t;
  typedef sep_32_64_3_12_axi_w_chan_t sep_system_peripherals_inbound_to_sep_axi_w_chan_t;
  typedef sep_32_64_3_12_axi_b_chan_t sep_system_peripherals_inbound_to_sep_axi_b_chan_t;
  typedef sep_32_64_3_12_axi_ar_chan_t sep_system_peripherals_inbound_to_sep_axi_ar_chan_t;
  typedef sep_32_64_3_12_axi_r_chan_t sep_system_peripherals_inbound_to_sep_axi_r_chan_t;
  typedef sep_32_64_3_12_axi_req_t sep_system_peripherals_inbound_to_sep_axi_req_t;
  typedef sep_32_64_3_12_axi_resp_t sep_system_peripherals_inbound_to_sep_axi_resp_t;

  // SEP IO AXI types (legacy - to be removed when sep_io_pkg is updated)
  // Maps to sep_32_64_6_12_axi types
  typedef sep_32_64_6_12_axi_id_t sep_io_axi_id_t;
  typedef sep_32_64_6_12_axi_user_t sep_io_axi_user_t;

  // SEP AXI Crossbar Master types (legacy - to be removed in module updates)
  // Maps to sep_32_64_3_12_axi types (32-bit addr, 64-bit data, 3-bit ID, 1-bit user)
  typedef sep_32_64_3_12_axi_aw_chan_t sep_axi_xbar_mst_aw_chan_t;
  typedef sep_32_64_3_12_axi_w_chan_t sep_axi_xbar_mst_w_chan_t;
  typedef sep_32_64_3_12_axi_b_chan_t sep_axi_xbar_mst_b_chan_t;
  typedef sep_32_64_3_12_axi_ar_chan_t sep_axi_xbar_mst_ar_chan_t;
  typedef sep_32_64_3_12_axi_r_chan_t sep_axi_xbar_mst_r_chan_t;
  typedef sep_32_64_3_12_axi_req_t sep_axi_xbar_mst_req_t;
  typedef sep_32_64_3_12_axi_resp_t sep_axi_xbar_mst_resp_t;

  // SEP AXI Crossbar Slave types (legacy - to be removed in module updates)
  // Maps to sep_32_64_6_12_axi types (32-bit addr, 64-bit data, 6-bit ID, 1-bit user)
  typedef sep_32_64_6_12_axi_aw_chan_t sep_axi_xbar_slv_aw_chan_t;
  typedef sep_32_64_6_12_axi_w_chan_t sep_axi_xbar_slv_w_chan_t;
  typedef sep_32_64_6_12_axi_b_chan_t sep_axi_xbar_slv_b_chan_t;
  typedef sep_32_64_6_12_axi_ar_chan_t sep_axi_xbar_slv_ar_chan_t;
  typedef sep_32_64_6_12_axi_r_chan_t sep_axi_xbar_slv_r_chan_t;
  typedef sep_32_64_6_12_axi_req_t sep_axi_xbar_slv_req_t;
  typedef sep_32_64_6_12_axi_resp_t sep_axi_xbar_slv_resp_t;

  // SEP Crypto AXI types (legacy - to be removed in module updates)
  // Maps to sep_32_64_6_12_axi types (32-bit addr, 64-bit data, 6-bit ID, 1-bit user)
  parameter int unsigned SEP_CRYPTO_AXI_ADDR_WIDTH = 32;
  parameter int unsigned SEP_CRYPTO_AXI_DATA_WIDTH = 64;
  parameter int unsigned SEP_CRYPTO_AXI_STRB_WIDTH = 8;
  parameter int unsigned SEP_CRYPTO_AXI_USER_WIDTH = 12;
  parameter int unsigned SEP_CRYPTO_AXI_ID_WIDTH = 6;

  typedef sep_32_64_6_12_axi_addr_t sep_crypto_axi_addr_t;
  typedef sep_32_64_6_12_axi_data_t sep_crypto_axi_data_t;
  typedef sep_32_64_6_12_axi_strb_t sep_crypto_axi_strb_t;
  typedef sep_32_64_6_12_axi_user_t sep_crypto_axi_user_t;
  typedef sep_32_64_6_12_axi_id_t sep_crypto_axi_id_t;
  typedef sep_32_64_6_12_axi_aw_chan_t sep_crypto_axi_aw_chan_t;
  typedef sep_32_64_6_12_axi_w_chan_t sep_crypto_axi_w_chan_t;
  typedef sep_32_64_6_12_axi_b_chan_t sep_crypto_axi_b_chan_t;
  typedef sep_32_64_6_12_axi_ar_chan_t sep_crypto_axi_ar_chan_t;
  typedef sep_32_64_6_12_axi_r_chan_t sep_crypto_axi_r_chan_t;
  typedef sep_32_64_6_12_axi_req_t sep_crypto_axi_req_t;
  typedef sep_32_64_6_12_axi_resp_t sep_crypto_axi_resp_t;

  // IFU AXI types (legacy - to be removed in module updates)
  // Maps to sep_32_64_3_12_axi types
  typedef sep_32_64_3_12_axi_req_t ifu_axi_req_t;
  typedef sep_32_64_3_12_axi_resp_t ifu_axi_resp_t;

  // LSU AXI types (legacy - to be removed in module updates)
  // Maps to sep_32_64_3_12_axi types
  typedef sep_32_64_3_12_axi_req_t lsu_axi_req_t;
  typedef sep_32_64_3_12_axi_resp_t lsu_axi_resp_t;

  // DBG AXI types (legacy - to be removed in module updates)
  // Maps to sep_32_64_3_12_axi types
  typedef sep_32_64_3_12_axi_req_t dbg_axi_req_t;
  typedef sep_32_64_3_12_axi_resp_t dbg_axi_resp_t;

  // TCM AXI types (legacy - to be removed in module updates)
  // Maps to sep_32_64_6_12_axi types
  typedef sep_32_64_6_12_axi_req_t tcm_axi_req_t;
  typedef sep_32_64_6_12_axi_resp_t tcm_axi_resp_t;

  // Mux output types (legacy - used in testbench)
  // Maps to sep_56_64_5_12_axi types (56-bit addr, 5-bit ID)
  typedef sep_56_64_5_12_axi_req_t mux_out_axi_req_t;
  typedef sep_56_64_5_12_axi_resp_t mux_out_axi_resp_t;

  // JTAG SEP Reset Control
  typedef struct packed {
    // jtag_ptap sizes the SEP IC_RESET slice from $bits(type)/2 and maps the
    // ovrd and val sub-structs independently by packed bit index. Fields run
    // from TDI to TDO in declaration order.
    logic abr_jtag_rst_n_ovrd;
    logic trng_jtag_rst_n_ovrd;
    logic sep_reset_n_ovrd;
    logic kmac_jtag_rst_n_ovrd;
    logic hmac_jtag_rst_n_ovrd;
    logic aes_jtag_rst_n_ovrd;
    logic otbn_jtag_rst_n_ovrd;
    logic km_jtag_rst_n_ovrd;
  } jtag_sep_reset_ctrl_ovrd_t;

  typedef struct packed {
    logic abr_jtag_rst_n_val;
    logic trng_jtag_rst_n_val;
    logic sep_reset_n_val;
    logic kmac_jtag_rst_n_val;
    logic hmac_jtag_rst_n_val;
    logic aes_jtag_rst_n_val;
    logic otbn_jtag_rst_n_val;
    logic km_jtag_rst_n_val;
  } jtag_sep_reset_ctrl_val_t;

  typedef struct packed {
    jtag_sep_reset_ctrl_ovrd_t ovrd;
    jtag_sep_reset_ctrl_val_t val;
  } jtag_sep_reset_ctrl_t;

endpackage
