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
// Every other technology-specific interface smc.sv exposes (CPU cache/SRAM/
// ROM memory macros, I3C DAT/DCT memory macros, ATB telemetry, DFD/trace,
// SPI-over-GPIO muxing, etc.) is passed straight through by smc_wrapper.sv,
// left for a full-chip integration to wire up.
//
// This is a reference integration example, provided for adopters to
// substitute with their own vendor IP/macros.
//-----------------------------------------------------------------------------

module smc_ip_integration (
    input logic clk_smc_i,
    input logic rst_primary_smc_clk_ni,

    // PLL AXI-Lite CSR (from smc.sv)
    input  smc_pkg::smc_axil_32_32_req_t  axil_pll_req_i,
    output smc_pkg::smc_axil_32_32_resp_t axil_pll_resp_o,

    // PVT AXI-Lite CSR (from smc.sv)
    input  smc_pkg::smc_axil_32_32_req_t  axil_pvt_req_i,
    output smc_pkg::smc_axil_32_32_resp_t axil_pvt_resp_o,

    // GPIO shim per-pin CSR AXI-Lite (from smc.sv; terminated internally)
    input  gpio_pkg::gpio_axil_req_t  axil_req_gpio_ctrl_i,
    output gpio_pkg::gpio_axil_resp_t axil_resp_gpio_ctrl_o,

    // Adopter peripheral extension AXI-Lite (from smc.sv; terminated
    // internally)
    input  smc_pkg::smc_axil_32_32_req_t  axil_extension_req_i,
    output smc_pkg::smc_axil_32_32_resp_t axil_extension_resp_o,

    // Efuse interfaces (from smc.sv)
    input  smc_pkg::smc_axil_32_32_req_t      efuse_bank_ctrl_req_i,
    output smc_pkg::smc_axil_32_32_resp_t     efuse_bank_ctrl_resp_o,
    input  smc_efuse_pkg::fuse_command_req_t  efuse_shim_command_req_i,
    output smc_efuse_pkg::fuse_command_resp_t efuse_shim_command_resp_o,

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

    ///////////////
    // PLL Model //
    ///////////////

    pll_wrap u_pll_wrap (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (axil_pll_req_i),
        .axil_resp_o(axil_pll_resp_o)
    );

    ///////////////
    // PVT Model //
    ///////////////

    pvt_wrap u_pvt_wrap (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (axil_pvt_req_i),
        .axil_resp_o(axil_pvt_resp_o)
    );

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
    // GPIO shim CSR + adopter peripheral extension -- terminated with
    // DECERR slaves.
    //=========================================================================

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (gpio_pkg::ADDR_WIDTH),
        .AXI_DATA_WIDTH (gpio_pkg::DATA_WIDTH),
        .axil_req_t     (gpio_pkg::gpio_axil_req_t),
        .axil_resp_t    (gpio_pkg::gpio_axil_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (gpio_pkg::DATA_WIDTH),
        .RESP_DATA      ('0),
        .MAX_TRANS      (2)
    ) u_gpio_ctrl_err_slv (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (axil_req_gpio_ctrl_i),
        .axil_resp_o(axil_resp_gpio_ctrl_o)
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
    ) u_axil_extension_err_slv (
        .clk_i      (clk_smc_i),
        .rst_ni     (rst_primary_smc_clk_ni),
        .axil_req_i (axil_extension_req_i),
        .axil_resp_o(axil_extension_resp_o)
    );

endmodule
