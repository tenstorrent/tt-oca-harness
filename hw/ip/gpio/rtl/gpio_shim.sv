// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Shim a GPIO pad with 2nd-HW override, LSIO, strap capture, and model control.
//
// force_primary_i preempts hw2 override back to the primary plane (for example CAT-THERM
// over a 2nd-HW-function override).
// External drive, pull, and glitch-filter controls can override register settings when
// selected: the electrical controls come, in priority order, from the cold-reset defaults,
// the LSIO pin select, CONTROL.config_enable, then the LSIO software select.
// AXI-Lite addresses below the GPIO_CTRL base plus size reach the gpio_ctrl register block;
// the base-plus-size address and above receive DECERR from an error subordinate. Addresses
// below the base are decoded away upstream, so this shim bounds only the top of the aperture.
// While rst_cold_ni is low a latch follows the pad input, and it holds the strap value once
// rst_cold_ni rises.

module gpio_shim
  import gpio_pkg::gpio_axil_req_t;
  import gpio_pkg::gpio_axil_resp_t;
  import gpio_pkg::gpio_axil_aw_chan_t;
  import gpio_pkg::gpio_axil_w_chan_t;
  import gpio_pkg::gpio_axil_b_chan_t;
  import gpio_pkg::gpio_axil_ar_chan_t;
  import gpio_pkg::gpio_axil_r_chan_t;
  import gpio_shim_pkg::gpio_model_ctrl_t;
  import gpio_shim_pkg::gpio_model_status_t;
