// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// SEP IP Integration -- 3rd party IP, macros, and shims
//
// Open-source reference models for sep.sv's technology-specific IP: the
// shared eFuse bank/shim model, OpenTitan generic RAM/ROM primitives for
// the SRAM/ROM/OTBN/Key-Manager memory macros, the OpenTitan-derived TCM
// ICCM/DCCM wrapper, and DECERR slaves terminating the external-TRNG and
// AXI extension windows.
//
// sep_wrapper.sv instantiates this module alongside the bare sep.sv core
// and wires the two together for standalone SEP reference simulation.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module sep_ip_integration
    import sep_pkg::*;
    import sep_crypto_pkg::*;
    import sep_efuse_pkg::*;
    import km_intf_pkg::*;
#(
    parameter int unsigned EXT_TRNG_NUM_AXIS = 2
) (
    input logic clk_i,
    input logic rst_ni,

    // Reset gating the sim-only memory macros, derived by sep_wrapper.sv from
    // sep.sv's reset and WDT-expiry outputs so the memories reinitialize
    // along with the core.
    input logic sep_cpu_reset_n_i,

    // Test/DFT passthrough (used by the AXI extension error slave's test_i)
    input logic test_en_i,

    // SRAM interface (from sep.sv)
    input  sep_sram_req_t sep_sram_req,
    output sep_sram_rsp_t sep_sram_rsp,

    // Boot ROM interface (from sep.sv)
    input  sep_sram_req_t sep_boot_rom_req,
    output sep_sram_rsp_t sep_boot_rom_rsp,

    // TCM interface (from sep.sv)
    input  sep_cpu_tcm_req_t sep_cpu_tcm_req_i,
    output sep_cpu_tcm_rsp_t sep_cpu_tcm_rsp_o,

    // OTBN external SRAM interfaces (from prim_ram_1p_scr_ext inside OTBN,
    // re-exposed at sep.sv's boundary)
    input  sep_crypto_pka_imem_sram_req_t sep_crypto_pka_imem_sram_req,
    output sep_crypto_pka_imem_sram_rsp_t sep_crypto_pka_imem_sram_rsp,
    input  sep_crypto_pka_dmem_sram_req_t sep_crypto_pka_dmem_sram_req,
    output sep_crypto_pka_dmem_sram_rsp_t sep_crypto_pka_dmem_sram_rsp,

    // Key Manager ROM/SRAM memory interfaces (from sep.sv)
    input  km_intf_pkg::km_rom_mem_req_t  km_rom_mem_req_i,
    output km_intf_pkg::km_rom_mem_rsp_t  km_rom_mem_rsp_o,
    input  km_intf_pkg::km_sram_mem_req_t km_sram_mem_req_i,
    output km_intf_pkg::km_sram_mem_rsp_t km_sram_mem_rsp_o,

    // Efuse interfaces (from sep.sv)
    input  sep_efuse_pkg::efuse_axil_req_t     efuse_bank_ctrl_req_i,
    output sep_efuse_pkg::efuse_axil_resp_t    efuse_bank_ctrl_resp_o,
    input  sep_efuse_pkg::fuse_command_req_t   efuse_shim_command_req_i,
    output sep_efuse_pkg::fuse_command_resp_t  efuse_shim_command_resp_o,

    // External TRNG AXI-Lite CSR interface (from sep.sv)
    input  sep_pkg::sep_32_32_axil_req_t  ext_trng_axil_req_i,
    output sep_pkg::sep_32_32_axil_resp_t ext_trng_axil_resp_o,

    // External TRNG AXI-Stream (to sep.sv)
    output ext_trng_axis_req_t ext_trng_axis_req_o [EXT_TRNG_NUM_AXIS-1:0],
    input  ext_trng_axis_rsp_t ext_trng_axis_rsp_i [EXT_TRNG_NUM_AXIS-1:0],

    // External TRNG interrupt and alarm (to sep.sv)
    output logic ext_trng_irq_o,
    output logic ext_trng_alarm_o,

    // AXI4 extension interface (from sep.sv)
    input  sep_pkg::sep_32_64_6_12_axi_req_t  axi_extension_axi_req_i,
    output sep_pkg::sep_32_64_6_12_axi_resp_t axi_extension_axi_resp_o,

    // eFuse debug bus (internal shim state, surfaced for DV visibility)
    output logic [15:0] efuse_debug_bus_o
);

    /////////////////////////
    // Signal Declarations //
    /////////////////////////

    sep_efuse_pkg::efuse_apb_req_t  efuse_model_otp_req;
    sep_efuse_pkg::efuse_apb_resp_t efuse_model_otp_resp;

    /////////////////////
    // eFuse SHIM      //
    /////////////////////

    efuse_interface_shim #(
        .SHADOW_REG_BITS      (sep_efuse_pkg::SHADOW_REG_BITS),
        .addr_t               (sep_efuse_pkg::addr_t),
        .data_t               (sep_efuse_pkg::data_t),
        .efuse_axil_req_t     (sep_efuse_pkg::efuse_axil_req_t),
        .efuse_axil_resp_t    (sep_efuse_pkg::efuse_axil_resp_t),
        .efuse_apb_req_t      (sep_efuse_pkg::efuse_apb_req_t),
        .efuse_apb_resp_t     (sep_efuse_pkg::efuse_apb_resp_t),
        .efuse_addr_byte_t    (sep_efuse_pkg::efuse_addr_byte_t),
        .efuse_data_t         (sep_efuse_pkg::efuse_data_t),
        .efuse_word_counter_t (sep_efuse_pkg::efuse_word_counter_t),
        .fuse_command_req_t   (sep_efuse_pkg::fuse_command_req_t),
        .fuse_command_resp_t  (sep_efuse_pkg::fuse_command_resp_t)
    ) u_efuse_interface_shim (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),

        .fuse_bank_ctrl_req_i  (efuse_bank_ctrl_req_i),
        .fuse_bank_ctrl_resp_o (efuse_bank_ctrl_resp_o),

        .fuse_command_req_i  (efuse_shim_command_req_i),
        .fuse_command_resp_o (efuse_shim_command_resp_o),

        .efuse_model_otp_req_o  (efuse_model_otp_req),
        .efuse_model_otp_resp_i (efuse_model_otp_resp),

        .debug_bus_o (efuse_debug_bus_o)
    );

    efuse_bank_model #(
        .NumFuseByteWidth (sep_efuse_pkg::NumFuseByteWidth),
        .IsSmcInstance    (1'b0),
        .efuse_apb_req_t  (sep_efuse_pkg::efuse_apb_req_t),
        .efuse_apb_resp_t (sep_efuse_pkg::efuse_apb_resp_t)
    ) u_efuse_bank_model (
        .clk_i  (clk_i),
        .rst_ni (rst_ni),

        .apb_req_i  (efuse_model_otp_req),
        .apb_resp_o (efuse_model_otp_resp),

        .hwif_out ()
    );

    //////////////////////////
    // SRAM External Module //
    //////////////////////////

    localparam int unsigned SRAM_N_ENTRIES  = 256 * 1024 / 8; // 256KB
    localparam int unsigned SRAM_ADDR_WIDTH = $clog2(SRAM_N_ENTRIES);
    localparam int unsigned SRAM_DATA_WIDTH = 64;

    logic                       sram_macro_req;
    logic                       sram_macro_write;
    logic [SRAM_ADDR_WIDTH-1:0] sram_macro_addr;
    logic [SRAM_DATA_WIDTH-1:0] sram_macro_wdata;
    logic [SRAM_DATA_WIDTH-1:0] sram_macro_wmask;
    logic [SRAM_DATA_WIDTH-1:0] sram_macro_rdata;
    logic                       sram_macro_rvalid;

    sep_sram_interface_shim #(
        .SRAM_ADDR_WIDTH (SRAM_ADDR_WIDTH)
    ) u_sep_sram_interface_shim (
        .clk_i          (clk_i),
        .rst_ni         (sep_cpu_reset_n_i),
        .mem_req_i      (sep_sram_req),
        .mem_rsp_o      (sep_sram_rsp),
        .macro_req_o    (sram_macro_req),
        .macro_write_o  (sram_macro_write),
        .macro_addr_o   (sram_macro_addr),
        .macro_wdata_o  (sram_macro_wdata),
        .macro_wmask_o  (sram_macro_wmask),
        .macro_rdata_i  (sram_macro_rdata),
        .macro_rvalid_i (sram_macro_rvalid)
    );

    prim_ram_1p_adv #(
        .Depth       (SRAM_N_ENTRIES),
        .Width       (SRAM_DATA_WIDTH),
        .MemInitFile ("")
    ) u_sep_sram (
        .clk_i     (clk_i),
        .rst_ni    (sep_cpu_reset_n_i),
        .req_i     (sram_macro_req),
        .write_i   (sram_macro_write),
        .addr_i    (sram_macro_addr),
        .wdata_i   (sram_macro_wdata),
        .wmask_i   (sram_macro_wmask),
        .rdata_o   (sram_macro_rdata),
        .rvalid_o  (sram_macro_rvalid),
        .rerror_o  (),
        .alert_o   (),
        .cfg_i     ('0),
        .cfg_rsp_o ()
    );

    /////////////////////////
    // ROM External Module //
    /////////////////////////

    localparam int unsigned ROM_N_ENTRIES  = 16384; // 16K entries * 8B = 128KB
    localparam int unsigned ROM_ADDR_WIDTH = $clog2(ROM_N_ENTRIES);
    localparam int unsigned ROM_DATA_WIDTH = 64;

    logic                      rom_macro_req;
    logic [ROM_ADDR_WIDTH-1:0] rom_macro_addr;
    logic [ROM_DATA_WIDTH-1:0] rom_macro_rdata;

    sep_rom_interface_shim #(
        .ROM_ADDR_WIDTH (ROM_ADDR_WIDTH)
    ) u_sep_rom_interface_shim (
        .clk_i         (clk_i),
        .rst_ni        (sep_cpu_reset_n_i),
        .mem_req_i     (sep_boot_rom_req),
        .mem_rsp_o     (sep_boot_rom_rsp),
        .macro_req_o   (rom_macro_req),
        .macro_addr_o  (rom_macro_addr),
        .macro_rdata_i (rom_macro_rdata)
    );

    prim_rom #(
        .Width       (ROM_DATA_WIDTH),
        .Depth       (ROM_N_ENTRIES),
        .MemInitFile ("")
    ) u_sep_boot_rom (
        .clk_i   (clk_i),
        .rst_ni  (sep_cpu_reset_n_i),
        .req_i   (rom_macro_req),
        .addr_i  (rom_macro_addr),
        .rdata_o (rom_macro_rdata),
        .cfg_i   ('0)
    );

    /////////////////////////
    // TCM External Module //
    /////////////////////////

    // sep_tcm_wrapper instantiates the VeeR EL2 ICCM/DCCM bank macros
    // (ram_<depth>x39), generated by the core's RAM-generation flow like in
    // upstream VeeR EL2's own reference testbench.
    sep_tcm_wrapper u_sep_tcm_wrapper (
        .tcm_req_i (sep_cpu_tcm_req_i),
        .tcm_rsp_o (sep_cpu_tcm_rsp_o)
    );

    ////////////////////////////
    // KM ROM External Module //
    ////////////////////////////

    localparam int unsigned KM_ROM_DEPTH = 4096; // 4K words x 32b = 16KB
    localparam int unsigned KM_ROM_AW    = $clog2(KM_ROM_DEPTH);
    localparam int unsigned KM_ROM_WIDTH = 36;   // 32 data + 4 parity

    logic [KM_ROM_WIDTH-1:0] km_rom_rdata;
    logic                    km_rom_rvalid;

    assign km_rom_mem_rsp_o.gnt    = 1'b1;
    assign km_rom_mem_rsp_o.rvalid = km_rom_rvalid;
    assign km_rom_mem_rsp_o.rdata  = km_rom_rdata[31:0];
    assign km_rom_mem_rsp_o.parity = km_rom_rdata[35:32];

    always_ff @(posedge clk_i or negedge sep_cpu_reset_n_i) begin
        if (!sep_cpu_reset_n_i) km_rom_rvalid <= 1'b0;
        else km_rom_rvalid <= km_rom_mem_req_i.req;
    end

    prim_rom #(
        .Width       (KM_ROM_WIDTH),
        .Depth       (KM_ROM_DEPTH),
        .MemInitFile ("")
    ) u_km_rom (
        .clk_i   (clk_i),
        .rst_ni  (sep_cpu_reset_n_i),
        .req_i   (km_rom_mem_req_i.req),
        .addr_i  (km_rom_mem_req_i.addr[KM_ROM_AW-1:0]),
        .rdata_o (km_rom_rdata),
        .cfg_i   ('0)
    );

    /////////////////////////////
    // KM SRAM External Module //
    /////////////////////////////

    localparam int unsigned KM_SRAM_DEPTH = 4096; // 4K words x 32b = 16KB
    localparam int unsigned KM_SRAM_AW    = $clog2(KM_SRAM_DEPTH);
    localparam int unsigned KM_SRAM_WIDTH = 36;   // 32 data + 4 parity

    logic [KM_SRAM_WIDTH-1:0] km_sram_wdata;
    logic [KM_SRAM_WIDTH-1:0] km_sram_wmask;
    logic [KM_SRAM_WIDTH-1:0] km_sram_rdata;

    assign km_sram_wdata = {km_sram_mem_req_i.wparity, km_sram_mem_req_i.wdata};

    for (genvar b = 0; b < 4; b++) begin : gen_km_sram_wmask
        assign km_sram_wmask[b*8+:8] = {8{km_sram_mem_req_i.be[b]}};
    end
    assign km_sram_wmask[35:32] = km_sram_mem_req_i.be;

    assign km_sram_mem_rsp_o.gnt     = 1'b1;
    assign km_sram_mem_rsp_o.rdata   = km_sram_rdata[31:0];
    assign km_sram_mem_rsp_o.rparity = km_sram_rdata[35:32];

    prim_ram_1p_adv #(
        .Depth       (KM_SRAM_DEPTH),
        .Width       (KM_SRAM_WIDTH),
        .MemInitFile ("")
    ) u_km_sram (
        .clk_i    (clk_i),
        .rst_ni   (sep_cpu_reset_n_i),
        .req_i    (km_sram_mem_req_i.req),
        .write_i  (km_sram_mem_req_i.we),
        .addr_i   (km_sram_mem_req_i.addr[KM_SRAM_AW-1:0]),
        .wdata_i  (km_sram_wdata),
        .wmask_i  (km_sram_wmask),
        .rdata_o  (km_sram_rdata),
        .rvalid_o (km_sram_mem_rsp_o.rvalid),
        .rerror_o (),
        .alert_o  (),
        .cfg_i    ('0),
        .cfg_rsp_o()
    );

    ////////////////////////////////
    // OTBN IMEM External Module //
    ////////////////////////////////

    logic [sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_WORD_WIDTH-1:0] otbn_imem_rdata;

    assign sep_crypto_pka_imem_sram_rsp.rdata   = otbn_imem_rdata;
    assign sep_crypto_pka_imem_sram_rsp.q_valid = 1'b0;

    prim_ram_1p #(
        .Width           (sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_WORD_WIDTH),
        .Depth           (2**sep_crypto_pkg::SEP_CRYPTO_PKA_IMEM_ADDR_WIDTH),
        .DataBitsPerMask (1)
    ) u_otbn_imem_sram (
        .clk_i    (sep_crypto_pka_imem_sram_req.clk),
        .rst_ni   (sep_cpu_reset_n_i),
        .req_i    (sep_crypto_pka_imem_sram_req.enable),
        .write_i  (sep_crypto_pka_imem_sram_req.write),
        .addr_i   (sep_crypto_pka_imem_sram_req.addr),
        .wdata_i  (sep_crypto_pka_imem_sram_req.wdata),
        .wmask_i  (sep_crypto_pka_imem_sram_req.wmask),
        .rdata_o  (otbn_imem_rdata),
        .cfg_i    ('0),
        .cfg_rsp_o()
    );

    ////////////////////////////////
    // OTBN DMEM External Module //
    ////////////////////////////////

    logic [sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_WORD_WIDTH-1:0] otbn_dmem_rdata;

    assign sep_crypto_pka_dmem_sram_rsp.rdata = otbn_dmem_rdata;

    prim_ram_1p #(
        .Width           (sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_WORD_WIDTH),
        .Depth           (2**sep_crypto_pkg::SEP_CRYPTO_PKA_DMEM_ADDR_WIDTH),
        .DataBitsPerMask (1)
    ) u_otbn_dmem_sram (
        .clk_i    (sep_crypto_pka_dmem_sram_req.clk),
        .rst_ni   (sep_cpu_reset_n_i),
        .req_i    (sep_crypto_pka_dmem_sram_req.enable),
        .write_i  (sep_crypto_pka_dmem_sram_req.write),
        .addr_i   (sep_crypto_pka_dmem_sram_req.addr),
        .wdata_i  (sep_crypto_pka_dmem_sram_req.wdata),
        .wmask_i  (sep_crypto_pka_dmem_sram_req.wmask),
        .rdata_o  (otbn_dmem_rdata),
        .cfg_i    ('0),
        .cfg_rsp_o()
    );

    //=========================================================================
    // External TRNG -- terminated with a DECERR slave; entropy-stream/irq/
    // alarm outputs are idled.
    //=========================================================================

    prim_axi_lite_err_slv #(
        .AXI_DATA_WIDTH (32),
        .AXI_ADDR_WIDTH (32),
        .axil_req_t     (sep_pkg::sep_32_32_axil_req_t),
        .axil_resp_t    (sep_pkg::sep_32_32_axil_resp_t)
    ) u_ext_trng_axil_err_slv (
        .clk_i       (clk_i),
        .rst_ni      (rst_ni),
        .axil_req_i  (ext_trng_axil_req_i),
        .axil_resp_o (ext_trng_axil_resp_o)
    );

    assign ext_trng_axis_req_o = '{default: '0};
    assign ext_trng_irq_o      = 1'b0;
    assign ext_trng_alarm_o    = 1'b0;

    //=========================================================================
    // AXI Extension -- terminated with a DECERR slave, keeping the bus from
    // hanging until an adopter connects a real peripheral here.
    //=========================================================================

    axi_err_slv #(
        .AxiIdWidth (sep_pkg::SEP_32_64_6_12_ID_WIDTH),
        .axi_req_t  (sep_pkg::sep_32_64_6_12_axi_req_t),
        .axi_resp_t (sep_pkg::sep_32_64_6_12_axi_resp_t),
        .Resp       (axi_pkg::RESP_DECERR),
        .RespWidth  (sep_pkg::SEP_32_64_6_12_DATA_WIDTH),
        .RespData   ('0),
        .ATOPs      (1'b0),
        .MaxTrans   (2)
    ) u_axi_extension_err_slv (
        .clk_i      (clk_i),
        .rst_ni     (rst_ni),
        .test_i     (test_en_i),
        .slv_req_i  (axi_extension_axi_req_i),
        .slv_resp_o (axi_extension_axi_resp_o)
    );

endmodule
