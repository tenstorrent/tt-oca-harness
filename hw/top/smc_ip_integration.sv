// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC IP Integration -- 3rd party IP, macros, and shims
//
// Open-source reference models for the technology-specific IP SMC exposes
// at this boundary: the shared eFuse bank/shim model (IS_SMC_INSTANCE=1), the
// PLL/PVT AXI-Lite models (pll_wrap.sv / pvt_wrap.sv). pll_wrap is the
// clock source the wrappers fan out to smc.sv / smu.sv. Also modeled here:
// the I3C DAT/DCT/RLT table memories, and one prim_pad_shim.sv instance per
// GPIO pin standing in for the physical padring. The GPIO-shim per-pin CSR
// and adopter peripheral extension AXI-Lite buses are terminated with
// prim_axi_lite_err_slv (DECERR).
//
// smc_wrapper.sv instantiates this module alongside the bare smc.sv core
// and wires the two together (smu_wrapper.sv does the same directly
// against smu.sv's own re-exposed hook points). See the integrator guide
// (doc/integrator/modules/ROOT/pages/index.adoc, "Module Variants and IP
// Integration") and hw/top/README.md.
//
// The I3C table memories live here because smc.sv and smu.sv export the same
// macro interfaces, so both wrappers need the same reference integration.
// The Chipyard CPU ROM/scratch/L1$ macros and the trace sink RAM banks live
// here too, so both wrappers pick them up from the one module they already
// instantiate.
//
// Every other technology-specific interface smc.sv exposes (ATB telemetry,
// SPI-over-GPIO muxing, etc.) is passed straight through by
// smc_wrapper.sv, left for a full-chip integration to wire up.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module smc_ip_integration (
    output logic clk_ref_o,
    output logic clk_sys_o,
    output logic clk_periph_o,
    input  logic rst_primary_smc_clk_ni,

    // The I3C table memories are the one block here that does not run on
    // clk_smc: the core drives them from the gated I3C peripheral clock.
    input logic gated_clk_periph_i3c_i,
    input logic rst_primary_periph_clk_ni,

    // Adopter external window (from smc.sv). One AXI-Lite port carrying the
    // whole smc_external map; the blocks behind it are decoded below.
    input  smc_pkg::smc_axil_32_32_req_t  smc_external_req_i,
    output smc_pkg::smc_axil_32_32_resp_t smc_external_resp_o,

    // Test/DFT passthrough (used by the external-window demux)
    input  logic test_en_i,

    // Efuse interfaces (from smc.sv)
    input  smc_pkg::smc_axil_32_32_req_t      efuse_bank_ctrl_req_i,
    output smc_pkg::smc_axil_32_32_resp_t     efuse_bank_ctrl_resp_o,
    input  smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req_i,
    output smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp_o,

    // CPU memory interfaces from SMC (ROM / scratch / L1$ macros below)
    input  chipyard_4core_mem_pkg::rom_req_t            rom_intf_req,
    output chipyard_4core_mem_pkg::rom_rsp_t            rom_intf_rsp,
    input  chipyard_4core_mem_pkg::scratch_ram_req_t    scratch_ram_intf_req
        [chipyard_4core_mem_pkg::NumSramBanks-1:0],
    output chipyard_4core_mem_pkg::scratch_ram_rsp_t    scratch_ram_intf_rsp
        [chipyard_4core_mem_pkg::NumSramBanks-1:0],
    input  chipyard_4core_mem_pkg::l1_icache_tag_req_t  l1_icache_tag_intf_req
        [chipyard_4core_mem_pkg::NumIcacheTagBanks-1:0],
    output chipyard_4core_mem_pkg::l1_icache_tag_rsp_t  l1_icache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NumIcacheTagBanks-1:0],
    input  chipyard_4core_mem_pkg::l1_icache_data_req_t l1_icache_data_intf_req
        [chipyard_4core_mem_pkg::NumIcacheDataBanks-1:0],
    output chipyard_4core_mem_pkg::l1_icache_data_rsp_t l1_icache_data_intf_rsp
        [chipyard_4core_mem_pkg::NumIcacheDataBanks-1:0],
    input  chipyard_4core_mem_pkg::l1_dcache_tag_req_t  l1_dcache_tag_intf_req
        [chipyard_4core_mem_pkg::NumDcacheTagBanks-1:0],
    output chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t  l1_dcache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NumDcacheTagBanks-1:0],
    input  chipyard_4core_mem_pkg::l1_dcache_data_req_t l1_dcache_data_intf_req
        [chipyard_4core_mem_pkg::NumDcacheDataBanks-1:0],
    output chipyard_4core_mem_pkg::l1_dcache_data_rsp_t l1_dcache_data_intf_rsp
        [chipyard_4core_mem_pkg::NumDcacheDataBanks-1:0],

    // Trace sink memory macros (from smc.sv's trace network)
    input  trace_mem_pkg::SinkMemPktIn_s  [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_req,
    output trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp,

    // GPIO pad-facing signals (from smc.sv's padring)
    output logic [smc_pkg::NumGpioWraps-1:0] pad2core_o,
    input  logic [smc_pkg::NumGpioWraps-1:0] core2pad_i,
    input  logic [smc_pkg::NumGpioWraps-1:0] pad2core_en_i,
    input  logic [smc_pkg::NumGpioWraps-1:0] core2pad_en_i,

    // Physical GPIO pad bus, one prim_pad_shim.sv instance per pin
    inout wire [smc_pkg::NumGpioWraps-1:0] gpio_pad_io,

    // I3C table memory macro interfaces (from smc.sv / smu.sv)
    input  i3c_pkg::dat_mem_sink_t [smc_config_pkg::NumI3c-1:0] i3c_dat_mem_sink_i,
    output i3c_pkg::dat_mem_src_t  [smc_config_pkg::NumI3c-1:0] i3c_dat_mem_src_o,
    input  i3c_pkg::dct_mem_sink_t [smc_config_pkg::NumI3c-1:0] i3c_dct_mem_sink_i,
    output i3c_pkg::dct_mem_src_t  [smc_config_pkg::NumI3c-1:0] i3c_dct_mem_src_o,
    input  i3c_pkg::rlt_mem_sink_t [smc_config_pkg::NumI3c-1:0] i3c_rlt_mem_sink_i,
    output i3c_pkg::rlt_mem_src_t  [smc_config_pkg::NumI3c-1:0] i3c_rlt_mem_src_o,

    // eFuse debug bus (internal shim state, surfaced for DV visibility)
    output logic [15:0] efuse_debug_bus_o
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    logic clk_ref;
    logic clk_sys;
    logic clk_periph;

    smc_pkg::smc_efuse_apb_req_t  efuse_model_otp_req;
    smc_pkg::smc_efuse_apb_resp_t efuse_model_otp_resp;

    /////////////////////
    // eFuse SHIM      //
    /////////////////////

    efuse_interface_shim #(
        .SHADOW_REG_BITS      (smc_efuse_pkg::ShadowRegBits),
        .addr_t               (smc_pkg::smc_axi_lite_32_addr_t),
        .data_t               (smc_pkg::smc_axi_lite_32_data_t),
        .efuse_axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .efuse_axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .efuse_apb_req_t      (smc_pkg::smc_efuse_apb_req_t),
        .efuse_apb_resp_t     (smc_pkg::smc_efuse_apb_resp_t),
        .efuse_addr_byte_t    (smc_efuse_pkg::efuse_addr_byte_t),
        .efuse_data_t         (smc_efuse_pkg::efuse_data_t),
        .efuse_word_counter_t (smc_efuse_pkg::efuse_word_counter_t),
        .fuse_command_req_t   (smc_efuse_pkg::fuse_command_req_t),
        .fuse_command_resp_t  (smc_efuse_pkg::fuse_command_resp_t)
    ) u_efuse_interface_shim (
        .clk_i  (clk_sys),
        .rst_ni (rst_primary_smc_clk_ni),

        .fuse_bank_ctrl_req_i  (efuse_bank_ctrl_req_i),
        .fuse_bank_ctrl_resp_o (efuse_bank_ctrl_resp_o),

        .fuse_command_req_i  (efuse_shim_command_req_i),
        .fuse_command_resp_o (efuse_shim_command_resp_o),

        .efuse_model_otp_req_o  (efuse_model_otp_req),
        .efuse_model_otp_resp_i (efuse_model_otp_resp),

        .debug_bus_o (efuse_debug_bus_o)
    );

    efuse_bank_model #(
        .NUM_FUSE_BYTE_WIDTH (smc_efuse_pkg::NumFuseByteWidth),
        .IS_SMC_INSTANCE     (1'b1),
        .efuse_apb_req_t     (smc_pkg::smc_efuse_apb_req_t),
        .efuse_apb_resp_t    (smc_pkg::smc_efuse_apb_resp_t)
    ) u_efuse_bank_model (
        .clk_i  (clk_sys),
        .rst_ni (rst_primary_smc_clk_ni),

        .apb_req_i  (efuse_model_otp_req),
        .apb_resp_o (efuse_model_otp_resp),

        .hwif_out_o ()
    );

    //=========================================================================
    // External-window demux
    //
    // smc.sv presents the adopter blocks as a single AXI-Lite window; the map
    // inside it is the adopter contract, so the decode lives here where a
    // vendor integration replaces it wholesale. Offsets are relative to the
    // window base and come from the generated smc_external map.
    //=========================================================================

    // The vendor eFuse shim CSR occupies the base of the window. The shim is not
    // decoded here: the peripheral crossbar diverts it to the eFuse controller
    // before the external port.
    localparam longint unsigned ExtBase = smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_BASE_ADDR;
    localparam int unsigned ExtGpioCtrlBase = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_BASE_ADDR(0) - ExtBase);
    localparam int unsigned ExtGpioCtrlSize = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_GPIO_CTRL_TOTAL_SIZE);
    localparam int unsigned ExtPllBase = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_BASE_ADDR - ExtBase);
    localparam int unsigned ExtPllSize = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_SMC_PLL_WRAP_SIZE);
    localparam int unsigned ExtPvtBase = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_BASE_ADDR - ExtBase);
    localparam int unsigned ExtPvtSize = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_SUPPLEMENTARY_SMC_PVT_WRAP_SIZE);
    localparam int unsigned ExtStrapsBase = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_BASE_ADDR - ExtBase);
    localparam int unsigned ExtStrapsSize = 32'(
        smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_MANDATORY_STRAPS_SIZE);
    localparam int unsigned ExtWindowSize = 32'(smc_top_addrmap_pkg::SMC_TOP_SMC_EXTERNAL_SIZE);

    // Targets, in demux port order. Anything unclaimed lands on ExtUnmapped,
    // which answers DECERR.
    localparam int unsigned ExtPll      = 0;
    localparam int unsigned ExtPvt      = 1;
    localparam int unsigned ExtGpioCtrl = 2;
    localparam int unsigned ExtStraps   = 3;
    localparam int unsigned ExtUnmapped = 4;
    localparam int unsigned ExtNumPorts = 5;

    smc_pkg::smc_axil_32_32_req_t  [ExtNumPorts-1:0] ext_req;
    smc_pkg::smc_axil_32_32_resp_t [ExtNumPorts-1:0] ext_resp;
    logic [$clog2(ExtNumPorts)-1:0] ext_aw_select, ext_ar_select;

    function automatic logic [$clog2(ExtNumPorts)-1:0] ext_decode(
        input logic [smc_pkg::SmcLocalAddrWidth-1:0] addr
    );
        automatic logic [smc_pkg::SmcLocalAddrWidth-1:0] off = addr % ExtWindowSize;
        if (off >= ExtStrapsBase && off < ExtStrapsBase + ExtStrapsSize)          return ExtStraps;
        else if (off >= ExtPvtBase && off < ExtPvtBase + ExtPvtSize)                return ExtPvt;
        else if (off >= ExtPllBase && off < ExtPllBase + ExtPllSize)                return ExtPll;
        else if (off >= ExtGpioCtrlBase && off < ExtGpioCtrlBase + ExtGpioCtrlSize) return ExtGpioCtrl;
        else                                                                        return ExtUnmapped;
    endfunction

    assign ext_aw_select = ext_decode(smc_external_req_i.aw.addr);
    assign ext_ar_select = ext_decode(smc_external_req_i.ar.addr);

    axi_lite_demux #(
        .aw_chan_t   (smc_pkg::smc_axil_32_32_aw_chan_t),
        .w_chan_t    (smc_pkg::smc_axil_32_32_w_chan_t),
        .b_chan_t    (smc_pkg::smc_axil_32_32_b_chan_t),
        .ar_chan_t   (smc_pkg::smc_axil_32_32_ar_chan_t),
        .r_chan_t    (smc_pkg::smc_axil_32_32_r_chan_t),
        .axi_req_t   (smc_pkg::smc_axil_32_32_req_t),
        .axi_resp_t  (smc_pkg::smc_axil_32_32_resp_t),
        .NoMstPorts  (ExtNumPorts),
        .MaxTrans    (1),
        .FallThrough (1'b0),
        .SpillAw     (1'b1),
        .SpillW      (1'b0),
        .SpillB      (1'b0),
        .SpillAr     (1'b1),
        .SpillR      (1'b0)
    ) u_smc_external_demux (
        .clk_i           (clk_sys_o),
        .rst_ni          (rst_primary_smc_clk_ni),
        .test_i          (test_en_i),
        .slv_req_i       (smc_external_req_i),
        .slv_resp_o      (smc_external_resp_o),
        .slv_aw_select_i (ext_aw_select),
        .slv_ar_select_i (ext_ar_select),
        .mst_reqs_o      (ext_req),
        .mst_resps_i     (ext_resp)
    );

    ///////////////
    // PLL Model //
    ///////////////

    pll_wrap u_pll_wrap (
        .clk_i        (clk_sys),
        .rst_ni       (rst_primary_smc_clk_ni),
        .axil_req_i   (ext_req[ExtPll]),
        .axil_resp_o  (ext_resp[ExtPll]),
        .clk_ref_o    (clk_ref),
        .clk_sys_o    (clk_sys),
        .clk_periph_o (clk_periph)
    );

    ///////////////
    // PVT Model //
    ///////////////

    pvt_wrap u_pvt_wrap (
        .clk_i      (clk_sys),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtPvt]),
        .axil_resp_o(ext_resp[ExtPvt])
    );

    //////////////////////////////
    // Captured GPIO straps     //
    //////////////////////////////
    // These rom_straps are intentionally undriven in RTL. They are to be driven/configured in DV/FW (cocotb)

    logic [smc_pkg::NumBondedGpio-1:0] rom_straps;
    assign rom_straps = '0;

    straps_reg_pkg::straps__in_t straps_hwif_in;

    always_comb begin
        straps_hwif_in.STRAPS_LO.straps.next = rom_straps[31:0];
        straps_hwif_in.STRAPS_HI.straps.next = rom_straps[smc_pkg::NumBondedGpio-1:32];
    end

    straps_reg u_straps_reg (
        .clk    (clk_sys),
        .arst_n (rst_primary_smc_clk_ni),

        .s_axil_awvalid (ext_req[ExtStraps].aw_valid),
        .s_axil_awaddr  (ext_req[ExtStraps].aw.addr[straps_reg_pkg::STRAPS_REG_MIN_ADDR_WIDTH-1:0]),
        .s_axil_awprot  (ext_req[ExtStraps].aw.prot),
        .s_axil_wvalid  (ext_req[ExtStraps].w_valid),
        .s_axil_wdata   (ext_req[ExtStraps].w.data),
        .s_axil_wstrb   (ext_req[ExtStraps].w.strb),
        .s_axil_bready  (ext_req[ExtStraps].b_ready),
        .s_axil_arvalid (ext_req[ExtStraps].ar_valid),
        .s_axil_araddr  (ext_req[ExtStraps].ar.addr[straps_reg_pkg::STRAPS_REG_MIN_ADDR_WIDTH-1:0]),
        .s_axil_arprot  (ext_req[ExtStraps].ar.prot),
        .s_axil_rready  (ext_req[ExtStraps].r_ready),

        .s_axil_awready (ext_resp[ExtStraps].aw_ready),
        .s_axil_wready  (ext_resp[ExtStraps].w_ready),
        .s_axil_bvalid  (ext_resp[ExtStraps].b_valid),
        .s_axil_bresp   (ext_resp[ExtStraps].b.resp),
        .s_axil_arready (ext_resp[ExtStraps].ar_ready),
        .s_axil_rvalid  (ext_resp[ExtStraps].r_valid),
        .s_axil_rdata   (ext_resp[ExtStraps].r.data),
        .s_axil_rresp   (ext_resp[ExtStraps].r.resp),

        .hwif_in        (straps_hwif_in)
    );

    //////////////////////////////////
    // Memory (SRAM + ROM + Caches) //
    //////////////////////////////////

    // Chipyard CPU ROM / scratch / L1$ macros, via the same prim_rom /
    // prim_ram_1p set as SEP. Unused cfg pins match the mem_swaps defaults.
    localparam int unsigned MemCfgWidth = 11;

    logic [MemCfgWidth-1:0] scratch_ram_cfg [chipyard_4core_mem_pkg::NumSramBanks-1:0];
    logic [MemCfgWidth-1:0] icache_tag_cfg  [chipyard_4core_mem_pkg::NumIcacheTagBanks-1:0];
    logic [MemCfgWidth-1:0] icache_data_cfg [chipyard_4core_mem_pkg::NumIcacheDataBanks-1:0];
    logic [MemCfgWidth-1:0] dcache_tag_cfg  [chipyard_4core_mem_pkg::NumDcacheTagBanks-1:0];
    logic [MemCfgWidth-1:0] dcache_data_cfg [chipyard_4core_mem_pkg::NumDcacheDataBanks-1:0];
    logic [MemCfgWidth-1:0] rom_cfg;

    for (genvar i = 0; i < chipyard_4core_mem_pkg::NumSramBanks; i++) begin : gen_scratch_cfg
        assign scratch_ram_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NumIcacheTagBanks; i++) begin : gen_itag_cfg
        assign icache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NumIcacheDataBanks; i++) begin : gen_idata_cfg
        assign icache_data_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NumDcacheTagBanks; i++) begin : gen_dtag_cfg
        assign dcache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NumDcacheDataBanks; i++) begin : gen_ddata_cfg
        assign dcache_data_cfg[i] = '0;
    end
    assign rom_cfg = '0;

    OCAH4CORECluster_mems #(
        .MEM_CFG_WIDTH (MemCfgWidth)
    ) u_mems (
        // Memory interfaces (inputs to mems from DigitalTop)
        .l1_icache_tag_req  (l1_icache_tag_intf_req),
        .l1_icache_tag_rsp  (l1_icache_tag_intf_rsp),
        .l1_icache_data_req (l1_icache_data_intf_req),
        .l1_icache_data_rsp (l1_icache_data_intf_rsp),
        .l1_dcache_tag_req  (l1_dcache_tag_intf_req),
        .l1_dcache_tag_rsp  (l1_dcache_tag_intf_rsp),
        .l1_dcache_data_req (l1_dcache_data_intf_req),
        .l1_dcache_data_rsp (l1_dcache_data_intf_rsp),
        .scratch_ram_req    (scratch_ram_intf_req),
        .scratch_ram_rsp    (scratch_ram_intf_rsp),
        .rom_req            (rom_intf_req),
        .rom_rsp            (rom_intf_rsp),

        // Memory configuration
        .icache_tag_cfg_i  (icache_tag_cfg),
        .icache_data_cfg_i (icache_data_cfg),
        .dcache_tag_cfg_i  (dcache_tag_cfg),
        .dcache_data_cfg_i (dcache_data_cfg),
        .scratch_ram_cfg_i (scratch_ram_cfg),
        .rom_cfg_i         (rom_cfg)
    );

    /////////////////////////
    // Trace Sink Memories //
    /////////////////////////

    // One single-port macro per trace sink bank. Depth/width come from the
    // packet structs so they cannot drift from what smc.sv's trace network
    // drives.
    localparam int unsigned TraceMemBankDepth = trace_mem_pkg::TRC_RAM_INDEX;
    localparam int unsigned TraceMemBankWidth = tn_pkg::TRC_RAM_DATA_WIDTH;

    for (genvar i = 0; i < tn_pkg::TRC_RAM_INSTANCES; i++) begin : gen_trace_mem_bank
        logic [TraceMemBankWidth-1:0] macro_rdata;

        assign trace_mem_resp[i].mem_rd_data = macro_rdata;

        // The sink writes whole words; mem_wr_mask_en is unused, so the macro
        // mask is held all-ones.
        prim_ram_1p_adv #(
            .Depth       (TraceMemBankDepth),
            .Width       (TraceMemBankWidth),
            .MemInitFile ("")
        ) u_trace_mem_bank (
            .clk_i     (clk_sys),
            .rst_ni    (rst_primary_smc_clk_ni),
            .req_i     (trace_mem_req[i].mem_chip_en),
            .write_i   (trace_mem_req[i].mem_wr_en),
            .addr_i    (trace_mem_req[i].mem_wr_addr),
            .wdata_i   (trace_mem_req[i].mem_wr_data),
            .wmask_i   ({TraceMemBankWidth{1'b1}}),
            .rdata_o   (macro_rdata),
            .rvalid_o  (),
            .rerror_o  (),
            .alert_o   (),
            .cfg_i     ('0),
            .cfg_rsp_o ()
        );
    end

    //////////////////////////////
    // GPIO pad primitives     //
    //////////////////////////////

    // Each pad is driven with gpio_shim.sv's own reset-default electrical
    // attributes.
    localparam gpio_shim_pkg::gpio_model_ctrl_t GpioCtrlDefault = '{
        gpio_drive_strength      : 3'b010,
        gpio_pull_en              : 1'b0,
        gpio_pull_sel             : 1'b0,
        gpio_sps                  : 1'b0,
        gpio_glitch_filter_enable : 1'b1
    };

    for (genvar i = 0; i < smc_pkg::NumGpioWraps; i++) begin : gen_gpio_pad
        prim_pad_shim #(
            .INPUT_ONLY (1'b0)
        ) u_prim_pad_shim (
            .core2pad_i          (core2pad_i[i]),
            .core2pad_en_i       (core2pad_en_i[i]),
            .pad2core_o          (pad2core_o[i]),
            .pad2core_en_i       (pad2core_en_i[i]),
            .gpio_ctrl_i         (GpioCtrlDefault),
            .gpio_nandtree_in_i  (1'b0),
            .gpio_nandtree_out_o (),
            .pad_io              (gpio_pad_io[i])
        );
    end

    //=========================================================================
    // GPIO shim CSR + the unclaimed remainder of the external window --
    // terminated with DECERR slaves.
    //=========================================================================

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (smc_pkg::SmcLocalAddrWidth),
        .AXI_DATA_WIDTH (smc_pkg::AxiLite32DataWidth),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (smc_pkg::AxiLite32DataWidth),
        .RESP_DATA      ('0),
        .MAX_TRANS      (2)
    ) u_gpio_ctrl_err_slv (
        .clk_i      (clk_sys),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtGpioCtrl]),
        .axil_resp_o(ext_resp[ExtGpioCtrl])
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (smc_pkg::SmcLocalAddrWidth),
        .AXI_DATA_WIDTH (smc_pkg::AxiLite32DataWidth),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (smc_pkg::AxiLite32DataWidth),
        .RESP_DATA      ('0),
        .MAX_TRANS      (2)
    ) u_ext_unmapped_err_slv (
        .clk_i      (clk_sys),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtUnmapped]),
        .axil_resp_o(ext_resp[ExtUnmapped])
    );

    //=========================================================================
    // I3C DAT/DCT/RLT table memories
    //
    // smc.sv / smu.sv export the I3C controller's three table memories as
    // macro interfaces rather than instantiating them, so an adopter can drop
    // in vendor SRAMs. These are the reference macros, one set per instance:
    //
    //   DAT  Device Address Table            64 b x 2**DatAw, single port
    //   DCT  Device Characteristic Table    128 b x 2**DctAw, single port
    //   RLT  dynamic address -> DAT index    DatAw b x 128,   dual port
    //
    // Sizing and the 32-bit write granularity mirror the I3C core's own
    // bring-up testbench (hw/ip/i3ccore_wrap/dv/tb/tb_i3ccore.sv), which
    // drives the identical interface. The core reads combinationally one cycle
    // after asserting req, which is exactly prim_ram_*'s latency.
    //
    // rvalid/rerror are outputs of the macro interface that the vendored I3C
    // core never reads (only rdata is consumed). They are still driven
    // honestly rather than tied off, so a waveform or a future consumer sees a
    // truthful interface.
    //=========================================================================

    // Address widths are the core's; depths follow from them so the arrays
    // always cover every address the core can present.
    localparam int unsigned DatDepth = 1 << i3c_pkg::DatAw;
    localparam int unsigned DctDepth = 1 << i3c_pkg::DctAw;
    // Fixed by the core: RLT is indexed by the 7-bit dynamic address
    // (vendor/chipsalliance/i3c-core/upstream/src/ctrl/flow_active.sv).
    localparam int unsigned RltDepth = 128;
    localparam int unsigned RltWidth = i3c_pkg::DatAw;

    // CSR writes reach DAT/DCT one 32-bit word at a time, so the macros need
    // 32-bit write granularity (dxt.sv builds {32{1'b1}}/{32{1'b0}} masks).
    localparam int unsigned I3cMaskGranularity = 32;

    for (genvar i = 0; i < smc_config_pkg::NumI3c; i++) begin : gen_i3c_mem

        ///////////
        // DAT   //
        ///////////

        logic dat_rvalid_q;

        prim_ram_1p #(
            .Width           (64),
            .Depth           (DatDepth),
            .DataBitsPerMask (I3cMaskGranularity)
        ) u_dat_mem (
            .clk_i     (gated_clk_periph_i3c_i),
            .rst_ni    (rst_primary_periph_clk_ni),
            .req_i     (i3c_dat_mem_sink_i[i].req),
            .write_i   (i3c_dat_mem_sink_i[i].write),
            .addr_i    (i3c_dat_mem_sink_i[i].addr),
            .wdata_i   (i3c_dat_mem_sink_i[i].wdata),
            .wmask_i   (i3c_dat_mem_sink_i[i].wmask),
            .rdata_o   (i3c_dat_mem_src_o[i].rdata),
            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

        always_ff @(posedge gated_clk_periph_i3c_i or negedge rst_primary_periph_clk_ni) begin
            if (!rst_primary_periph_clk_ni) begin
                dat_rvalid_q <= 1'b0;
            end else begin
                dat_rvalid_q <= i3c_dat_mem_sink_i[i].req & ~i3c_dat_mem_sink_i[i].write;
            end
        end

        assign i3c_dat_mem_src_o[i].rvalid = dat_rvalid_q;
        assign i3c_dat_mem_src_o[i].rerror = '0;

        ///////////
        // DCT   //
        ///////////

        logic dct_rvalid_q;

        prim_ram_1p #(
            .Width           (128),
            .Depth           (DctDepth),
            .DataBitsPerMask (I3cMaskGranularity)
        ) u_dct_mem (
            .clk_i     (gated_clk_periph_i3c_i),
            .rst_ni    (rst_primary_periph_clk_ni),
            .req_i     (i3c_dct_mem_sink_i[i].req),
            .write_i   (i3c_dct_mem_sink_i[i].write),
            .addr_i    (i3c_dct_mem_sink_i[i].addr),
            .wdata_i   (i3c_dct_mem_sink_i[i].wdata),
            .wmask_i   (i3c_dct_mem_sink_i[i].wmask),
            .rdata_o   (i3c_dct_mem_src_o[i].rdata),
            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

        always_ff @(posedge gated_clk_periph_i3c_i or negedge rst_primary_periph_clk_ni) begin
            if (!rst_primary_periph_clk_ni) begin
                dct_rvalid_q <= 1'b0;
            end else begin
                dct_rvalid_q <= i3c_dct_mem_sink_i[i].req & ~i3c_dct_mem_sink_i[i].write;
            end
        end

        assign i3c_dct_mem_src_o[i].rvalid = dct_rvalid_q;
        assign i3c_dct_mem_src_o[i].rerror = '0;

        ///////////
        // RLT   //
        ///////////

        // Port A is write-only (ENTDAA installs dynamic address -> DAT index),
        // port B is read-only (reverse lookup). Both live on the same clock.
        prim_ram_2p #(
            .Width           (RltWidth),
            .Depth           (RltDepth),
            .DataBitsPerMask (1)
        ) u_rlt_mem (
            .clk_a_i   (gated_clk_periph_i3c_i),
            .clk_b_i   (gated_clk_periph_i3c_i),

            .a_req_i   (i3c_rlt_mem_sink_i[i].a_req),
            .a_write_i (i3c_rlt_mem_sink_i[i].a_write),
            .a_addr_i  (i3c_rlt_mem_sink_i[i].a_addr),
            .a_wdata_i (i3c_rlt_mem_sink_i[i].a_wdata),
            .a_wmask_i (i3c_rlt_mem_sink_i[i].a_wmask),
            .a_rdata_o (i3c_rlt_mem_src_o[i].a_rdata),

            .b_req_i   (i3c_rlt_mem_sink_i[i].b_req),
            .b_write_i (i3c_rlt_mem_sink_i[i].b_write),
            .b_addr_i  (i3c_rlt_mem_sink_i[i].b_addr),
            .b_wdata_i (i3c_rlt_mem_sink_i[i].b_wdata),
            .b_wmask_i (i3c_rlt_mem_sink_i[i].b_wmask),
            .b_rdata_o (i3c_rlt_mem_src_o[i].b_rdata),

            .cfg_i     ('0),
            .cfg_rsp_o ()
        );

    end : gen_i3c_mem

    assign clk_ref_o = clk_ref;
    assign clk_sys_o = clk_sys;
    assign clk_periph_o = clk_periph;

endmodule
