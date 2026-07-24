// SPDX-License-Identifier: Apache-2.0
//
// DV shadow of hw/.bos/wrapper/smc/smc_padring_ext.sv (issue #3357
// flow). Identical to the hw/.bos source except that the refclk /
// reset / powergood input pads are modeled as transparent connections:
// the original drives prim_pad_wrapper inout_io from input-only ports,
// which Verilator rejects (ASSIGNIN). The sim config excludes the
// hw/.bos copy and compiles this file instead; drop this shadow
// once the hw fix lands.
//
//----------------------------------------------------------
// SMC GPIO External Components
// Includes Shim + Macro + IP-specific logic
//
// Copyright 2025 Tenstorrent Inc.
//----------------------------------------------------------


module smc_padring_ext
(
    // Clock and Reset
    input  logic                                    clk_smc_i,
    input  logic                                    rst_cold_stable_ref_clk_ni,
    input  logic                                    rst_primary_smc_clk_ni,
    input  logic                                    test_en_i,
    input  logic                                    scan_rst_ni,

    // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
    inout wire VDD,
    inout wire VDDO,
    inout wire VSS,
`endif

    // GPIO PADs (inout signals to be connected to actual pads)
    inout  wire [smc_pkg::NUM_BONDED_GPIO-1:0]      GPIO_PAD,
    inout  wire [smc_pkg::NUM_UNBONDED_GPIO-1:0]    UNBONDED_GPIO,

    // JTAG PADs (inout signals to be connected to actual pads)
    inout  wire PAD_JTAG_IN_TCK,
    inout  wire PAD_JTAG_IN_TRSTN,
    inout  wire PAD_JTAG_IN_TMS,
    inout  wire PAD_JTAG_IN_TDI,
    inout  wire PAD_JTAG_IN_TDO,
    inout  wire PAD_JTAG_OUT_TCK,
    inout  wire PAD_JTAG_OUT_TRSTN,
    inout  wire PAD_JTAG_OUT_TMS,
    inout  wire PAD_JTAG_OUT_TDI,
    inout  wire PAD_JTAG_OUT_TDO,

    // Xtrigger PADs (inout signals to be connected to actual pads)
    inout  wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_REQ_OUT,
    inout  wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_REQ_IN,
    inout  wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_ACK_IN,
    inout  wire [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] BP_XTRIG_ACK_OUT,

    // Reference Clock and Reset PADs
    input  wire PAD_REFCLK,
    input  wire PAD_PRSTN,
    input  wire PAD_POWERGOOD,

    // GPIO Control AXI-Lite interface (single interface for all control blocks)
    // This control plane is intentionally `smc_clk`-synchronous. Any adopter-
    // specific need for `refclk` inside this wrapper should be handled with an
    // explicit local CDC, not by reinterpreting this bus as a `refclk` bus.
    input  gpio_pkg::gpio_axil_req_t                            axil_req_ctrl_i,
    output gpio_pkg::gpio_axil_resp_t                           axil_resp_ctrl_o,

    // LSIO interface select (for hardware protocols)
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0]        lsio_interface_select_i,

    // I3C glitch filter disable
    input  logic [smc_config_pkg::NUM_I3C-1:0]			i3c_gf_dis_i,

    input  logic psyscrit_active_i,
    input  logic vrhot_active_i,

    // GPIO interface signals
    output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_o,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en_i,

    // GPIO 2nd HW Function Override
    output logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_ovrd_o,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_ovrd_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en_ovrd_i,
    input  logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en_ovrd_i,

    // GPIO nandtree interface
    input  logic                               gpio_nandtree_enable_i,
    output logic                               gpio_nandtree_o,

    // JTAG input bundle interface (from pads to core)
    output logic jtag_in_tck_o,
    output logic jtag_in_trstn_o,
    output logic jtag_in_tms_o,
    output logic jtag_in_tdi_o,
    input  logic jtag_in_tdo_i,

    // JTAG output bundle interface (from core to pads)
    input  logic jtag_out_tck_i,
    input  logic jtag_out_trstn_i,
    input  logic jtag_out_tms_i,
    output logic jtag_out_tdi_o,
    input  logic jtag_out_tdo_i,

    // Cross trigger interface (from DTP to drive xtrigger pads) - using first 4 of 8 available
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_out_dout_i,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_out_dout_en_i,
    output logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_out_din_o,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_out_din_en_i,

    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_in_dout_i,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_in_dout_en_i,
    output logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_in_din_o,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_req_in_din_en_i,

    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_in_dout_i,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_in_dout_en_i,
    output logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_in_din_o,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_in_din_en_i,

    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_out_dout_i,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_out_dout_en_i,
    output logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_out_din_o,
    input  logic [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0] ct_ack_out_din_en_i,

    // Reference clock outputs (to core)
    output logic refclk_vdd_sys_o,

    // Captured straps
    output logic [smc_pkg::NUM_BONDED_GPIO-1:0] captured_straps_o,

    // Reset and PowerGood outputs
    output logic powergood_o, // PowerGood signal
    output logic rst_cold_no, // Cold reset from pad to SMC
    output logic rst_cool_no  // Cool reset from pad to SMC
);

    // GPIO Shim to Pad interface signals
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] core2pad_en;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] pad2core_en;

    // GPIO control and status signals
    gpio_shim_pkg::gpio_model_ctrl_t   gpio_ctrl   [smc_ip_integration_pkg::NUM_GPIO-1:0];
    gpio_shim_pkg::gpio_model_status_t gpio_status [smc_ip_integration_pkg::NUM_GPIO-1:0];

    // Power control signals from POC/PBIAS wrappers
    wire VSW_vdd_sys;
    wire VREFN_vdd_sys;
    wire VREFP_vdd_sys;
    wire RTN_vdd_sys;
    wire SPS_vdd_sys;

    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_nandtree_en, gpio_nandtree_out;
    logic gpio_nandtree_jtag_in_en, gpio_nandtree_jtag_in__out;
    logic gpio_nandtree_jtag_out_en, gpio_nandtree_jtag_out__out;

    ////////////////
    // Powergood  //
    ////////////////

    logic powergood_1p2_b;

    logic refclk_vdd_sys;

    ////////////////////
	// LSIO Interface //
	////////////////////

    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_pull_en;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_pull_sel;
    logic [smc_pkg::NUM_GPIO_WRAPS-1:0] lsio_gf_dis;

	always_comb begin
        lsio_pull_en  = '0;  // default: don't pull
        lsio_pull_sel = '0;
        lsio_gf_dis   = '0;  // default: enable glitch filter

        // SPI Data Connections
        // Quad SPI so 8 data pins
        for (int s = 0; s < 8; s = s + 1) begin : gen_spi_connections
            lsio_pull_en[s]  = 1'b1;  // weak pull down for SPI data
            lsio_pull_sel[s] = 1'b0;
        end

        // weak pull up for SPI CS
        lsio_pull_en[8]  = 1'b1;
        lsio_pull_sel[8] = 1'b1;

        // weak pull down for SPI clock
        lsio_pull_en[9]  = 1'b1;
        lsio_pull_sel[9] = 1'b0;

        // weak pull down for SPI DQS
        lsio_pull_en[10]  = 1'b1;
        lsio_pull_sel[10] = 1'b0;

        // UART Interfaces
        for (integer u = 0; u < smc_config_pkg::NUM_UART; u = u + 1) begin : gen_uart_connections
            // weak pull up for UART RX
            lsio_pull_en[11+4*u]          = 1'b1;
            lsio_pull_sel[11+4*u]         = 1'b1;

            // weak pull up for UART TX
            lsio_pull_en[12+4*u]          = 1'b1;
            lsio_pull_sel[12+4*u]         = 1'b1;

            // weak pull down for UART RTS
            lsio_pull_en[13+4*u]          = 1'b1;
            lsio_pull_sel[13+4*u]         = 1'b0;

            // weak pull down for UART CTS
            lsio_pull_en[14+4*u]          = 1'b1;
            lsio_pull_sel[14+4*u]         = 1'b0;
        end

                // PTP timer makes use of GPIOs 15/16, if uart is not enabled, then give permissions to PTP -- weak pull up
        if (!lsio_interface_select_i[15]) begin
            lsio_pull_en[15]          = 1'b1;
            lsio_pull_sel[15]         = 1'b1;
        end

        if (!lsio_interface_select_i[16]) begin
            lsio_pull_en[16]          = 1'b1;
            lsio_pull_sel[16]         = 1'b1;
        end

        // VRHOT & PSYSCRIT make use of GPIOs 25/26, if active, set GPIO to read the signals
        if (psyscrit_active_i) begin
            lsio_pull_en[25]          = 1'b1;
            lsio_pull_sel[25]         = 1'b0;
        end

        if (vrhot_active_i) begin
            lsio_pull_en[26]          = 1'b1;
            lsio_pull_sel[26]         = 1'b0;
        end

        // Non-Boot I3C Interface (I3C[0]) (Exposed to Package) -- no pull
        lsio_pull_en[27]          = 1'b0;
        lsio_pull_sel[27]         = 1'b1;

        lsio_pull_en[28]          = 1'b0;
        lsio_pull_sel[28]         = 1'b1;

        // I3C[2:5] -- no pull (I3C[1] is fully unbonded)
        for (integer i = 0; i < (smc_config_pkg::NUM_I3C - 2); i = i + 1) begin : gen_i3c_connections
            lsio_pull_en[29+(2*i)]  = 1'b0;
            lsio_pull_sel[29+(2*i)] = 1'b1;

            lsio_pull_en[30+(2*i)]  = 1'b0;
            lsio_pull_sel[30+(2*i)] = 1'b1;
            lsio_gf_dis[30+(2*i)]   = i3c_gf_dis_i[2+i]; // i3c can control glitch filter for SDA
        end

        // GPIO_62 and GPIO_63 are now available for repurposing -- weak pull down
        lsio_pull_en[62]  = 1'b1;
        lsio_pull_sel[62] = 1'b0;

        lsio_pull_en[63]  = 1'b1;
        lsio_pull_sel[63] = 1'b0;

        // I3C[1] fully unbonded (both SCL and SDA) -- no pull
        lsio_pull_en[66]  = 1'b0;
        lsio_pull_sel[66] = 1'b1;
        // No glitch filter control for SCL

        lsio_pull_en[67]  = 1'b0;
        lsio_pull_sel[67] = 1'b1;
        lsio_gf_dis[67]   = i3c_gf_dis_i[1]; // i3c can control glitch filter for SDA

        // I2C Interfaces -- don't pull (external pull-up resistor used)
        lsio_pull_en[37+:(smc_config_pkg::NUM_I2C*4)]  = '0;
        lsio_pull_sel[37+:(smc_config_pkg::NUM_I2C*4)] = '0;

        // AVS Interface -- weak pull up
        lsio_pull_en[49]      = 1'b1;
        lsio_pull_sel[49]     = 1'b1;

        lsio_pull_en[50]      = 1'b1;
        lsio_pull_sel[50]     = 1'b1;

        lsio_pull_en[51]      = 1'b1;
        lsio_pull_sel[51]     = 1'b1;

        // CAT THERM Interface -- weak pull up (active low)
        lsio_pull_en[52]      = 1'b1;
        lsio_pull_sel[52]     = 1'b1;

        // Isolate request -- weak pull down
        lsio_pull_en[53]      = 1'b1;
        lsio_pull_sel[53]     = 1'b0;

        // SPI memory rebar -- weak pull down
        lsio_pull_en[54]      = 1'b1;
        lsio_pull_sel[54]     = 1'b0;

        // PLL observation -- weak pull down
        lsio_pull_en[55]      = 1'b1;
        lsio_pull_sel[55]     = 1'b0; // weak pull down

        // Unused -- weak pull down
        lsio_pull_en[56]      = 1'b1;
        lsio_pull_sel[56]     = 1'b0;

        // PVT RO observation -- weak pull down
        lsio_pull_en[57]      = 1'b1;
        lsio_pull_sel[57]     = 1'b0;

        // OCTS -- weak pull up
        lsio_pull_en[58]      = 1'b1;
        lsio_pull_sel[58]     = 1'b1;

        lsio_pull_en[59]      = 1'b1;
        lsio_pull_sel[59]     = 1'b1;

        // Boot Stall -- weak pull down
        lsio_pull_en[60]      = 1'b1;
        lsio_pull_sel[60]     = 1'b0;

        // unused - weak pull down
        lsio_pull_en[61]      = 1'b1;
        lsio_pull_sel[61]     = 1'b0;

        // Cool Reset In -- weak pull up (active low)
        lsio_pull_en[64]          = 1'b1;
        lsio_pull_sel[64]         = 1'b1;

        // Cool Reset Out -- weak pull up (active low)
        lsio_pull_en[65]          = 1'b1;
        lsio_pull_sel[65]         = 1'b1;

    end

    ///////////////////
    // Strap Capture //
    ///////////////////

    logic [smc_pkg::NUM_BONDED_GPIO-1:0] captured_straps;

    ///////////////////////////////////
    // GPIO Control Demux and Blocks //
    ///////////////////////////////////

    // TODO: add error slave for final target

    gpio_pkg::gpio_axil_req_t  [smc_ip_integration_pkg::NUM_EXT_PADRING_TARGETS-1:0] axil_reqs_ctrl_demux;
    gpio_pkg::gpio_axil_resp_t [smc_ip_integration_pkg::NUM_EXT_PADRING_TARGETS-1:0] axil_resps_ctrl_demux;
    logic [$clog2(smc_ip_integration_pkg::NUM_EXT_PADRING_TARGETS)-1:0] ctrl_aw_select, ctrl_ar_select;

    always_comb begin
        // Decode AW channel
        if (axil_req_ctrl_i.aw.addr >= smc_pkg::GPIO_CTRL_0__REG_MAP_BASE_ADDR && axil_req_ctrl_i.aw.addr < smc_pkg::GPIO_REFCLK_CTRL_REG_MAP_BASE_ADDR) begin
            ctrl_aw_select = (axil_req_ctrl_i.aw.addr - smc_pkg::GPIO_CTRL_0__REG_MAP_BASE_ADDR) >> 5;
        end else if (axil_req_ctrl_i.aw.addr >= smc_pkg::GPIO_REFCLK_CTRL_REG_MAP_BASE_ADDR && axil_req_ctrl_i.aw.addr < smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR) begin
            ctrl_aw_select = 68; // gpio_refclk_ctrl at index 68
        end else if (axil_req_ctrl_i.aw.addr >= smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR &&
                        axil_req_ctrl_i.aw.addr < smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR + smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_SIZE) begin
            ctrl_aw_select = 69; // POC/PBIAS at index 69
        end else begin
            ctrl_aw_select = 0; // Default to first target if out of range
        end

        // Decode AR channel
        if (axil_req_ctrl_i.ar.addr >= smc_pkg::GPIO_CTRL_0__REG_MAP_BASE_ADDR && axil_req_ctrl_i.ar.addr < smc_pkg::GPIO_REFCLK_CTRL_REG_MAP_BASE_ADDR) begin
            ctrl_ar_select = (axil_req_ctrl_i.ar.addr - smc_pkg::GPIO_CTRL_0__REG_MAP_BASE_ADDR) >> 5;
        end else if (axil_req_ctrl_i.ar.addr >= smc_pkg::GPIO_REFCLK_CTRL_REG_MAP_BASE_ADDR && axil_req_ctrl_i.ar.addr < smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR) begin
            ctrl_ar_select = 68; // gpio_refclk_ctrl at index 68
        end else if (axil_req_ctrl_i.ar.addr >= smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR &&
                        axil_req_ctrl_i.ar.addr < smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_BASE_ADDR + smc_pkg::GPIO_POC_PBIAS_CTRL_REG_MAP_SIZE) begin
            ctrl_ar_select = 69; // POC/PBIAS at index 69
        end else begin
            ctrl_ar_select = 0; // Default to first target if out of range
        end
    end

    axi_lite_demux #(
        .aw_chan_t          (gpio_pkg::gpio_axil_aw_chan_t),
        .w_chan_t           (gpio_pkg::gpio_axil_w_chan_t),
        .b_chan_t           (gpio_pkg::gpio_axil_b_chan_t),
        .ar_chan_t          (gpio_pkg::gpio_axil_ar_chan_t),
        .r_chan_t           (gpio_pkg::gpio_axil_r_chan_t),
        .axi_req_t          (gpio_pkg::gpio_axil_req_t),
        .axi_resp_t         (gpio_pkg::gpio_axil_resp_t),
        .NoMstPorts         (smc_ip_integration_pkg::NUM_EXT_PADRING_TARGETS),
        .MaxTrans           (1),
        .FallThrough        (1'b0),
        .SpillAw            (1'b1),
        .SpillW             (1'b0),
        .SpillB             (1'b0),
        .SpillAr            (1'b1),
        .SpillR             (1'b0)
    ) ctrl_axi_lite_demux (
        .clk_i              (clk_smc_i),
        .rst_ni             (rst_primary_smc_clk_ni),
        .test_i             (test_en_i),
        .slv_req_i          (axil_req_ctrl_i),
        .slv_resp_o         (axil_resp_ctrl_o),
        .slv_aw_select_i    (ctrl_aw_select),
        .slv_ar_select_i    (ctrl_ar_select),
        .mst_reqs_o         (axil_reqs_ctrl_demux),
        .mst_resps_i        (axil_resps_ctrl_demux)
    );


    /////////////////////////
    // GPIO Shims and Pads //
    /////////////////////////

    // Generate GPIO shims and Samsung pad instances for each GPIO
    for (genvar g = 0; g < smc_pkg::NUM_BONDED_GPIO; g++) begin : gen_gpio_instances

        // GPIO Macro Wrapper Instance - encapsulates shim + pad
        gpio_macro_wrapper #(
            .INPUT_BY_DEFAULT   (smc_ip_integration_pkg::PadValidStrapMap[g]),     // Input strap configuration from map
            .ENABLE_PULL        (smc_ip_integration_pkg::PadPullEnableMap[g]),     // Pull enable from map
            .USE_PULL_UP        (smc_ip_integration_pkg::PadPullUpMap[g]),         // Pull direction from map
            .PAD_ORIENTATION    (smc_ip_integration_pkg::PadOrientationMap[g])    // Pad orientation (0=vertical, 1=horizontal)
        ) u_gpio_macro_wrapper (
            .clk_i                      (clk_smc_i),
            .rst_primary_ni             (rst_primary_smc_clk_ni),
            .rst_cold_ni                (rst_cold_stable_ref_clk_ni),
            .test_en_i                  (test_en_i),

            // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
            .VDD                        (VDD),
            .VDDO                       (VDDO),
            .VSS                        (VSS),
`endif
            .VSW_vdd_sys                (VSW_vdd_sys),
            .VREFN_vdd_sys              (VREFN_vdd_sys),
            .VREFP_vdd_sys              (VREFP_vdd_sys),
            .RTN_vdd_sys                (RTN_vdd_sys),
            .SPS_vdd_sys                (SPS_vdd_sys),

            // GPIO Core Interface (to/from SMC)
            .core2pad_i                 (core2pad_i[g]),
            .core2pad_en_i              (core2pad_en_i[g]),
            .pad2core_o                 (pad2core_o[g]),
            .pad2core_en_i              (pad2core_en_i[g]),

            // GPIO 2nd HW Function Override
            .core2pad_ovrd_i            (core2pad_ovrd_i[g]),
            .core2pad_en_ovrd_i         (core2pad_en_ovrd_i[g]),
            .pad2core_ovrd_o            (pad2core_ovrd_o[g]),
            .pad2core_en_ovrd_i         (pad2core_en_ovrd_i[g]),

            // External GPIO Control (from LSIO interface)
            .ext_intf_sel_i             (lsio_interface_select_i[g]),
            .reg_lsio_sel_i             (1'b0),
            .reg_lsio_disable_i         (1'b0),
            .ext_drive_strength_i       (3'b010),                   // Default drive strength
            .ext_pull_en_i              (lsio_pull_en[g]),
            .ext_pull_sel_i             (lsio_pull_sel[g]),
            .ext_gf_disable_i           (lsio_gf_dis[g]),

            .captured_strap_o           (captured_straps[g]),

            // GPIO Register Interface (AXI4-Lite)
            .axil_req_i                 (axil_reqs_ctrl_demux[g]),
            .axil_resp_o                (axil_resps_ctrl_demux[g]),

            .gpio_nandtree_in_i         (gpio_nandtree_en[g]),
            .gpio_nandtree_out_o        (gpio_nandtree_out[g]),

            // External PAD connection
            .GPIO_PAD                   (GPIO_PAD[g])
        );

        if (g == 0) begin : gen_gpio_nandtree_first
            assign gpio_nandtree_en[g] = gpio_nandtree_enable_i;
        end else begin : gen_gpio_nandtree
            assign gpio_nandtree_en[g] = gpio_nandtree_out[g-1];
        end
    end

    ////////////////////////////////////////
    // Unbonded GPIO Individual Instances //
    ////////////////////////////////////////

    assign gpio_nandtree_en[64] = gpio_nandtree_out[63];

    input_gpio_macro_wrapper #(
        .INPUT_BY_DEFAULT   (smc_ip_integration_pkg::PadValidStrapMap[64]),     // Input strap configuration from map
        .ENABLE_PULL        (smc_ip_integration_pkg::PadPullEnableMap[64]),     // Pull enable from map
        .USE_PULL_UP        (smc_ip_integration_pkg::PadPullUpMap[64]),         // Pull direction from map
        .PAD_ORIENTATION    (smc_ip_integration_pkg::PadOrientationMap[64])    // Pad orientation (0=vertical, 1=horizontal)
    ) u_unbonded_gpio_0_input_wrapper (
        .clk_i                      (clk_smc_i),
        .rst_primary_ni             (rst_primary_smc_clk_ni),
        .rst_cold_ni                (rst_cold_stable_ref_clk_ni),
        .test_en_i                  (test_en_i),

        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW_vdd_sys                (VSW_vdd_sys),
        .VREFN_vdd_sys              (VREFN_vdd_sys),
        .VREFP_vdd_sys              (VREFP_vdd_sys),
        .RTN_vdd_sys                (RTN_vdd_sys),
        .SPS_vdd_sys                (SPS_vdd_sys),

        // GPIO Core Interface (to/from SMC)
        .core2pad_i                 (core2pad_i[64]),
        .core2pad_en_i              (core2pad_en_i[64]),
        .pad2core_o                 (pad2core_o[64]),
        .pad2core_en_i              (pad2core_en_i[64]),

        // GPIO 2nd HW Function Override
        .core2pad_ovrd_i            (core2pad_ovrd_i[64]),
        .core2pad_en_ovrd_i         (core2pad_en_ovrd_i[64]),
        .pad2core_ovrd_o            (pad2core_ovrd_o[64]),
        .pad2core_en_ovrd_i         (pad2core_en_ovrd_i[64]),

        // External GPIO Control (from LSIO interface)
        .ext_intf_sel_i             (lsio_interface_select_i[64]),
        .reg_lsio_sel_i             (1'b0),
        .reg_lsio_disable_i         (1'b0),
        .ext_drive_strength_i       (3'b010),                           // Default drive strength
        .ext_pull_en_i              (lsio_pull_en[64]),
        .ext_pull_sel_i             (lsio_pull_sel[64]),
        .ext_gf_disable_i           (lsio_gf_dis[64]),

        .captured_strap_o           (),

        // GPIO Register Interface (AXI4-Lite)
        .axil_req_i                 (axil_reqs_ctrl_demux[64]),
        .axil_resp_o                (axil_resps_ctrl_demux[64]),

        // Nandtree Interface
        .gpio_nandtree_in_i         (gpio_nandtree_en[64]),
        .gpio_nandtree_out_o        (gpio_nandtree_out[64]),

        // External PAD connection
        .GPIO_PAD                   (UNBONDED_GPIO[0])
    );

    assign gpio_nandtree_en[65] = gpio_nandtree_out[64];

    gpio_macro_wrapper #(
        .INPUT_BY_DEFAULT   (smc_ip_integration_pkg::PadValidStrapMap[65]),     // Input strap configuration from map
        .ENABLE_PULL        (smc_ip_integration_pkg::PadPullEnableMap[65]),     // Pull enable from map
        .USE_PULL_UP        (smc_ip_integration_pkg::PadPullUpMap[65]),         // Pull direction from map
        .PAD_ORIENTATION    (smc_ip_integration_pkg::PadOrientationMap[65])    // Pad orientation (0=vertical, 1=horizontal)
    ) u_unbonded_gpio_1_wrapper (
        .clk_i                      (clk_smc_i),
        .rst_primary_ni             (rst_primary_smc_clk_ni),
        .rst_cold_ni                (rst_cold_stable_ref_clk_ni),
        .test_en_i                  (test_en_i),

        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW_vdd_sys                (VSW_vdd_sys),
        .VREFN_vdd_sys              (VREFN_vdd_sys),
        .VREFP_vdd_sys              (VREFP_vdd_sys),
        .RTN_vdd_sys                (RTN_vdd_sys),
        .SPS_vdd_sys                (SPS_vdd_sys),

        // GPIO Core Interface (to/from SMC)
        .core2pad_i                 (core2pad_i[65]),
        .core2pad_en_i              (core2pad_en_i[65]),
        .pad2core_o                 (pad2core_o[65]),
        .pad2core_en_i              (pad2core_en_i[65]),

        // GPIO 2nd HW Function Override
        .core2pad_ovrd_i            (core2pad_ovrd_i[65]),
        .core2pad_en_ovrd_i         (core2pad_en_ovrd_i[65]),
        .pad2core_ovrd_o            (pad2core_ovrd_o[65]),
        .pad2core_en_ovrd_i         (pad2core_en_ovrd_i[65]),

        // External GPIO Control (from LSIO interface)
        .ext_intf_sel_i             (lsio_interface_select_i[65]),
        .reg_lsio_sel_i             (1'b0),
        .reg_lsio_disable_i         (1'b0),
        .ext_drive_strength_i       (3'b010),                           // Default drive strength
        .ext_pull_en_i              (lsio_pull_en[65]),
        .ext_pull_sel_i             (lsio_pull_sel[65]),
        .ext_gf_disable_i           (lsio_gf_dis[65]),

        .captured_strap_o           (),

        // GPIO Register Interface (AXI4-Lite)
        .axil_req_i                 (axil_reqs_ctrl_demux[65]),
        .axil_resp_o                (axil_resps_ctrl_demux[65]),

        .gpio_nandtree_in_i         (gpio_nandtree_en[65]),
        .gpio_nandtree_out_o        (gpio_nandtree_out[65]),

        // External PAD connection
        .GPIO_PAD                   (UNBONDED_GPIO[1])
    );

    assign gpio_nandtree_en[66] = gpio_nandtree_out[65];

    gpio_macro_wrapper #(
        .INPUT_BY_DEFAULT   (smc_ip_integration_pkg::PadValidStrapMap[66]),     // Input strap configuration from map
        .ENABLE_PULL        (smc_ip_integration_pkg::PadPullEnableMap[66]),     // Pull enable from map
        .USE_PULL_UP        (smc_ip_integration_pkg::PadPullUpMap[66]),         // Pull direction from map
        .PAD_ORIENTATION    (smc_ip_integration_pkg::PadOrientationMap[66])    // Pad orientation (0=vertical, 1=horizontal)
    ) u_unbonded_gpio_2_wrapper (
        .clk_i                      (clk_smc_i),
        .rst_primary_ni             (rst_primary_smc_clk_ni),
        .rst_cold_ni                (rst_cold_stable_ref_clk_ni),
        .test_en_i                  (test_en_i),

        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW_vdd_sys                (VSW_vdd_sys),
        .VREFN_vdd_sys              (VREFN_vdd_sys),
        .VREFP_vdd_sys              (VREFP_vdd_sys),
        .RTN_vdd_sys                (RTN_vdd_sys),
        .SPS_vdd_sys                (SPS_vdd_sys),

        // GPIO Core Interface (to/from SMC)
        .core2pad_i                 (core2pad_i[66]),
        .core2pad_en_i              (core2pad_en_i[66]),
        .pad2core_o                 (pad2core_o[66]),
        .pad2core_en_i              (pad2core_en_i[66]),

        // GPIO 2nd HW Function Override
        .core2pad_ovrd_i            (core2pad_ovrd_i[66]),
        .core2pad_en_ovrd_i         (core2pad_en_ovrd_i[66]),
        .pad2core_ovrd_o            (pad2core_ovrd_o[66]),
        .pad2core_en_ovrd_i         (pad2core_en_ovrd_i[66]),

        // External GPIO Control (from LSIO interface)
        .ext_intf_sel_i             (lsio_interface_select_i[66]),
        .reg_lsio_sel_i             (1'b0),
        .reg_lsio_disable_i         (1'b0),
        .ext_drive_strength_i       (3'b010),                           // Default drive strength
        .ext_pull_en_i              (lsio_pull_en[66]),
        .ext_pull_sel_i             (lsio_pull_sel[66]),
        .ext_gf_disable_i           (lsio_gf_dis[66]),

        .captured_strap_o           (),

        // GPIO Register Interface (AXI4-Lite)
        .axil_req_i                 (axil_reqs_ctrl_demux[66]),
        .axil_resp_o                (axil_resps_ctrl_demux[66]),

        .gpio_nandtree_in_i         (gpio_nandtree_en[66]),
        .gpio_nandtree_out_o        (gpio_nandtree_out[66]),

        // External PAD connection
        .GPIO_PAD                   (UNBONDED_GPIO[2])
    );

    assign gpio_nandtree_en[67] = gpio_nandtree_out[66];

    gpio_macro_wrapper #(
        .INPUT_BY_DEFAULT   (smc_ip_integration_pkg::PadValidStrapMap[67]),     // Input strap configuration from map
        .ENABLE_PULL        (smc_ip_integration_pkg::PadPullEnableMap[67]),     // Pull enable from map
        .USE_PULL_UP        (smc_ip_integration_pkg::PadPullUpMap[67]),         // Pull direction from map
        .PAD_ORIENTATION    (smc_ip_integration_pkg::PadOrientationMap[67])    // Pad orientation (0=vertical, 1=horizontal)
    ) u_unbonded_gpio_3_wrapper (
        .clk_i                      (clk_smc_i),
        .rst_primary_ni             (rst_primary_smc_clk_ni),
        .rst_cold_ni                (rst_cold_stable_ref_clk_ni),
        .test_en_i                  (test_en_i),

        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW_vdd_sys                (VSW_vdd_sys),
        .VREFN_vdd_sys              (VREFN_vdd_sys),
        .VREFP_vdd_sys              (VREFP_vdd_sys),
        .RTN_vdd_sys                (RTN_vdd_sys),
        .SPS_vdd_sys                (SPS_vdd_sys),

        // GPIO Core Interface (to/from SMC)
        .core2pad_i                 (core2pad_i[67]),
        .core2pad_en_i              (core2pad_en_i[67]),
        .pad2core_o                 (pad2core_o[67]),
        .pad2core_en_i              (pad2core_en_i[67]),

        // GPIO 2nd HW Function Override
        .core2pad_ovrd_i            (core2pad_ovrd_i[67]),
        .core2pad_en_ovrd_i         (core2pad_en_ovrd_i[67]),
        .pad2core_ovrd_o            (pad2core_ovrd_o[67]),
        .pad2core_en_ovrd_i         (pad2core_en_ovrd_i[67]),

        // External GPIO Control (from LSIO interface)
        .ext_intf_sel_i             (lsio_interface_select_i[67]),
        .reg_lsio_sel_i             (1'b0),
        .reg_lsio_disable_i         (1'b0),
        .ext_drive_strength_i       (3'b010),                           // Default drive strength
        .ext_pull_en_i              (lsio_pull_en[67]),
        .ext_pull_sel_i             (lsio_pull_sel[67]),
        .ext_gf_disable_i           (lsio_gf_dis[67]),

        .captured_strap_o           (),

        // GPIO Register Interface (AXI4-Lite)
        .axil_req_i                 (axil_reqs_ctrl_demux[67]),
        .axil_resp_o                (axil_resps_ctrl_demux[67]),

        .gpio_nandtree_in_i         (gpio_nandtree_en[67]),
        .gpio_nandtree_out_o        (gpio_nandtree_out[67]),

        // External PAD connection
        .GPIO_PAD                   (UNBONDED_GPIO[3])
    );

    // intercept cool_reset signal here
    assign rst_cool_no = pad2core_o[64];

    /////////////////////////
    // JTAG Pad Bundles   //
    /////////////////////////

    // JTAG Input Pad Bundle - handles JTAG signals coming into the chiplet
    smc_jtag_in_pad_bundle #(
        .JtagOrientationMap(smc_ip_integration_pkg::JtagInOrientationMap)
    ) u_jtag_in_pad_bundle (
        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW                        (VSW_vdd_sys),
        .VREFN                      (VREFN_vdd_sys),
        .VREFP                      (VREFP_vdd_sys),
        .RTN                        (RTN_vdd_sys),
        .SPS                        (SPS_vdd_sys),

        // JTAG PAD connections
        .PAD_JTAG_TCK               (PAD_JTAG_IN_TCK),
        .PAD_JTAG_TRSTN             (PAD_JTAG_IN_TRSTN),
        .PAD_JTAG_TMS               (PAD_JTAG_IN_TMS),
        .PAD_JTAG_TDI               (PAD_JTAG_IN_TDI),
        .PAD_JTAG_TDO               (PAD_JTAG_IN_TDO),

        // JTAG core interface
        .jtag_tck_o                 (jtag_in_tck_o),
        .jtag_trstn_o               (jtag_in_trstn_o),
        .jtag_tms_o                 (jtag_in_tms_o),
        .jtag_tdi_o                 (jtag_in_tdi_o),
        .jtag_tdo_i                 (jtag_in_tdo_i),

        // Nandtree interface
        .gpio_nandtree_enable_i     (gpio_nandtree_jtag_in_en),
        .gpio_nandtree_o            (gpio_nandtree_jtag_in__out)
    );

    assign gpio_nandtree_jtag_in_en = gpio_nandtree_out[smc_pkg::NUM_GPIO_WRAPS-1];

    // JTAG Output Pad Bundle - handles JTAG signals going out of the chiplet
    smc_jtag_out_pad_bundle #(
        .JtagOrientationMap(smc_ip_integration_pkg::JtagOutOrientationMap)
    ) u_jtag_out_pad_bundle (
        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                        (VDD),
        .VDDO                       (VDDO),
        .VSS                        (VSS),
`endif
        .VSW                        (VSW_vdd_sys),
        .VREFN                      (VREFN_vdd_sys),
        .VREFP                      (VREFP_vdd_sys),
        .RTN                        (RTN_vdd_sys),
        .SPS                        (SPS_vdd_sys),

        // JTAG PAD connections
        .PAD_JTAG_TCK               (PAD_JTAG_OUT_TCK),
        .PAD_JTAG_TRSTN             (PAD_JTAG_OUT_TRSTN),
        .PAD_JTAG_TMS               (PAD_JTAG_OUT_TMS),
        .PAD_JTAG_TDI               (PAD_JTAG_OUT_TDI),
        .PAD_JTAG_TDO               (PAD_JTAG_OUT_TDO),

        // JTAG core interface
        .jtag_tck_i                 (jtag_out_tck_i),
        .jtag_trstn_i               (jtag_out_trstn_i),
        .jtag_tms_i                 (jtag_out_tms_i),
        .jtag_tdi_o                 (jtag_out_tdi_o),
        .jtag_tdo_i                 (jtag_out_tdo_i),

        // Nandtree interface
        .gpio_nandtree_enable_i     (gpio_nandtree_jtag_out_en),
        .gpio_nandtree_o            (gpio_nandtree_jtag_out__out)
    );

    assign gpio_nandtree_jtag_out_en = gpio_nandtree_jtag_in__out;

    /////////////////////////////
    // Xtrigger Pad Bundle     //
    /////////////////////////////

    logic xtrig_nandtree_en, xtrig_nandtree_out;

    smc_xtrigger_pad_bundle #(
        .NUM_XTRIGGER           (smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS), // 4 xtrigger connections
        .XtriggerOrientationMap (smc_ip_integration_pkg::XtriggerOrientationMap) // Pad orientations
    ) u_xtrigger_pad_bundle (
        // Samsung GPIO IP Power and Reference signals
`ifdef POWER_PINS
        .VDD                    (VDD),
        .VDDO                   (VDDO),
        .VSS                    (VSS),
`endif
        .VSW                    (VSW_vdd_sys),
        .VREFN                  (VREFN_vdd_sys),
        .VREFP                  (VREFP_vdd_sys),
        .RTN                    (RTN_vdd_sys),
        .SPS                    (SPS_vdd_sys),

        // Xtrigger PAD connections
        .BP_XTRIG_REQ_OUT       (BP_XTRIG_REQ_OUT),
        .BP_XTRIG_REQ_IN        (BP_XTRIG_REQ_IN),
        .BP_XTRIG_ACK_IN        (BP_XTRIG_ACK_IN),
        .BP_XTRIG_ACK_OUT       (BP_XTRIG_ACK_OUT),

        // Direct pad control interface connections to ct_* signals
        .req_out_dout_i         (ct_req_out_dout_i),
        .req_out_dout_en_i      (ct_req_out_dout_en_i),
        .req_out_din_o          (ct_req_out_din_o),
        .req_out_din_en_i       (ct_req_out_din_en_i),

        .req_in_din_o           (ct_req_in_din_o),
        .req_in_din_en_i        (ct_req_in_din_en_i),

        .ack_in_din_o           (ct_ack_in_din_o),
        .ack_in_din_en_i        (ct_ack_in_din_en_i),

        .ack_out_dout_i         (ct_ack_out_dout_i),
        .ack_out_dout_en_i      (ct_ack_out_dout_en_i),
        .ack_out_din_o          (ct_ack_out_din_o),
        .ack_out_din_en_i       (ct_ack_out_din_en_i),

        // Nandtree interface
        .gpio_nandtree_enable_i (xtrig_nandtree_en),
        .gpio_nandtree_o        (xtrig_nandtree_out)
    );

    // Connect xtrigger nandtree to chain after JTAG outputs
    assign xtrig_nandtree_en = gpio_nandtree_jtag_out__out;
    assign gpio_nandtree_o = xtrig_nandtree_out;

    ////////////////////////////////////
    // Reference Clock and Reset Pads //
    ////////////////////////////////////

    // GPIO RefClk Control Register (at index 68)
    gpio_ctrl_reg_pkg::gpio_ctrl__in_t  gpio_refclk_ctrl_hwif_in;
    gpio_ctrl_reg_pkg::gpio_ctrl__out_t gpio_refclk_ctrl_hwif_out;

    // RefClk pad control signals derived from GPIO refclk control register
    logic pull_enable;
    logic pull_select;
    logic schmitt_select;

    gpio_ctrl_reg u_gpio_refclk_ctrl_reg (
        .clk                (clk_smc_i),
        .arst_n             (rst_primary_smc_clk_ni),

        // AXI4-Lite interface from demux
        .s_axil_awready     (axil_resps_ctrl_demux[68].aw_ready),
        .s_axil_awvalid     (axil_reqs_ctrl_demux[68].aw_valid),
        .s_axil_awaddr      (axil_reqs_ctrl_demux[68].aw.addr[2:0]),
        .s_axil_awprot      (axil_reqs_ctrl_demux[68].aw.prot),
        .s_axil_wready      (axil_resps_ctrl_demux[68].w_ready),
        .s_axil_wvalid      (axil_reqs_ctrl_demux[68].w_valid),
        .s_axil_wdata       (axil_reqs_ctrl_demux[68].w.data),
        .s_axil_wstrb       (axil_reqs_ctrl_demux[68].w.strb),
        .s_axil_bready      (axil_reqs_ctrl_demux[68].b_ready),
        .s_axil_bvalid      (axil_resps_ctrl_demux[68].b_valid),
        .s_axil_bresp       (axil_resps_ctrl_demux[68].b.resp),
        .s_axil_arready     (axil_resps_ctrl_demux[68].ar_ready),
        .s_axil_arvalid     (axil_reqs_ctrl_demux[68].ar_valid),
        .s_axil_araddr      (axil_reqs_ctrl_demux[68].ar.addr[2:0]),
        .s_axil_arprot      (axil_reqs_ctrl_demux[68].ar.prot),
        .s_axil_rready      (axil_reqs_ctrl_demux[68].r_ready),
        .s_axil_rvalid      (axil_resps_ctrl_demux[68].r_valid),
        .s_axil_rdata       (axil_resps_ctrl_demux[68].r.data),
        .s_axil_rresp       (axil_resps_ctrl_demux[68].r.resp),

        // Hardware interface
        .hwif_in            (gpio_refclk_ctrl_hwif_in),
        .hwif_out           (gpio_refclk_ctrl_hwif_out)
    );

    // Tie off hwif_in inputs (strap signals not used for refclk pads)
    assign gpio_refclk_ctrl_hwif_in.CONTROL.strap_valid.next = 1'b0;
    assign gpio_refclk_ctrl_hwif_in.CONTROL.strap_value.next = 1'b0;

    // Extract control signals for refclk pads
    assign pull_enable    = gpio_refclk_ctrl_hwif_out.CONTROL.pull_enable_n0_scan.value;
    assign pull_select    = gpio_refclk_ctrl_hwif_out.CONTROL.pull_select.value;
    assign schmitt_select = gpio_refclk_ctrl_hwif_out.CONTROL.schmitt_select.value;

    // These three top-level signals are input-only in the production wrapper.
    // Model the input pads as transparent connections in the OSS environment.
    assign refclk_vdd_sys = PAD_REFCLK;
    assign rst_cold_no    = PAD_PRSTN;
    assign powergood_o    = PAD_POWERGOOD;

    assign powergood_1p2_b = ~powergood_o;

    ////////////////////////////////
    // GPIO POC/PBIAS Controllers //
    ////////////////////////////////

    // OSS: no Samsung POC/PBIAS — tie reference signals for prim_pad_wrapper
    assign VSW_vdd_sys   = 1'b1;
    assign VREFN_vdd_sys = 1'b0;
    assign VREFP_vdd_sys = 1'b1;
    assign RTN_vdd_sys   = 1'b0;
    assign SPS_vdd_sys   = 1'b1;

    // Idle AXI-Lite for POC/PBIAS control register slice
    assign axil_resps_ctrl_demux[69].aw_ready = 1'b1;
    assign axil_resps_ctrl_demux[69].w_ready  = 1'b1;
    assign axil_resps_ctrl_demux[69].b_valid  =
        axil_reqs_ctrl_demux[69].aw_valid & axil_reqs_ctrl_demux[69].w_valid;
    assign axil_resps_ctrl_demux[69].b.resp   = 2'b00;
    assign axil_resps_ctrl_demux[69].ar_ready = 1'b1;
    assign axil_resps_ctrl_demux[69].r_valid  = axil_reqs_ctrl_demux[69].ar_valid;
    assign axil_resps_ctrl_demux[69].r.data   = '0;
    assign axil_resps_ctrl_demux[69].r.resp   = 2'b00;

    assign refclk_vdd_sys_o = refclk_vdd_sys;
    assign captured_straps_o = captured_straps;

endmodule