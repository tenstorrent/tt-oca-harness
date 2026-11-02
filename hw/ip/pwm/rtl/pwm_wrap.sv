// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Wrap the OpenTitan PWM with an AXI-Lite register interface.
//
// The AXI-Lite slave is rebased by subtracting REG_MAP_BASE_ADDR and bridged to the PWM TL-UL
// port. The bridge, the alert receiver and the PWM register interface run on clk_i; clk_core_i
// clocks the PWM phase counters and channel outputs. fatal_alert_o aggregates the fatal alert
// pulse with integ_fail of all alert channels. RACL is compiled out.
//
// The register layout depends on NUM_OUTPUTS. Static assertions check that the generated map
// handed in through REG_MAP_SIZE and the *_REG_OFFSET parameters matches the layout of the
// PWM built here, and that REG_MAP_BASE_ADDR is aligned to the PWM block size.

`include "ocah_assert.svh"

module pwm_wrap #(
  parameter int unsigned NUM_OUTPUTS            = 4,      // Number of PWM channels; 1 to 32.
  parameter logic [31:0] REG_MAP_BASE_ADDR      = '0,     // Base address of the PWM registers,
                                                          // subtracted from AW and AR addresses;
                                                          // aligned to the PWM block size.
  parameter logic [31:0] REG_MAP_SIZE           = '0,     // Size of the generated PWM register
                                                          // map in bytes.
  parameter logic [31:0] PWM_PARAM_REG_OFFSET   = '0,     // Offset of PWM_PARAM_0 in the
                                                          // generated map.
  parameter logic [31:0] DUTY_CYCLE_REG_OFFSET  = '0,     // Offset of DUTY_CYCLE_0 in the
                                                          // generated map.
  parameter logic [31:0] BLINK_PARAM_REG_OFFSET = '0,     // Offset of BLINK_PARAM_0 in the
                                                          // generated map.
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
  input  logic                   test_en_i,        // DFT test-mode enable; unused.

  input  axil_req_t              csr_axil_req_i,   // AXI-Lite slave for the PWM registers, at
                                                   // system addresses.
  output axil_resp_t             csr_axil_resp_o,  // Response on the PWM register slave.

  output logic [NUM_OUTPUTS-1:0] pwm_o,            // PWM channel outputs, from the clk_core_i
                                                   // domain.
  output logic [NUM_OUTPUTS-1:0] pwm_en_o,         // PWM channel output enables, from the
                                                   // clk_core_i domain.
  output logic                   fatal_alert_o     // Aggregated fatal alert (alert pulse |
                                                   // integ_fail of all alert channels).
);

  localparam int unsigned NumAlerts = pwm_reg_pkg::NumAlerts;

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

  axil_req_t csr_axil_req_offset;

  always_comb begin
    csr_axil_req_offset         = csr_axil_req_i;
    csr_axil_req_offset.ar.addr = csr_axil_req_i.ar.addr - REG_MAP_BASE_ADDR;
    csr_axil_req_offset.aw.addr = csr_axil_req_i.aw.addr - REG_MAP_BASE_ADDR;
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
    .axi_lite_rsp_o (csr_axil_resp_o),
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

  logic unused_test_en;
  assign unused_test_en = test_en_i;

endmodule : pwm_wrap
