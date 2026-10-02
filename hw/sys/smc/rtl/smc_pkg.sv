// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Share SMC types, address-map helpers, and fabric typedefs.
//
// Packages AXI, AXI-Lite and APB request/response types used across the SMC hierarchy.
// Holds mailbox counts, GPIO wrap counts, and other constants the top-level and fabrics
// share, the M-mode and Xvisor remap windows taken from smc_top_addrmap_pkg, the JTAG
// reset-control override type, and the address-width adjustment assignment macros.

`ifndef SMC_PACKAGE_DEFINED
`define SMC_PACKAGE_DEFINED

package smc_pkg;

  // Include register header file

  // Peripheral parameters
  localparam int unsigned NumBondedGpio = 61;
  localparam int unsigned NumUnbondedGpio = 4;
  localparam int unsigned NumGpioWraps = NumBondedGpio + NumUnbondedGpio;

  // DFD parameters
  localparam int unsigned XtriggerWidth = 2;
  typedef logic [XtriggerWidth-1:0] xtrigger_t;
  localparam int unsigned NumMaxExternalXtrigAgents = 6;

  `include "axi/typedef.svh"
  `include "apb/typedef.svh"

  //////////////////////////////
  // AXI Parameters - General //
  //////////////////////////////

  // Full AXI
  localparam int unsigned AxiAddrWidth = 56;  // General AXI address width.
  localparam int unsigned SmcLocalAddrWidth = 32;  // Within SMC.

  localparam int unsigned AxiDataWidth = 64;
  localparam int unsigned AxiStrbWidth = AxiDataWidth / 8;
  localparam int unsigned AxiUserWidth = 12;

  localparam int unsigned Axi32DataWidth = 32;
  localparam int unsigned Axi32StrbWidth = Axi32DataWidth / 8;

  // Input ID Width Parameters
  localparam int unsigned SysInIdWidth = 6;
  localparam int unsigned JtagIdWidth = 2;
  localparam int unsigned SepInIdWidth = 6;

  // Output ID Width Parameters
  localparam int unsigned SysOutIdWidth = 8;

  // Fabric ID Width Parameters
  localparam int unsigned SmcInputFabricSlaveIdWidth = 4;  // Into Input Fabric.
  localparam int unsigned SmcLocalOutputFabricSlaveIdWidth = 6; // Input to Local Fabric/Output Fabric.
  localparam int unsigned SmcLocalFabricXbarMasterIdWidth  = 8; // Out of Local Fabric to CPU cluster + Peripherals.
  localparam int unsigned SmcOutputFabricMasterIdWidth = 8;  // Out of Output Fabric.

  // MMIO AXI interface (output from DigitalTop)
  // - ID width: 3 bits, Address: 56 bits, Data: 64 bits
  localparam int unsigned SmcCpuMmioAxiIdWidth = 3;

  // L2 Frontend Bus AXI interface (input to DigitalTop)
  // - ID width: 8 bits, Address: 56 bits, Data: 64 bits
  localparam int unsigned SmcCpuL2FrontendAxiIdWidth = 8;

  // AXI-Lite
  localparam int unsigned AxiLite64DataWidth = 64;
  localparam int unsigned AxiLite32DataWidth = 32;

  //////////////////
  // AXI Typedefs //
  //////////////////

  typedef logic [AxiAddrWidth-1:0] smc_axi_addr_t;
  typedef logic [SmcLocalAddrWidth-1:0] smc_axi_local_addr_t;

  typedef logic [AxiDataWidth-1:0] smc_axi_data_t;
  typedef logic [AxiStrbWidth-1:0] smc_axi_strb_t;
  typedef logic [AxiUserWidth-1:0] smc_axi_user_t;

  typedef logic [Axi32DataWidth-1:0] smc_axi_32_data_t;
  typedef logic [Axi32StrbWidth-1:0] smc_axi_32_strb_t;

  // SMC System Inputs
  typedef logic [SysInIdWidth-1:0] smc_sys_in_id_t;
  typedef logic [JtagIdWidth-1:0] smc_jtag_id_t;
  typedef logic [SepInIdWidth-1:0] smc_sep_in_id_t;

  // Types follow naming convention: name_<addr_width>_<data_width>_<id_width>_<user_width>_axi
  `AXI_TYPEDEF_ALL(smc_sys_in_56_64_6_12_axi, smc_axi_addr_t, smc_sys_in_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_jtag_56_64_2_12_axi, smc_axi_addr_t, smc_jtag_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_sep_in_56_64_6_12_axi, smc_axi_addr_t, smc_sep_in_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // SMC System Outputs
  typedef logic [SysOutIdWidth-1:0] smc_sys_out_id_t;
  `AXI_TYPEDEF_ALL(smc_sys_out_56_64_8_12_axi, smc_axi_addr_t, smc_sys_out_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // Input Fabric Inputs
  typedef logic [SmcInputFabricSlaveIdWidth-1:0] smc_input_fabric_slave_id_t;
  `AXI_TYPEDEF_ALL(smc_input_fabric_56_64_4_12_axi, smc_axi_addr_t, smc_input_fabric_slave_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // Input to Local Fabric/Output Fabric
  typedef logic [SmcLocalOutputFabricSlaveIdWidth-1:0] smc_local_output_fabric_slave_id_t;
  `AXI_TYPEDEF_ALL(smc_56_64_6_12_axi, smc_axi_addr_t, smc_local_output_fabric_slave_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_local_32_64_6_12_axi, smc_axi_local_addr_t,
                   smc_local_output_fabric_slave_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // Local Fabric to peripherals
  // one 64bit and one 32bit data version for internal and external peripherals
  typedef logic [SmcLocalFabricXbarMasterIdWidth-1:0] smc_local_fabric_xbar_master_id_t;
  `AXI_TYPEDEF_ALL(smc_local_32_64_8_12_axi, smc_axi_local_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)
  `AXI_TYPEDEF_ALL(smc_local_32_32_8_12_axi, smc_axi_local_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_32_data_t, smc_axi_32_strb_t,
                   smc_axi_user_t)

  // Output Fabric Output
  typedef logic [SmcOutputFabricMasterIdWidth-1:0] smc_output_fabric_master_id_t;
  `AXI_TYPEDEF_ALL(smc_output_56_64_8_12_axi, smc_axi_addr_t, smc_output_fabric_master_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // MMIO AXI types
  typedef logic [SmcCpuMmioAxiIdWidth-1:0] smc_cpu_mmio_axi_id_t;
  `AXI_TYPEDEF_ALL(smc_cpu_mmio_axi, smc_axi_addr_t, smc_cpu_mmio_axi_id_t, smc_axi_data_t,
                   smc_axi_strb_t, smc_axi_user_t)

  // L2 Frontend Bus AXI types
  typedef logic [SmcCpuL2FrontendAxiIdWidth-1:0] smc_cpu_l2_frontend_axi_id_t;
  `AXI_TYPEDEF_ALL(smc_cpu_l2_frontend_axi, smc_axi_local_addr_t, smc_cpu_l2_frontend_axi_id_t,
                   smc_axi_data_t, smc_axi_strb_t, smc_axi_user_t)

  // AXI-Lite Typedefs
  typedef logic [AxiAddrWidth-1:0] smc_axi_lite_56_addr_t;
  typedef logic [SmcLocalAddrWidth-1:0] smc_axi_lite_32_addr_t;
  typedef logic [AxiLite64DataWidth-1:0] smc_axi_lite_64_data_t;
  typedef logic [AxiLite32DataWidth-1:0] smc_axi_lite_32_data_t;
  typedef logic [AxiLite64DataWidth/8-1:0] smc_axi_lite_64_strb_t;
  typedef logic [AxiLite32DataWidth/8-1:0] smc_axi_lite_32_strb_t;
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

  localparam int unsigned NumApbTargets = 1;

  localparam int unsigned CpuDebugApbAddrWidth = 32;
  localparam int unsigned CpuDebugApbDataWidth = 32;
  localparam int unsigned CpuDebugApbStrbWidth = CpuDebugApbDataWidth / 8;

  typedef logic [CpuDebugApbAddrWidth-1:0] cpu_debug_apb_addr_t;
  typedef logic [CpuDebugApbDataWidth-1:0] cpu_debug_apb_data_t;
  typedef logic [CpuDebugApbStrbWidth-1:0] cpu_debug_apb_strb_t;

  `APB_TYPEDEF_ALL(cpu_debug_apb, cpu_debug_apb_addr_t, cpu_debug_apb_data_t, cpu_debug_apb_strb_t)

  localparam int unsigned SmcDfdApbAddrWidth = 32;
  localparam int unsigned SmcDfdApbDataWidth = 32;
  localparam int unsigned SmcDfdApbStrbWidth = SmcDfdApbDataWidth / 8;

  typedef logic [SmcDfdApbAddrWidth-1:0] smc_dfd_apb_addr_t;
  typedef logic [SmcDfdApbDataWidth-1:0] smc_dfd_apb_data_t;
  typedef logic [SmcDfdApbStrbWidth-1:0] smc_dfd_apb_strb_t;

  `APB_TYPEDEF_ALL(smc_dfd_apb, smc_dfd_apb_addr_t, smc_dfd_apb_data_t, smc_dfd_apb_strb_t)

  ////////////////////////////////////////
  // Transaction and Timeout Parameters //
  ////////////////////////////////////////

  // PER AXI ID BUCKET, for axi_demux.MaxTrans
  localparam int unsigned FabricMaxTrans = 32;
  // For axi_demux.AxiLookBits
  localparam int unsigned FabricIdLookupBits = 3;
  // ALL IDs, PER DIRECTION, for passive monitors (prim_axi_snoop via axi_cg_snoop, axi_hang_detector)
  localparam int unsigned FabricIdBuckets = 2 ** FabricIdLookupBits;
  localparam int unsigned FabricOutstandingTx = FabricIdBuckets * FabricMaxTrans;
  // ALL IDs, to be used with axi_err_slv
  localparam int unsigned ErrSlvMaxTrans = 32;

  // Unique-ID table depth for axi_id_remap (prim_axi_id_converter)
  localparam int unsigned MaxInflightIds = 4;
  localparam int unsigned TimeoutCountW = 48;  // 48 bits is enough for 78 hours at refclk.

  ////////////////////////////////////
  // Alias Remap Parameters + Types //
  ////////////////////////////////////

  localparam int unsigned InputFabricNumRegMaps = 3;
  localparam int unsigned NumAliasRemapInputs = 4;

  localparam int unsigned NumChunksAliasRemapCarrySelectAdder = 5;  // 56-12+1 = 45, 45/5 = 9.

  typedef struct packed {
    logic [2:0] aw_remap_hit_debug;
    logic [2:0] ar_remap_hit_debug;
  } remap_debug_t;

  typedef struct packed {
    logic [AxiAddrWidth-1:0] region_start;
    logic [AxiAddrWidth-1:0] region_end;
    logic [AxiAddrWidth-1:0] offset;
    axi_pkg::cache_t cacheable;
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

  localparam int unsigned OutputRemapIdxStart = 20;

  localparam int unsigned NumMmodeOutputRemapRegions = 8;
  localparam int unsigned MmodeRemapSelW = $clog2(NumMmodeOutputRemapRegions);
  localparam int unsigned NumXvisorOutputRemapRegions = 8;
  localparam int unsigned XvisorRemapSelW = $clog2(NumXvisorOutputRemapRegions);
  localparam int unsigned NumAliasRemapRegions = 8;
  localparam int unsigned AliasRemapSelW = $clog2(NumAliasRemapRegions);
  localparam int unsigned AliasRemapIdxStart = 12;
  localparam int unsigned AliasRemapOffsetWidth = AxiAddrWidth - AliasRemapIdxStart;

  localparam int unsigned NumOutputRemaps = 3;

  localparam longint unsigned MmodeRemapBaseAddr = 64'h100_0000;
  localparam longint unsigned XvisorRemapBaseAddr = 64'h180_0000;

  // External Interface Parameters
  localparam int unsigned NumExtInterfaces = 12;
  localparam int unsigned ExtRegAddrWidth = 32;
  localparam int unsigned ExtRegDataWidth = 32;
  localparam int unsigned ExtRegStrbWidth = ExtRegDataWidth / 8;
  typedef logic [ExtRegAddrWidth-1:0] ext_reg_addr_t;
  typedef logic [ExtRegDataWidth-1:0] ext_reg_data_t;
  typedef logic [ExtRegStrbWidth-1:0] ext_reg_strb_t;

  // Source ID Parameters
  localparam smc_axi_user_t OthersSrcId = smc_axi_user_t'(0);
  localparam smc_axi_user_t SmcSrcId = smc_axi_user_t'(3);
  localparam smc_axi_user_t MmodeSrcId = smc_axi_user_t'('hC);
  localparam smc_axi_user_t SepSrcId = smc_axi_user_t'('hF);

  // Address Remap Parameters
  // The remap starts are offsets into the SMC register window, since the fabric adds them to a
  // runtime window base. SMC_TOP_BASE_ADDR is the addrmap root (0), not the window base, so the
  // window base is taken from the lowest-addressed block in the window instead.
  localparam smc_axi_addr_t RegWindowBase      = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_SMC_CLUSTER_CORE0_WDT_BASE_ADDR);
  localparam smc_axi_addr_t MmodeRemapStart    = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_BASE_ADDR) - RegWindowBase;
  localparam smc_axi_addr_t MmodeRemapSize     = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_MMODE_REGION_SIZE);
  localparam smc_axi_addr_t XvisorRemapStart   = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_BASE_ADDR) - RegWindowBase;
  localparam smc_axi_addr_t XvisorRemapSize    = smc_axi_addr_t'(smc_top_addrmap_pkg::SMC_TOP_XVISOR_REGION_SIZE);

  // Filter Parameters
  localparam int unsigned NumOutboundFilters = 16;
  localparam int unsigned NumInboundFilters = 16;

  /////////////////////
  // Misc Parameters //
  /////////////////////

  localparam int unsigned LcStateWidth = 4;
  localparam int unsigned NumMailboxes = 32;
  localparam int unsigned MailboxDepth = 2;

  /////////////////////////////////////
  // Data Accelerator Parameters     //
  /////////////////////////////////////

  localparam int unsigned F2mFifoDepth = 4;
  localparam int unsigned M2bFifoDepth = 0;

  typedef enum logic {
    DMA = 0,
    ZEROER = 1
  } data_accelerator_type_e;

  // DMA backend internal ID width (for axi_mux inside DMA backend)
  localparam int unsigned DmaBackendMstIdW = SmcInputFabricSlaveIdWidth - 2;  // 2.

  // DMA control interface (9-bit addr, reuses 64-bit data / 8-bit ID / 12-bit user)
  localparam int unsigned DmaCtrlAddrW = 9;
  typedef logic [DmaCtrlAddrW-1:0] smc_dma_ctrl_addr_t;
  `AXI_TYPEDEF_ALL(smc_dma_ctrl_9_64_8_12_axi, smc_dma_ctrl_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // Zeroer control interface (5-bit addr matches zeroer_ctrl_reg_pkg::ZEROER_CTRL_REG_MIN_ADDR_WIDTH)
  localparam int unsigned ZeroerCtrlAddrW = 5;
  typedef logic [ZeroerCtrlAddrW-1:0] smc_zeroer_ctrl_addr_t;
  `AXI_LITE_TYPEDEF_ALL(smc_zeroer_ctrl_axil_5_64, smc_zeroer_ctrl_addr_t, smc_axi_data_t,
                        smc_axi_strb_t)
  `AXI_TYPEDEF_ALL(smc_zeroer_ctrl_5_64_8_12_axi, smc_zeroer_ctrl_addr_t,
                   smc_local_fabric_xbar_master_id_t, smc_axi_data_t, smc_axi_strb_t,
                   smc_axi_user_t)

  // AXI data size for byte-lane calculations
  localparam int unsigned AxiDataSize = $clog2(AxiStrbWidth);  // 3.

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
  localparam int unsigned CgHysteresisW = 6;
  typedef logic [CgHysteresisW-1:0] cg_hyster_t;

  // CPU Specific Parameters
  localparam int unsigned DbgAddrW = 12;  // smc_4core_cpu_pkg.
  localparam int unsigned DbgDataW = 32;  // smc_4core_cpu_pkg.
  localparam int unsigned DbgStrbW = DbgDataW / 8;  // smc_4core_cpu_pkg.


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