#(
  parameter bit INPUT_BY_DEFAULT = 1'b1,                    // Enables strap capture and drives
                                                            // CONTROL.strap_valid; when clear,
                                                            // captured_strap_o is tied low.
  parameter bit ENABLE_PULL = 1'b0,                         // Pull enable driven in cold reset and
                                                            // when no source owns the electrical
                                                            // controls.
  parameter bit USE_PULL_UP = 1'b0                          // Pull select driven in cold reset and
                                                            // when no source owns the electrical
                                                            // controls; 1 selects pull-up.
) (
  input  logic        clk_i,                                // System clock.
  input  logic        rst_primary_ni,                       // Primary async reset, active-low;
                                                            // resets the demux, error subordinate
                                                            // and register block.
  input  logic        rst_cold_ni,                          // Cold reset, active-low; forces the
                                                            // default electrical controls and opens
                                                            // the strap latch while low.
  input  logic        test_en_i,                            // DFT test enable, driven to the demux
                                                            // test input.

  input  wire         core2pad_i,                           // Primary core-to-pad data.
  input  wire         core2pad_en_i,                        // Primary core-to-pad enable.
  output wire         pad2core_o,                           // Pad input to the primary plane,
                                                            // driven from gpio_in_i whether or not
                                                            // the override is active.
  input  wire         pad2core_en_i,                        // Primary pad-to-core enable.

  input  logic        core2pad_ovrd_i,                      // 2nd-HW core-to-pad data, used while
                                                            // CONTROL.hw2_ovrd is set and
                                                            // force_primary_i is low.
  input  logic        core2pad_en_ovrd_i,                   // 2nd-HW core-to-pad enable.
  output logic        pad2core_ovrd_o,                      // 2nd-HW pad-to-core data; low while
                                                            // the override is inactive.
  input  logic        pad2core_en_ovrd_i,                   // 2nd-HW pad-to-core enable.

  input  logic        force_primary_i,                      // Force the primary plane over hw2
                                                            // override. Assert for safety preempt
                                                            // (e.g. CAT-THERM).

  input  logic        ext_intf_sel_i,                       // LSIO pin select; the ext_* controls
                                                            // take priority over the register
                                                            // settings unless reg_lsio_disable_i is
                                                            // set.
  input  logic        reg_lsio_sel_i,                       // Software LSIO select; applies the
                                                            // ext_* controls only when
                                                            // CONTROL.config_enable is clear.
  input  logic        reg_lsio_disable_i,                   // Register LSIO disable; blocks both
                                                            // LSIO selects.
  input  logic [2:0]  ext_drive_strength_i,                 // External drive strength.
  input  logic        ext_pull_en_i,                        // External pull enable.
  input  logic        ext_pull_sel_i,                       // External pull select.
  input  logic        ext_gf_disable_i,                     // Disable the glitch filter.

  output logic        captured_strap_o,                     // Pad input latched while rst_cold_ni
                                                            // is low; also read back as
                                                            // CONTROL.strap_value.

  input  logic                gpio_in_i,                    // Pad input level.
  output logic                gpio_out_o,                   // Pad output data.
  output logic                gpio_in_en_o,                 // Pad input enable.
  output logic                gpio_out_en_o,                // Pad output enable.
  output gpio_model_ctrl_t    gpio_ctrl_o,                  // Pad drive strength, pull and
                                                            // glitch-filter controls; sps is always
                                                            // low.
  input  gpio_model_status_t  gpio_status_i,                // Model status struct; unused.

  input  gpio_axil_req_t  axil_req_i,                       // AXI-Lite CSR request.
  output gpio_axil_resp_t axil_resp_o                       // AXI-Lite CSR response.
);

  localparam int unsigned GpioRegAddrWidth = $clog2(gpio_wrap_addrmap_pkg::GPIO_WRAP_SIZE);

  // GPIO Control Register hardware interface
  gpio_ctrl_reg_pkg::gpio_ctrl__in_t gpio_ctrl_hwif_in;
  gpio_ctrl_reg_pkg::gpio_ctrl__out_t gpio_ctrl_hwif_out;



  // Decode logic for err slv

  gpio_axil_req_t  axil_req_to_demux;
  gpio_axil_resp_t axil_resp_from_demux;

  gpio_axil_req_t  [1:0] axil_reqs_demuxed;
  gpio_axil_resp_t [1:0] axil_resps_demuxed;

  assign axil_req_to_demux = axil_req_i;
  assign axil_resp_o = axil_resp_from_demux;

  logic aw_select;
  logic ar_select;

  // Address decode: output[0] for register block, output[1] for error slave.
  // The upstream fabric routes only addresses at or above the GPIO_CTRL base to this shim, so
  // the ctrl aperture is the half-open range [base, base+size); base+size and above are out of
  // range and route to the error subordinate.
  always_comb begin
    if (axil_req_to_demux.aw.addr[GpioRegAddrWidth-1:0] < gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_BASE_ADDR + gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_SIZE) begin
      aw_select = 1'b0;
    end else begin
      aw_select = 1'b1;
    end

    if (axil_req_to_demux.ar.addr[GpioRegAddrWidth-1:0] < gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_BASE_ADDR + gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_SIZE) begin
      ar_select = 1'b0;
    end else begin
      ar_select = 1'b1;
    end
  end

  axi_lite_demux #(
    .aw_chan_t   (gpio_axil_aw_chan_t),
    .w_chan_t    (gpio_axil_w_chan_t),
    .b_chan_t    (gpio_axil_b_chan_t),
    .ar_chan_t   (gpio_axil_ar_chan_t),
    .r_chan_t    (gpio_axil_r_chan_t),
    .axi_req_t   (gpio_axil_req_t),
    .axi_resp_t  (gpio_axil_resp_t),
    .NoMstPorts  (2),
    .MaxTrans    (1),
    .FallThrough (1'b0),
    .SpillAw     (1'b0),
    .SpillW      (1'b0),
    .SpillB      (1'b0),
    .SpillAr     (1'b0),
    .SpillR      (1'b0)
  ) u_shim_axil_demux (
    .clk_i(clk_i),
    .rst_ni(rst_primary_ni),
    .test_i(test_en_i),
    .slv_req_i(axil_req_to_demux),
    .slv_aw_select_i(aw_select),
    .slv_ar_select_i(ar_select),
    .slv_resp_o(axil_resp_from_demux),
    .mst_reqs_o(axil_reqs_demuxed),
    .mst_resps_i(axil_resps_demuxed)
  );

  // Connect demuxed port [1] to AXI-Lite error slave
  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH(gpio_pkg::AddrWidth),
    .AXI_DATA_WIDTH(gpio_pkg::DataWidth),
    .axil_req_t(gpio_axil_req_t),
    .axil_resp_t(gpio_axil_resp_t),
    .RESP(axi_pkg::RESP_DECERR),
    .RESP_WIDTH(gpio_pkg::DataWidth),
    .RESP_DATA(32'hBADCAB1E),
    .MAX_TRANS(1)
  ) u_axil_err_slv (
    .clk_i(clk_i),
    .rst_ni(rst_primary_ni),
    .axil_req_i(axil_reqs_demuxed[1]),
    .axil_resp_o(axil_resps_demuxed[1])
  );

  gpio_ctrl_reg u_gpio_ctrl_reg (
    .clk(clk_i),
    .arst_n(rst_primary_ni),

    .s_axil_awready(axil_resps_demuxed[0].aw_ready),
    .s_axil_awvalid(axil_reqs_demuxed[0].aw_valid),
    .s_axil_awaddr(axil_reqs_demuxed[0].aw.addr[2:0]),
    .s_axil_awprot(axil_reqs_demuxed[0].aw.prot),
    .s_axil_wready(axil_resps_demuxed[0].w_ready),
    .s_axil_wvalid(axil_reqs_demuxed[0].w_valid),
    .s_axil_wdata(axil_reqs_demuxed[0].w.data),
    .s_axil_wstrb(axil_reqs_demuxed[0].w.strb),
    .s_axil_bready(axil_reqs_demuxed[0].b_ready),
    .s_axil_bvalid(axil_resps_demuxed[0].b_valid),
    .s_axil_bresp(axil_resps_demuxed[0].b.resp),
    .s_axil_arready(axil_resps_demuxed[0].ar_ready),
    .s_axil_arvalid(axil_reqs_demuxed[0].ar_valid),
    .s_axil_araddr(axil_reqs_demuxed[0].ar.addr[2:0]),
    .s_axil_arprot(axil_reqs_demuxed[0].ar.prot),
    .s_axil_rready(axil_reqs_demuxed[0].r_ready),
    .s_axil_rvalid(axil_resps_demuxed[0].r_valid),
    .s_axil_rdata(axil_resps_demuxed[0].r.data),
    .s_axil_rresp(axil_resps_demuxed[0].r.resp),
    .hwif_in(gpio_ctrl_hwif_in),
    .hwif_out(gpio_ctrl_hwif_out)
  );

  // Register signals from gpio_ctrl_reg hwif_out structure
  logic [2:0] reg__drive_strength;
  logic reg__pull_enable;
  logic reg__pull_select;
  logic reg__schmitt_select;
  logic reg__config_enable;

  // Secondary HW function MUXed signals
  logic core2pad_muxed;
  logic core2pad_en_muxed;
  logic pad2core_muxed;
  logic pad2core_en_muxed;

  // Connect gpio_ctrl_reg hwif_out to internal signals
  assign reg__drive_strength = gpio_ctrl_hwif_out.CONTROL.drive_strength.value;
  assign reg__pull_enable = gpio_ctrl_hwif_out.CONTROL.pull_enable_n0_scan.value;
  assign reg__pull_select = gpio_ctrl_hwif_out.CONTROL.pull_select.value;
  assign reg__schmitt_select = gpio_ctrl_hwif_out.CONTROL.schmitt_select.value;
  assign reg__config_enable = gpio_ctrl_hwif_out.CONTROL.config_enable.value;

  assign gpio_ctrl_hwif_in.CONTROL.strap_valid.next = INPUT_BY_DEFAULT;
  assign gpio_ctrl_hwif_in.CONTROL.strap_value.next = captured_strap_o;

  // GPIO 2nd HW Function Override MUXing
  // Note: it is the responsibility of the adopter to ensure enabling secondary function is safe with the primary function
  always_comb begin
    if (gpio_ctrl_hwif_out.CONTROL.hw2_ovrd.value && !force_primary_i) begin
      core2pad_muxed = core2pad_ovrd_i;
      core2pad_en_muxed = core2pad_en_ovrd_i;
      pad2core_en_muxed = pad2core_en_ovrd_i;
      pad2core_ovrd_o = pad2core_muxed;
    end else begin
      core2pad_muxed = core2pad_i;
      core2pad_en_muxed = core2pad_en_i;
      pad2core_en_muxed = pad2core_en_i;
      pad2core_ovrd_o = 1'b0;
    end
  end

  assign pad2core_o = pad2core_muxed;

  // Electrical-attribute ownership, ranked to match the data/enable mux in
  // gpio.sv: hardware LSIO request, then the CSR plane, then software-forced LSIO.
  logic lsio_pin, lsio_sw;
  assign lsio_pin = ext_intf_sel_i && ~reg_lsio_disable_i;
  assign lsio_sw  = reg_lsio_sel_i && ~reg_lsio_disable_i;

  always_comb begin
    gpio_ctrl_o.gpio_drive_strength = 3'b010; // default taken from RDL
    gpio_ctrl_o.gpio_pull_en = ENABLE_PULL;
    gpio_ctrl_o.gpio_pull_sel = USE_PULL_UP;
    gpio_ctrl_o.gpio_sps = 1'b0; // default inactive
    gpio_ctrl_o.gpio_glitch_filter_enable = 1'b1; // enabled by default, meaning GPIO uses a Schmitt trigger

    if (~rst_cold_ni) begin
      gpio_ctrl_o.gpio_drive_strength = 3'b010; // default taken from RDL
      gpio_ctrl_o.gpio_pull_en = ENABLE_PULL;
      gpio_ctrl_o.gpio_pull_sel = USE_PULL_UP;
      gpio_ctrl_o.gpio_sps = 1'b0;
      gpio_ctrl_o.gpio_glitch_filter_enable = 1'b1;
    end else if (lsio_pin) begin  // LSIO HW determines settings
      gpio_ctrl_o.gpio_drive_strength = ext_drive_strength_i;
      gpio_ctrl_o.gpio_pull_en = ext_pull_en_i;
      gpio_ctrl_o.gpio_pull_sel = ext_pull_sel_i;
      gpio_ctrl_o.gpio_sps = 1'b0; // maintain default
      gpio_ctrl_o.gpio_glitch_filter_enable = ~ext_gf_disable_i;
    end else if (reg__config_enable) begin  // CSR interface determines settings
      gpio_ctrl_o.gpio_drive_strength = reg__drive_strength;
      gpio_ctrl_o.gpio_pull_en = reg__pull_enable;
      gpio_ctrl_o.gpio_pull_sel = reg__pull_select;
      gpio_ctrl_o.gpio_sps = 1'b0; // maintain default
      gpio_ctrl_o.gpio_glitch_filter_enable = reg__schmitt_select;
    end else if (lsio_sw) begin  // software-forced LSIO
      gpio_ctrl_o.gpio_drive_strength = ext_drive_strength_i;
      gpio_ctrl_o.gpio_pull_en = ext_pull_en_i;
      gpio_ctrl_o.gpio_pull_sel = ext_pull_sel_i;
      gpio_ctrl_o.gpio_sps = 1'b0; // maintain default
      gpio_ctrl_o.gpio_glitch_filter_enable = ~ext_gf_disable_i;
    end
  end
  assign gpio_out_o = core2pad_muxed;
  assign gpio_out_en_o = core2pad_en_muxed;
  assign pad2core_muxed = gpio_in_i;
  assign gpio_in_en_o = pad2core_en_muxed;

  //---------------//
  // STRAP CAPTURE //
  //---------------//

  logic captured_strap;

  if (INPUT_BY_DEFAULT) begin : gen_capture_strap
    prim_latch_n u_strap_latch (
      .d_i(pad2core_o),
      .g_ni(rst_cold_ni),
      .q_o(captured_strap)
    );
  end else begin : gen_no_strap
    assign captured_strap = 1'b0;
  end

  assign captured_strap_o = captured_strap;

endmodule
