// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// GPIO Interface Shim Example

module gpio_shim
  import gpio_pkg::*;
  import gpio_shim_pkg::*;
#(
  parameter bit INPUT_BY_DEFAULT = 1'b1,
  parameter bit ENABLE_PULL = 1'b0,
  parameter bit USE_PULL_UP = 1'b0
) (
  input  logic        clk_i,
  input  logic        rst_primary_ni,
  input  logic        rst_cold_ni,
  input  logic        test_en_i,

  // GPIO request/response
  input  wire         core2pad_i,
  input  wire         core2pad_en_i,
  output wire         pad2core_o,
  input  wire         pad2core_en_i,

  // GPIO 2nd HW Function Override
  input  logic        core2pad_ovrd_i,
  input  logic        core2pad_en_ovrd_i,
  output logic        pad2core_ovrd_o,
  input  logic        pad2core_en_ovrd_i,

  // Safety preempt: when asserted, force the primary/normal plane regardless
  // of hw2_ovrd (e.g. CAT-THERM preempts a 2nd-HW-function override)
  input  logic        force_primary_i,

  // External GPIO Control
  input  logic        ext_intf_sel_i,
  input  logic        reg_lsio_sel_i,
  input  logic        reg_lsio_disable_i,
  input  logic [2:0]  ext_drive_strength_i,
  input  logic        ext_pull_en_i,
  input  logic        ext_pull_sel_i,
  input  logic        ext_gf_disable_i,

  // Strap
  output logic        captured_strap_o,

  // GPIO Hardware Interface
  input  logic                gpio_in_i,
  output logic                gpio_out_o,
  output logic                gpio_in_en_o,
  output logic                gpio_out_en_o,
  output gpio_model_ctrl_t    gpio_ctrl_o,
  input  gpio_model_status_t  gpio_status_i,


  // GPIO Register Interface
  // AXI4-Lite Register Interface
  input  gpio_axil_req_t  axil_req_i,
  output gpio_axil_resp_t axil_resp_o
);

  localparam int unsigned GPIO_REG_ADDR_WIDTH = $clog2(gpio_wrap_addrmap_pkg::GPIO_WRAP_SIZE);

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

  // Address decode: output[0] for register block, output[1] for error slave
  // Address is assumed to be greater than the GPIO_CTRL base address after passing the demux in gpio.sv
  always_comb begin
    if (axil_req_to_demux.aw.addr[GPIO_REG_ADDR_WIDTH-1:0] <= gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_BASE_ADDR + gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_SIZE) begin
      aw_select = 1'b0;
    end else begin
      aw_select = 1'b1;
    end

    if (axil_req_to_demux.ar.addr[GPIO_REG_ADDR_WIDTH-1:0] <= gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_BASE_ADDR + gpio_wrap_addrmap_pkg::GPIO_WRAP_GPIO_CTRL_SIZE) begin
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
  prim_axil_err_slv #(
    .AXI_DATA_WIDTH(gpio_pkg::DATA_WIDTH),
    .AXI_ADDR_WIDTH(gpio_pkg::ADDR_WIDTH),
    .axil_req_t(gpio_axil_req_t),
    .axil_resp_t(gpio_axil_resp_t)
  ) u_axil_err_slv (
    .clk_i(clk_i),
    .rst_ni(rst_primary_ni),
    .axil_req_i(axil_reqs_demuxed[1]),
    .axil_resp_o(axil_resps_demuxed[1])
  );

  gpio_ctrl_reg gpio_ctrl_reg (
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
    prim_latch_n strap_latch (
      .d_i(pad2core_o),
      .g_ni(rst_cold_ni),
      .q_o(captured_strap)
    );
  end else begin : gen_no_strap
    assign captured_strap = 1'b0;
  end

  assign captured_strap_o = captured_strap;

endmodule
