// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// System Timer OCTS
//
//-----------------------------------------------------------------------------

// Description: Top level wrapper for the System Timer OCTS


module system_timer_octs
  import system_timer_octs_pkg::*;
(
  // Global Interface
  input  logic                         clk_i,
  input  logic                         rst_ni,

  // Primary/Secondary mode select (runtime signal)
  input  logic                         is_primary_i,

  // AXI4-Lite Register Interface
  input  system_timer_octs_axil_req_t  axil_req_i,
  output system_timer_octs_axil_resp_t axil_resp_o,


  // OCTS Synchronization Interface
  input  logic                         timer_sync_load_i,
  input  logic                         timer_cnt_credit_i,
  output logic                         timer_sync_load_o,
  output logic                         timer_cnt_credit_o,

  // Timer Interface
  output logic [63:0]                  timer_count_o,

  // GPIO Interface
  output logic                         timer_gpio_enable_o,

  // Debug output
  output logic [8:0]                   cur_credits_debug_o,
  output logic                         credits_left_debug_o
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Register interface signals
  system_timer_octs_reg_pkg::system_timer_octs__in_t  hwif_in;
  system_timer_octs_reg_pkg::system_timer_octs__out_t hwif_out;

  // Register interface signals
  logic        start;
  logic [7:0]  credit_val;
  logic [7:0]  step;
  logic [31:0] preset_lo;
  logic [31:0] preset_hi;
  logic        mode;
  logic        running;
  logic [31:0] count_lo;
  logic [31:0] count_hi;
  logic [7:0]  pulse_width;
  logic [31:0] credit_expired;

  /////////////////////////
  // Timer Core Instance //
  /////////////////////////

  system_timer_octs_core u_timer_core (
    .clk_i                (clk_i),
    .rst_ni               (rst_ni),
    .is_primary_i         (is_primary_i),

    // Register interface
    .reg_start_i          (start),
    .reg_credit_val_i     (credit_val),
    .reg_preset_lo_i      (preset_lo),
    .reg_preset_hi_i      (preset_hi),
    .reg_pulse_width_i    (pulse_width),

    .reg_mode_o           (mode),
    .reg_running_o        (running),
    .reg_count_lo_o       (count_lo),
    .reg_count_hi_o       (count_hi),

    // OCTS synchronization signals
    .timer_sync_load_i    (timer_sync_load_i),
    .timer_cnt_credit_i   (timer_cnt_credit_i),
    .timer_sync_load_o    (timer_sync_load_o),
    .timer_cnt_credit_o   (timer_cnt_credit_o),

    // System Timer Counter signal (SECONDARY only)
    .timer_cnt_step_i     (step),

    // Credit expired counter (SECONDARY only)
    .credit_expired_o     (credit_expired),

    // Timer outputs
    .timer_count_o        (timer_count_o),

    // Debug outputs
    .cur_credits_debug_o  (cur_credits_debug_o),
    .credits_left_debug_o (credits_left_debug_o)
  );

  //////////////////////////
  // Credit Expired Logic //
  //////////////////////////

  logic rst_credit_expired;
  logic [31:0] credit_expired_value_d, credit_expired_value_q;

  assign credit_expired_value_d   = (credit_expired_value_q < credit_expired) ? credit_expired : credit_expired_value_q; // Max(credit_expired_value, credit_expired)
  assign rst_credit_expired       = hwif_out.CREDIT_EXPIRED.req & hwif_out.CREDIT_EXPIRED.req_is_wr; // If we get a write to this register, reset the value

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (~rst_ni) begin
      credit_expired_value_q <= 32'h0;
    end else begin
      if (rst_credit_expired) begin
        credit_expired_value_q <= 32'h0;
      end else begin
        credit_expired_value_q <= credit_expired_value_d;
      end
    end
  end

  assign hwif_in.CREDIT_EXPIRED.rd_data.MAX_CYCLES_EXPIRED = credit_expired_value_q;
  assign hwif_in.CREDIT_EXPIRED.wr_ack = hwif_out.CREDIT_EXPIRED.req & hwif_out.CREDIT_EXPIRED.req_is_wr;
  assign hwif_in.CREDIT_EXPIRED.rd_ack = hwif_out.CREDIT_EXPIRED.req & ~hwif_out.CREDIT_EXPIRED.req_is_wr;

  //////////
  // CSRs //
  //////////

  assign start                = hwif_out.TIMER_START.START.value;
  assign credit_val           = hwif_out.CTRL.CREDIT_VAL.value;
  assign pulse_width          = hwif_out.CTRL.PULSE_WIDTH.value;
  assign step                 = hwif_out.CTRL.STEP.value;
  assign preset_lo            = hwif_out.TIMER_PRESET_LO.PRESET_LO.value;
  assign preset_hi            = hwif_out.TIMER_PRESET_HI.PRESET_HI.value;
  assign timer_gpio_enable_o  = hwif_out.TIMER_GPIO_ENABLE.GPIO_ENABLE.value;

  assign hwif_in.STATUS.MODE.next             = mode;
  assign hwif_in.STATUS.RUNNING.next          = running;
  assign hwif_in.TIMER_COUNT_LO.COUNT_LO.next = count_lo;
  assign hwif_in.TIMER_COUNT_HI.COUNT_HI.next = count_hi;

  // Register Block
  system_timer_octs_reg u_reg (
    .clk            (clk_i),
    .arst_n         (rst_ni),

    .s_axil_awready (axil_resp_o.aw_ready),
    .s_axil_awvalid (axil_req_i.aw_valid),
    .s_axil_awaddr  (axil_req_i.aw.addr[
                             system_timer_octs_reg_pkg::SYSTEM_TIMER_OCTS_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_awprot  (axil_req_i.aw.prot),
    .s_axil_wready  (axil_resp_o.w_ready),
    .s_axil_wvalid  (axil_req_i.w_valid),
    .s_axil_wdata   (axil_req_i.w.data),
    .s_axil_wstrb   (axil_req_i.w.strb),
    .s_axil_bready  (axil_req_i.b_ready),
    .s_axil_bvalid  (axil_resp_o.b_valid),
    .s_axil_bresp   (axil_resp_o.b.resp),
    .s_axil_arready (axil_resp_o.ar_ready),
    .s_axil_arvalid (axil_req_i.ar_valid),
    .s_axil_araddr  (axil_req_i.ar.addr[
                             system_timer_octs_reg_pkg::SYSTEM_TIMER_OCTS_REG_MIN_ADDR_WIDTH-1:0
                         ]),
    .s_axil_arprot  (axil_req_i.ar.prot),
    .s_axil_rready  (axil_req_i.r_ready),
    .s_axil_rvalid  (axil_resp_o.r_valid),
    .s_axil_rdata   (axil_resp_o.r.data),
    .s_axil_rresp   (axil_resp_o.r.resp),

    .hwif_in        (hwif_in),
    .hwif_out       (hwif_out)
  );

endmodule
