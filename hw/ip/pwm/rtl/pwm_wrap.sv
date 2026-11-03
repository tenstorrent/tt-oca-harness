// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the OpenTitan PWM and its pad-control register behind one AXI-Lite port.
//
// The AXI-Lite slave is demuxed onto three ports: the PWM register map, the CTRL register map and
// an error slave that answers DECERR with read data 0xBADCAB1E for every other address. PWM
// accesses are rebased by subtracting REG_MAP_BASE_ADDR and bridged to the PWM TL-UL port.
// CTRL.PAD_EN drives pad_en_o, one bit per channel; it does not gate the PWM itself. The demux,
// the bridge, CTRL, the alert receiver and the PWM register interface run on clk_i; clk_core_i
// clocks the PWM phase counters and channel outputs. fatal_alert_o aggregates the fatal alert
// pulse with integ_fail of all alert channels. RACL is compiled out.
//
// The register layout depends on NUM_OUTPUTS. Static assertions check that the generated map
// handed in through REG_MAP_SIZE and the *_REG_OFFSET parameters matches the layout of the
// PWM built here, that the generated CTRL.PAD_EN has NUM_OUTPUTS bits, and that both map bases
// are aligned to their block sizes.

`include "ocah_assert.svh"

module pwm_wrap #(
  parameter int unsigned NUM_OUTPUTS            = 4,      // Number of PWM channels; 1 to 32.
  parameter logic [31:0] REG_MAP_BASE_ADDR      = '0,     // Base address of the PWM registers,
                                                          // subtracted from AW and AR addresses;
                                                          // aligned to the PWM block size.
  parameter logic [31:0] REG_MAP_SIZE           = '0,     // Size of the generated PWM register
                                                          // map in bytes.
  parameter logic [31:0] CTRL_REG_MAP_BASE_ADDR = '0,     // Base address of the CTRL register
                                                          // map; aligned to its block size.
  parameter logic [31:0] CTRL_REG_MAP_SIZE      = '0,     // Size of the generated CTRL register
                                                          // map in bytes.
  parameter logic [31:0] PWM_PARAM_REG_OFFSET   = '0,     // Offset of PWM_PARAM_0 in the
                                                          // generated map.
  parameter logic [31:0] DUTY_CYCLE_REG_OFFSET  = '0,     // Offset of DUTY_CYCLE_0 in the
                                                          // generated map.
  parameter logic [31:0] BLINK_PARAM_REG_OFFSET = '0,     // Offset of BLINK_PARAM_0 in the
                                                          // generated map.
  parameter type         axil_aw_chan_t         = logic,  // 32-bit AXI-Lite AW channel type.
  parameter type         axil_w_chan_t          = logic,  // 32-bit AXI-Lite W channel type.
  parameter type         axil_b_chan_t          = logic,  // 32-bit AXI-Lite B channel type.
  parameter type         axil_ar_chan_t         = logic,  // 32-bit AXI-Lite AR channel type.
  parameter type         axil_r_chan_t          = logic,  // 32-bit AXI-Lite R channel type.
  parameter type         axil_req_t             = logic,  // 32-bit AXI-Lite request type.
  parameter type         axil_resp_t            = logic   // 32-bit AXI-Lite response type.
) (
  input  logic                   clk_i,            // Register interface clock.
  input  logic                   rst_ni,           // Register interface reset, active-low,
                                                   // synchronized to clk_i.
  input  logic                   clk_core_i,       // PWM counter clock; may be asynchronous to
                                                   // clk_i.
  input  logic                   rst_core_ni,      // PWM counter reset, active-low,
                                                   // synchronized to clk_core_i.
  input  logic                   test_en_i,        // DFT test mode to the AXI cells.

  input  axil_req_t              csr_axil_req_i,   // AXI-Lite slave for the PWM and CTRL
                                                   // registers, at system addresses.
  output axil_resp_t             csr_axil_resp_o,  // Response on the register slave.

  output logic [NUM_OUTPUTS-1:0] pad_en_o,         // CTRL.PAD_EN, one bit per channel, on
                                                   // clk_i; resets to 0.

  output logic [NUM_OUTPUTS-1:0] pwm_o,            // PWM channel outputs, from the clk_core_i
                                                   // domain.
  output logic [NUM_OUTPUTS-1:0] pwm_en_o,         // PWM channel output enables, from the
                                                   // clk_core_i domain.
  output logic                   fatal_alert_o     // Aggregated fatal alert (alert pulse |
                                                   // integ_fail of all alert channels).
);

  localparam int unsigned NumAlerts = pwm_reg_pkg::NumAlerts;

  // Demux ports: PWM, CTRL and the error slave.
  localparam int unsigned NumRegMaps = 3;
  typedef logic [$clog2(NumRegMaps)-1:0] reg_map_select_t;
  localparam reg_map_select_t PwmRegMap = reg_map_select_t'(0);
  localparam reg_map_select_t CtrlRegMap = reg_map_select_t'(1);
  localparam reg_map_select_t UndefinedRegMap = reg_map_select_t'(2);

  `OCAH_ASSERT_STATIC(
      PwmRegMapSize_A, REG_MAP_SIZE == 4 * pwm_reg_pkg::pwm_num_regs(NUM_OUTPUTS),
      "REG_MAP_SIZE does not match NUM_OUTPUTS; NUM_OUTPUTS must equal the RDL N_OUTPUTS, regenerate the register map")
  `OCAH_ASSERT_STATIC(
      PwmParamRegOffset_A, PWM_PARAM_REG_OFFSET == pwm_reg_pkg::pwm_pwm_param_offset(),
      "PWM_PARAM_REG_OFFSET does not match the register package; regenerate the register map from the RDL")
  `OCAH_ASSERT_STATIC(
      PwmDutyCycleRegOffset_A, DUTY_CYCLE_REG_OFFSET == pwm_reg_pkg::pwm_duty_cycle_offset(
      NUM_OUTPUTS),
      "DUTY_CYCLE_REG_OFFSET does not match NUM_OUTPUTS; NUM_OUTPUTS must equal the RDL N_OUTPUTS, regenerate the register map")
  `OCAH_ASSERT_STATIC(
      PwmBlinkParamRegOffset_A, BLINK_PARAM_REG_OFFSET == pwm_reg_pkg::pwm_blink_param_offset(
      NUM_OUTPUTS),
      "BLINK_PARAM_REG_OFFSET does not match NUM_OUTPUTS; NUM_OUTPUTS must equal the RDL N_OUTPUTS, regenerate the register map")
  `OCAH_ASSERT_STATIC(
      PwmRegMapBaseAligned_A, REG_MAP_BASE_ADDR % (32'd1 << pwm_reg_pkg::pwm_block_aw(NUM_OUTPUTS
      )) == 0,
      "REG_MAP_BASE_ADDR is not aligned to the PWM register block size; place the PWM window on a block-size boundary in the RDL")
  `OCAH_ASSERT_STATIC(
      PwmPadEnWidth_A, $bits(pwm_ctrl_reg_pkg::pwm_ctrl__CTRL__PAD_EN__out_t) == NUM_OUTPUTS,
      "CTRL.PAD_EN width does not match NUM_OUTPUTS; NUM_OUTPUTS must equal the RDL N_OUTPUTS, regenerate the register map")
  `OCAH_ASSERT_STATIC(
      PwmCtrlRegMapSize_A, CTRL_REG_MAP_SIZE == pwm_ctrl_reg_pkg::PWM_CTRL_REG_SIZE,
      "CTRL_REG_MAP_SIZE does not match the register package; regenerate the register map from the RDL")
  `OCAH_ASSERT_STATIC(
      PwmCtrlRegMapBaseAligned_A,
      CTRL_REG_MAP_BASE_ADDR % (32'd1 << pwm_ctrl_reg_pkg::PWM_CTRL_REG_MIN_ADDR_WIDTH) == 0,
      "CTRL_REG_MAP_BASE_ADDR is not aligned to the CTRL register block size; place the CTRL map on a block-size boundary in the RDL")

  ///////////
  // Demux //
  ///////////

  function automatic reg_map_select_t reg_map_select(logic [31:0] addr);
    if (addr >= REG_MAP_BASE_ADDR && addr < REG_MAP_BASE_ADDR + REG_MAP_SIZE) begin
      return PwmRegMap;
    end
    if (addr >= CTRL_REG_MAP_BASE_ADDR && addr < CTRL_REG_MAP_BASE_ADDR + CTRL_REG_MAP_SIZE) begin
      return CtrlRegMap;
    end
    return UndefinedRegMap;
  endfunction

  axil_req_t  [NumRegMaps-1:0] axil_reqs;
  axil_resp_t [NumRegMaps-1:0] axil_resps;

  axi_lite_demux #(
    .aw_chan_t       (axil_aw_chan_t),
    .w_chan_t        (axil_w_chan_t),
    .b_chan_t        (axil_b_chan_t),
    .ar_chan_t       (axil_ar_chan_t),
    .r_chan_t        (axil_r_chan_t),
    .axi_req_t       (axil_req_t),
    .axi_resp_t      (axil_resp_t),
    .NoMstPorts      (NumRegMaps),
    .MaxTrans        (1),
    .FallThrough     (1'b0),
    .SpillAw         (1'b1),
    .SpillW          (1'b0),
    .SpillB          (1'b0),
    .SpillAr         (1'b1),
    .SpillR          (1'b0)
  ) u_axi_lite_demux (
    .clk_i,
    .rst_ni,
    .test_i          (test_en_i),
    .slv_req_i       (csr_axil_req_i),
    .slv_aw_select_i (reg_map_select(csr_axil_req_i.aw.addr)),
    .slv_ar_select_i (reg_map_select(csr_axil_req_i.ar.addr)),
    .slv_resp_o      (csr_axil_resp_o),
    .mst_reqs_o      (axil_reqs),
    .mst_resps_i     (axil_resps)
  );

  prim_axi_lite_err_slv #(
    .AXI_ADDR_WIDTH (32),
    .AXI_DATA_WIDTH (32),
    .axil_req_t     (axil_req_t),
    .axil_resp_t    (axil_resp_t),
    .RESP           (axi_pkg::RESP_DECERR),
    .RESP_WIDTH     (32),
    .RESP_DATA      (32'hBADCAB1E),
    .MAX_TRANS      (1)
  ) u_prim_axi_lite_err_slv (
    .clk_i,
    .rst_ni,
    .test_en_i,
    .axil_req_i     (axil_reqs [UndefinedRegMap]),
    .axil_resp_o    (axil_resps[UndefinedRegMap])
  );

  /////////
  // PWM //
  /////////

  axil_req_t csr_axil_req_offset;

  always_comb begin
    csr_axil_req_offset         = axil_reqs[PwmRegMap];
    csr_axil_req_offset.ar.addr = axil_reqs[PwmRegMap].ar.addr - REG_MAP_BASE_ADDR;
    csr_axil_req_offset.aw.addr = axil_reqs[PwmRegMap].aw.addr - REG_MAP_BASE_ADDR;
  end

  tlul_pkg::tl_h2d_t tl_h2d;
  tlul_pkg::tl_d2h_t tl_d2h;

  axi_lite_to_tlul #(
    .axi_lite_req_t (axil_req_t),
    .axi_lite_rsp_t (axil_resp_t)
  ) u_axi_lite_to_tlul (
    .clk_i          (clk_i),
    .rst_ni         (rst_ni),
    .axi_lite_req_i (csr_axil_req_offset),
    .axi_lite_rsp_o (axil_resps[PwmRegMap]),
    .tl_o           (tl_h2d),
    .tl_i           (tl_d2h),
    .err_o          (/* UNUSED */),
    .err_clr_i      (1'b0)
  );

  prim_alert_pkg::alert_tx_t [NumAlerts-1:0] alert_tx;
  prim_alert_pkg::alert_rx_t [NumAlerts-1:0] alert_rx;
  logic [NumAlerts-1:0]                      alert_pulse;
  logic [NumAlerts-1:0]                      alert_integ_fail;

  pwm #(
    .NOutputs     (NUM_OUTPUTS),
    .AlertAsyncOn (1'b0),
    .EnableRacl   (1'b0)
  ) u_pwm (
    .clk_i           (clk_i),
    .rst_ni          (rst_ni),
    .clk_core_i      (clk_core_i),
    .rst_core_ni     (rst_core_ni),
    .tl_i            (tl_h2d),
    .tl_o            (tl_d2h),
    .alert_rx_i      (alert_rx),
    .alert_tx_o      (alert_tx),
    .racl_policies_i ('0),
    .racl_error_o    (/* UNUSED */),
    .cio_pwm_o       (pwm_o),
    .cio_pwm_en_o    (pwm_en_o)
  );

  for (genvar i = 0; i < NumAlerts; i++) begin : gen_alert_receivers
    prim_alert_receiver #(
      .AsyncOn    (1'b0),
      .SkewCycles (1)
    ) u_alert_receiver (
      .clk_i,
      .rst_ni,
      .init_trig_i  (prim_mubi_pkg::MuBi4False),
      .ping_req_i   (1'b0),
      .ping_ok_o    (),
      .integ_fail_o (alert_integ_fail[i]),
      .alert_o      (alert_pulse[i]),
      .alert_rx_o   (alert_rx[i]),
      .alert_tx_i   (alert_tx[i])
    );
  end

  assign fatal_alert_o = (|alert_pulse) | (|alert_integ_fail);

  //////////
  // CTRL //
  //////////

  localparam int unsigned CtrlAddrWidth = pwm_ctrl_reg_pkg::PWM_CTRL_REG_MIN_ADDR_WIDTH;

  pwm_ctrl_reg_pkg::pwm_ctrl__out_t ctrl_reg_out;

  pwm_ctrl_reg u_pwm_ctrl_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resps[CtrlRegMap].aw_ready),
    .s_axil_awvalid (axil_reqs [CtrlRegMap].aw_valid),
    .s_axil_awaddr  (axil_reqs [CtrlRegMap].aw.addr[CtrlAddrWidth-1:0]),
    .s_axil_awprot  (axil_reqs [CtrlRegMap].aw.prot),
    .s_axil_wready  (axil_resps[CtrlRegMap].w_ready),
    .s_axil_wvalid  (axil_reqs [CtrlRegMap].w_valid),
    .s_axil_wdata   (axil_reqs [CtrlRegMap].w.data),
    .s_axil_wstrb   (axil_reqs [CtrlRegMap].w.strb),
    .s_axil_bready  (axil_reqs [CtrlRegMap].b_ready),
    .s_axil_bvalid  (axil_resps[CtrlRegMap].b_valid),
    .s_axil_bresp   (axil_resps[CtrlRegMap].b.resp),
    .s_axil_arready (axil_resps[CtrlRegMap].ar_ready),
    .s_axil_arvalid (axil_reqs [CtrlRegMap].ar_valid),
    .s_axil_araddr  (axil_reqs [CtrlRegMap].ar.addr[CtrlAddrWidth-1:0]),
    .s_axil_arprot  (axil_reqs [CtrlRegMap].ar.prot),
    .s_axil_rready  (axil_reqs [CtrlRegMap].r_ready),
    .s_axil_rvalid  (axil_resps[CtrlRegMap].r_valid),
    .s_axil_rdata   (axil_resps[CtrlRegMap].r.data),
    .s_axil_rresp   (axil_resps[CtrlRegMap].r.resp),

    .hwif_out       (ctrl_reg_out)
  );

  assign pad_en_o = ctrl_reg_out.CTRL.PAD_EN.value;

endmodule : pwm_wrap
