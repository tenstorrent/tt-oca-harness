// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SMC IP Integration -- 3rd party IP, macros, and shims
//
// Open-source reference models for the technology-specific IP SMC exposes
// at this boundary: the shared eFuse bank/shim model (IsSmcInstance=1), the
// PLL/PVT AXI-Lite models (pll_wrap.sv / pvt_wrap.sv), and one
// prim_pad_shim.sv instance per GPIO pin standing in for the physical
// padring. The GPIO-shim per-pin CSR and adopter peripheral extension
// AXI-Lite buses are terminated with prim_axi_lite_err_slv (DECERR).
//
// smc_wrapper.sv instantiates this module alongside the bare smc.sv core
// and wires the two together (smu_wrapper.sv does the same directly
// against smu.sv's own re-exposed hook points). See the integrator guide
// (doc/integrator/modules/ROOT/pages/index.adoc, "Module Variants and IP
// Integration") and hw/top/README.md.
//
// The Chipyard CPU ROM/scratch/L1$ macros and the trace sink RAM banks live
// here too, so both wrappers pick them up from the one module they already
// instantiate.
//
// Every other technology-specific interface smc.sv exposes (I3C DAT/DCT
// memory macros, ATB telemetry, SPI-over-GPIO muxing, etc.) is passed
// straight through by smc_wrapper.sv, left for a full-chip integration to
// wire up.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module smc_ip_integration (
    input logic clk_smc_i,
    input logic rst_primary_smc_clk_ni,

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
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
    output chipyard_4core_mem_pkg::scratch_ram_rsp_t    scratch_ram_intf_rsp
        [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0],
    input  chipyard_4core_mem_pkg::l1_icache_tag_req_t  l1_icache_tag_intf_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
    output chipyard_4core_mem_pkg::l1_icache_tag_rsp_t  l1_icache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0],
    input  chipyard_4core_mem_pkg::l1_icache_data_req_t l1_icache_data_intf_req
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
    output chipyard_4core_mem_pkg::l1_icache_data_rsp_t l1_icache_data_intf_rsp
        [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0],
    input  chipyard_4core_mem_pkg::l1_dcache_tag_req_t  l1_dcache_tag_intf_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
    output chipyard_4core_mem_pkg::l1_dcache_tag_rsp_t  l1_dcache_tag_intf_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0],
    input  chipyard_4core_mem_pkg::l1_dcache_data_req_t l1_dcache_data_intf_req
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],
    output chipyard_4core_mem_pkg::l1_dcache_data_rsp_t l1_dcache_data_intf_rsp
        [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0],

    // Trace sink memory macros (from smc.sv's trace network)
    input  trace_mem_pkg::SinkMemPktIn_s  [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_req,
    output trace_mem_pkg::SinkMemPktOut_s [tn_pkg::TRC_RAM_INSTANCES-1:0] trace_mem_resp,

    // GPIO pad-facing signals (from smc.sv's padring)
    output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_o,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en_i,

    // Physical GPIO pad bus, one prim_pad_shim.sv instance per pin
    inout wire [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_pad_io,

    // eFuse debug bus (internal shim state, surfaced for DV visibility)
    output logic [15:0] efuse_debug_bus_o
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    smc_pkg::smc_efuse_apb_req_t  efuse_model_otp_req;
    smc_pkg::smc_efuse_apb_resp_t efuse_model_otp_resp;

    /////////////////////
    // eFuse SHIM      //
    /////////////////////

    efuse_interface_shim #(
        .SHADOW_REG_BITS      (smc_efuse_pkg::SHADOW_REG_BITS),
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
        .clk_i  (clk_smc_i),
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
        .NumFuseByteWidth (smc_efuse_pkg::NumFuseByteWidth),
        .IsSmcInstance    (1'b1),
        .efuse_apb_req_t  (smc_pkg::smc_efuse_apb_req_t),
        .efuse_apb_resp_t (smc_pkg::smc_efuse_apb_resp_t)
    ) u_efuse_bank_model (
        .clk_i  (clk_smc_i),
        .rst_ni (rst_primary_smc_clk_ni),

        .apb_req_i  (efuse_model_otp_req),
        .apb_resp_o (efuse_model_otp_resp),

        .hwif_out ()
    );

    //=========================================================================
    // External-window demux
    //
    // smc.sv presents the adopter blocks as a single AXI-Lite window; the map
    // inside it is the adopter contract, so the decode lives here where a
    // vendor integration replaces it wholesale. Offsets are relative to the
    // window base and follow the smc_external mandatory map.
    //=========================================================================

    // The vendor eFuse shim CSR occupies the base of the window, so everything
    // else sits 0x1000 up from it. The shim is not decoded here: the peripheral
    // crossbar diverts it to the eFuse controller before the external port.
    localparam int unsigned ExtGpioCtrlBase   = 'h1100;
    localparam int unsigned ExtGpioCtrlStride = 'h0020;
    localparam int unsigned ExtGpioCtrlNum    = 65;
    localparam int unsigned ExtPllBase        = 'h2000;
    localparam int unsigned ExtPvtBase        = 'h3000;
    localparam int unsigned ExtWindowSize     = 'h4000;

    // Targets, in demux port order. Anything unclaimed lands on ExtUnmapped,
    // which answers DECERR.
    localparam int unsigned ExtPll      = 0;
    localparam int unsigned ExtPvt      = 1;
    localparam int unsigned ExtGpioCtrl = 2;
    localparam int unsigned ExtUnmapped = 3;
    localparam int unsigned ExtNumPorts = 4;

    smc_pkg::smc_axil_32_32_req_t  [ExtNumPorts-1:0] ext_req;
    smc_pkg::smc_axil_32_32_resp_t [ExtNumPorts-1:0] ext_resp;
    logic [$clog2(ExtNumPorts)-1:0] ext_aw_select, ext_ar_select;

    function automatic logic [$clog2(ExtNumPorts)-1:0] ext_decode(
        input logic [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] addr
    );
        automatic logic [smc_pkg::SMC_LOCAL_ADDR_WIDTH-1:0] off = addr % ExtWindowSize;
        if (off >= ExtPvtBase)                              return ExtUnmapped;
        else if (off >= ExtPllBase + pll_wrap_addrmap_pkg::PLL_WRAP_SIZE) return ExtUnmapped;
        else if (off >= ExtPllBase)                         return ExtPll;
        else if (off >= ExtGpioCtrlBase + ExtGpioCtrlNum * ExtGpioCtrlStride) return ExtUnmapped;
        else if (off >= ExtGpioCtrlBase)                    return ExtGpioCtrl;
        else                                                return ExtUnmapped;
    endfunction

    always_comb begin
        ext_aw_select = ext_decode(smc_external_req_i.aw.addr);
        ext_ar_select = ext_decode(smc_external_req_i.ar.addr);
        // The PVT window sits above the PLL one; fold it in separately so the
        // chain above stays a simple descending compare.
        if (smc_external_req_i.aw.addr % ExtWindowSize >= ExtPvtBase &&
            smc_external_req_i.aw.addr % ExtWindowSize <
                ExtPvtBase + pvt_wrap_addrmap_pkg::PVT_WRAP_SIZE) begin
            ext_aw_select = ExtPvt;
        end
        if (smc_external_req_i.ar.addr % ExtWindowSize >= ExtPvtBase &&
            smc_external_req_i.ar.addr % ExtWindowSize <
                ExtPvtBase + pvt_wrap_addrmap_pkg::PVT_WRAP_SIZE) begin
            ext_ar_select = ExtPvt;
        end
    end

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
        .clk_i           (clk_smc_i),
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
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtPll]),
        .axil_resp_o(ext_resp[ExtPll])
    );

    ///////////////
    // PVT Model //
    ///////////////

    pvt_wrap u_pvt_wrap (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtPvt]),
        .axil_resp_o(ext_resp[ExtPvt])
    );

    //////////////////////////////////
    // Memory (SRAM + ROM + Caches) //
    //////////////////////////////////

    // Chipyard CPU ROM / scratch / L1$ macros, via the same prim_rom /
    // prim_ram_1p set as SEP. Unused cfg pins match the mem_swaps defaults.
    localparam int unsigned MEM_CFG_WIDTH = 11;

    logic [MEM_CFG_WIDTH-1:0] scratch_ram_cfg [chipyard_4core_mem_pkg::NUM_SRAM_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] icache_tag_cfg  [chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] icache_data_cfg [chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] dcache_tag_cfg  [chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] dcache_data_cfg [chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS-1:0];
    logic [MEM_CFG_WIDTH-1:0] rom_cfg;

    for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_SRAM_BANKS; i++) begin : gen_scratch_cfg
        assign scratch_ram_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_ICACHE_TAG_BANKS; i++) begin : gen_itag_cfg
        assign icache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_ICACHE_DATA_BANKS; i++) begin : gen_idata_cfg
        assign icache_data_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_DCACHE_TAG_BANKS; i++) begin : gen_dtag_cfg
        assign dcache_tag_cfg[i] = '0;
    end
    for (genvar i = 0; i < chipyard_4core_mem_pkg::NUM_DCACHE_DATA_BANKS; i++) begin : gen_ddata_cfg
        assign dcache_data_cfg[i] = '0;
    end
    assign rom_cfg = '0;

    OCAH4CORECluster_mems #(
        .MEM_CFG_WIDTH (MEM_CFG_WIDTH)
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
            .clk_i     (clk_smc_i),
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
    localparam gpio_shim_pkg::gpio_model_ctrl_t GPIO_CTRL_DEFAULT = '{
        gpio_drive_strength      : 3'b010,
        gpio_pull_en              : 1'b0,
        gpio_pull_sel             : 1'b0,
        gpio_sps                  : 1'b0,
        gpio_glitch_filter_enable : 1'b1
    };

    for (genvar i = 0; i < smc_pkg::NUM_GPIO_WRAPS; i++) begin : gen_gpio_pad
        prim_pad_shim #(
            .InputOnly (1'b0)
        ) u_prim_pad_shim (
            .core2pad_i          (core2pad_i[i]),
            .core2pad_en_i       (core2pad_en_i[i]),
            .pad2core_o          (pad2core_o[i]),
            .pad2core_en_i       (pad2core_en_i[i]),
            .gpio_ctrl_i         (GPIO_CTRL_DEFAULT),
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
        .AXI_ADDR_WIDTH (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
        .AXI_DATA_WIDTH (smc_pkg::AXI_LITE_32_DATA_WIDTH),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (smc_pkg::AXI_LITE_32_DATA_WIDTH),
        .RESP_DATA      ('0),
        .MAX_TRANS      (2)
    ) u_gpio_ctrl_err_slv (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtGpioCtrl]),
        .axil_resp_o(ext_resp[ExtGpioCtrl])
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (smc_pkg::SMC_LOCAL_ADDR_WIDTH),
        .AXI_DATA_WIDTH (smc_pkg::AXI_LITE_32_DATA_WIDTH),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (smc_pkg::AXI_LITE_32_DATA_WIDTH),
        .RESP_DATA      ('0),
        .MAX_TRANS      (2)
    ) u_ext_unmapped_err_slv (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (ext_req[ExtUnmapped]),
        .axil_resp_o(ext_resp[ExtUnmapped])
    );

endmodule
