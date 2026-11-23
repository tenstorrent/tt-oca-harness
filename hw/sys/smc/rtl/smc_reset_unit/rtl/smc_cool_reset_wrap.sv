// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Generate the FLR cool reset and the subsystem isolation requests.
//
// On a rising edge of isolate_sequence_trigger_i, counts down ISOLATE_REQ_FLR_COUNTER_VALUE
// reference clock cycles, then holds rst_cool_no low while counting down
// ISOLATE_REQ_FLR_RESET_COUNTER_VALUE cycles; no sequence starts while the reset count is
// zero. The first count ends early once isolate_req_ack_i is high for every subsystem
// enabled in ISOLATE_REQ_SMCEN_REG and at least one is enabled.
// Records the cause of each cool reset and, for a sequence, the acknowledges it saw, in
// ISOLATE_REQ_VIS and ISOLATE_REQ_ACK_CAPTURE. Those and the ISOLATE_REQ_* registers are
// reset only by the cold reset, so they survive the cool reset.

`include "ocah_registers.svh"

module smc_cool_reset_wrap (
  input  logic                                   clk_ref_i,  // Reference clock for the FLR counters
                                                             // and rst_cool_no.
  input  logic                                   rst_cold_ref_ni,  // Stable cold reset, active-low,
                                                                   // synchronized to clk_ref_i;
                                                                   // resets the FLR counters and
                                                                   // releases rst_cool_no.
  input  logic                                   rst_primary_ref_ni,  // Primary reset, active-low,
                                                                      // synchronized to clk_ref_i;
                                                                      // clears the isolate_req_ack_i
                                                                      // synchronizer, so the cool
                                                                      // reset discards acknowledges
                                                                      // from the sequence that caused
                                                                      // it.

  input  logic                                   clk_smc_i,  // SMC core clock for the ISOLATE_REQ_*
                                                             // registers and input synchronizers.
  input  logic                                   rst_cold_smc_ni,  // Stable cold reset, active-low,
                                                                   // synchronized to clk_smc_i;
                                                                   // resets the ISOLATE_REQ_*
                                                                   // registers.

  input  reset_unit_reg_pkg::reset_unit__out_t   hwif_out_i,  // Reset-unit register outputs: the
                                                              // access strobes and write data of
                                                              // the external ISOLATE_REQ_*
                                                              // registers.
  output reset_unit_reg_pkg::reset_unit__in_t    hwif_in_o,  // Reset-unit register inputs for
                                                             // ISOLATE_REQ_VIS and the external
                                                             // ISOLATE_REQ_* registers; every other
                                                             // field is zero.

  input  logic                                   isolate_req_pin_i,  // Isolation request pin,
                                                                     // active-high, synchronized to
                                                                     // clk_smc_i; raises the
                                                                     // isolate_req_o bits enabled in
                                                                     // ISOLATE_REQ_PINEN_REG and
                                                                     // preserves that register across
                                                                     // cold reset while high.
  input  logic                                   isolate_sequence_trigger_i,  // Isolation sequence
                                                                              // trigger, active-high,
                                                                              // from any cause such as a
                                                                              // PCIe function-level reset;
                                                                              // its synchronized rising
                                                                              // edge sets ISOLATE_REQ_SMC
                                                                              // and starts the FLR counters.
  input  logic [31:0]                            isolate_req_ack_i,  // Isolation acknowledge, one bit
                                                                     // per isolate_req_o bit, active-high,
                                                                     // asynchronous: subsystem i has
                                                                     // nothing in flight across its
                                                                     // boundary. Must fall before
                                                                     // isolate_req_o[i] does.
  input  logic                                   rst_cool_pin_stable_ni,  // De-glitched cool reset
                                                                          // pin, active-low, on
                                                                          // clk_ref_i; a fall while
                                                                          // rst_cool_no is high is
                                                                          // recorded as a pin cool
                                                                          // reset.
  output logic [31:0]                            isolate_req_o,  // Controls isolation of
                                                                 // subsystems like PCIe
                                                                 // and/or ETH during FLR:
                                                                 // ISOLATE_REQ_REG, OR the
                                                                 // pin-enabled bits while the
                                                                 // pin is high, OR the
                                                                 // SMCEN-enabled bits while
                                                                 // ISOLATE_REQ_SMC is set.
  output logic                                   skip_mem_repair_o,  // Signal to skip
                                                                     // memory repair &
                                                                     // MBIST during FLR; high
                                                                     // while the pin or
                                                                     // ISOLATE_REQ_SMC is set.
  output logic                                   rst_cool_no  // FLR cool reset, active-low, on
                                                              // clk_ref_i.
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Register Interface Signals
  logic                        isolate_req_pin_sync_smc;
  logic                        isolate_sequence_trigger_sync_smc;
  logic                        isolate_sequence_trigger_sync_ref;

  logic [31:0]                 isolate_req_ack_sync_ref;
  logic [31:0]                 isolate_req_smcen_ref_clk;

  // Cool reset record, written on clk_ref_i and read on clk_smc_i.
  typedef struct packed {
    reset_unit_reg_pkg::reset_unit__cool_reset_cause_enum_e cause;
    logic [31:0]                                            ack_capture;
  } cool_reset_record_t;

  cool_reset_record_t          cool_reset_record_ref;
  cool_reset_record_t          cool_reset_record_smc;

  logic [31:0]                 isolate_req_reg_wr_data;
  logic [31:0]                 isolate_req_reg_wr_mask;
  logic                        isolate_req_reg_wr_en;
  logic [31:0]                 isolate_req_reg;

  logic [31:0]                 isolate_req_pinen_reg_wr_data;
  logic [31:0]                 isolate_req_pinen_reg_wr_mask;
  logic                        isolate_req_pinen_reg_wr_en;
  logic [31:0]                 isolate_req_pinen_reg;

  logic                        isolate_req_smc_reg_wr_en;
  logic                        isolate_req_smc_reg;

  logic [31:0]                 isolate_req_smcen_reg_wr_data;
  logic [31:0]                 isolate_req_smcen_reg_wr_mask;
  logic                        isolate_req_smcen_wr_en;
  logic [31:0]                 isolate_req_smcen_reg;

  logic [31:0]                 flr_set_cnt_wr_data;
  logic [31:0]                 flr_set_cnt_wr_mask;
  logic                        flr_set_cnt_wr_en;
  logic [31:0]                 flr_set_cnt;
  logic [31:0]                 flr_set_cnt_ref_clk;

  logic [31:0]                 flr_reset_set_cnt_wr_data;
  logic [31:0]                 flr_reset_set_cnt_wr_mask;
  logic                        flr_reset_set_cnt_wr_en;
  logic [31:0]                 flr_reset_set_cnt;
  logic [31:0]                 flr_reset_set_cnt_ref_clk;

  // FLR Logic Signals
  logic isolate_sequence_trigger_sync_ref_q, isolate_sequence_trigger_sync_ref_posedge;
  logic isolate_sequence_trigger_sync_smc_q, isolate_sequence_trigger_sync_smc_posedge;

  ////////////////////////
  // Register Interface //
  ////////////////////////

  always_comb begin
    hwif_in_o = '{default: '0};

    // ISOLATE_REQ_VIS
    hwif_in_o.ISOLATE_REQ_VIS.isolate_req_pin.next                   = isolate_req_pin_sync_smc;
    hwif_in_o.ISOLATE_REQ_VIS.cool_reset_cause.next                  = cool_reset_record_smc.cause;

    // ISOLATE_REQ_ACK_CAPTURE
    hwif_in_o.ISOLATE_REQ_ACK_CAPTURE.isolate_req_ack_capture.next   = cool_reset_record_smc.ack_capture;

    // ISOLATE_REQ_REG
    hwif_in_o.ISOLATE_REQ_REG.rd_ack                                  = hwif_out_i.ISOLATE_REQ_REG.req && !hwif_out_i.ISOLATE_REQ_REG.req_is_wr;
    hwif_in_o.ISOLATE_REQ_REG.rd_data                                 = isolate_req_reg;
    hwif_in_o.ISOLATE_REQ_REG.wr_ack                                  = isolate_req_reg_wr_en;

    // ISOLATE_REQ_PINEN_REG
    hwif_in_o.ISOLATE_REQ_PINEN_REG.rd_ack                            = hwif_out_i.ISOLATE_REQ_PINEN_REG.req && !hwif_out_i.ISOLATE_REQ_PINEN_REG.req_is_wr;
    hwif_in_o.ISOLATE_REQ_PINEN_REG.rd_data                           = isolate_req_pinen_reg;
    hwif_in_o.ISOLATE_REQ_PINEN_REG.wr_ack                            = isolate_req_pinen_reg_wr_en;

    // ISOLATE_REQ_SMC_REG
    hwif_in_o.ISOLATE_REQ_SMC_REG.rd_ack                              = hwif_out_i.ISOLATE_REQ_SMC_REG.req && !hwif_out_i.ISOLATE_REQ_SMC_REG.req_is_wr;
    hwif_in_o.ISOLATE_REQ_SMC_REG.rd_data                             = {31'b0, isolate_req_smc_reg};
    hwif_in_o.ISOLATE_REQ_SMC_REG.wr_ack                              = isolate_req_smc_reg_wr_en;

    // ISOLATE_REQ_SMCEN_REG
    hwif_in_o.ISOLATE_REQ_SMCEN_REG.rd_ack                            = hwif_out_i.ISOLATE_REQ_SMCEN_REG.req && !hwif_out_i.ISOLATE_REQ_SMCEN_REG.req_is_wr;
    hwif_in_o.ISOLATE_REQ_SMCEN_REG.rd_data                           = isolate_req_smcen_reg;
    hwif_in_o.ISOLATE_REQ_SMCEN_REG.wr_ack                            = isolate_req_smcen_wr_en;

    // ISOLATE_REQ_FLR_COUNTER_VALUE
    hwif_in_o.ISOLATE_REQ_FLR_COUNTER_VALUE.rd_ack                    = hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.req && !hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.req_is_wr;
    hwif_in_o.ISOLATE_REQ_FLR_COUNTER_VALUE.rd_data                   = flr_set_cnt;
    hwif_in_o.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_ack                    = flr_set_cnt_wr_en;

    // ISOLATE_REQ_FLR_RESET_COUNTER_VALUE
    hwif_in_o.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.rd_ack              = hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req && !hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req_is_wr;
    hwif_in_o.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.rd_data             = flr_reset_set_cnt;
    hwif_in_o.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_ack              = flr_reset_set_cnt_wr_en;
  end

  // ISOLATE_REQ_REG
  assign isolate_req_reg_wr_data                                           = hwif_out_i.ISOLATE_REQ_REG.wr_data;
  assign isolate_req_reg_wr_mask                                           = hwif_out_i.ISOLATE_REQ_REG.wr_biten;
  assign isolate_req_reg_wr_en                                             = hwif_out_i.ISOLATE_REQ_REG.req && hwif_out_i.ISOLATE_REQ_REG.req_is_wr;

  // ISOLATE_REQ_PINEN_REG
  assign isolate_req_pinen_reg_wr_data                                     = hwif_out_i.ISOLATE_REQ_PINEN_REG.wr_data;
  assign isolate_req_pinen_reg_wr_mask                                     = hwif_out_i.ISOLATE_REQ_PINEN_REG.wr_biten;
  assign isolate_req_pinen_reg_wr_en                                       = hwif_out_i.ISOLATE_REQ_PINEN_REG.req && hwif_out_i.ISOLATE_REQ_PINEN_REG.req_is_wr;

  // ISOLATE_REQ_SMC_REG
  assign isolate_req_smc_reg_wr_en                                         = hwif_out_i.ISOLATE_REQ_SMC_REG.req && hwif_out_i.ISOLATE_REQ_SMC_REG.req_is_wr;

  // ISOLATE_REQ_SMCEN_REG
  assign isolate_req_smcen_reg_wr_data                                     = hwif_out_i.ISOLATE_REQ_SMCEN_REG.wr_data;
  assign isolate_req_smcen_reg_wr_mask                                     = hwif_out_i.ISOLATE_REQ_SMCEN_REG.wr_biten;
  assign isolate_req_smcen_wr_en                                           = hwif_out_i.ISOLATE_REQ_SMCEN_REG.req && hwif_out_i.ISOLATE_REQ_SMCEN_REG.req_is_wr;

  // ISOLATE_REQ_FLR_COUNTER_VALUE
  assign flr_set_cnt_wr_data                                               = hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_data;
  assign flr_set_cnt_wr_mask                                               = hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_biten;
  assign flr_set_cnt_wr_en                                                 = hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.req && hwif_out_i.ISOLATE_REQ_FLR_COUNTER_VALUE.req_is_wr;

  // ISOLATE_REQ_FLR_RESET_COUNTER_VALUE
  assign flr_reset_set_cnt_wr_data                                         = hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_data;
  assign flr_reset_set_cnt_wr_mask                                         = hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_biten;
  assign flr_reset_set_cnt_wr_en                                           = hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req && hwif_out_i.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req_is_wr;

  ////////////////////////
  // Sync input signals //
  ////////////////////////

  prim_sync3 #(
    .WIDTH(1)
  ) u_isolate_req_pin_sync (
    .clk_i(clk_smc_i),
    .d_i  (isolate_req_pin_i),
    .q_o  (isolate_req_pin_sync_smc)
  );

  prim_sync3 #(
    .WIDTH(1)
  ) u_isolate_sequence_trigger_sync_smc (
    .clk_i(clk_smc_i),
    .d_i  (isolate_sequence_trigger_i),
    .q_o  (isolate_sequence_trigger_sync_smc)
  );

  prim_sync3 #(
    .WIDTH(1)
  ) u_isolate_sequence_trigger_sync_ref (
    .clk_i(clk_ref_i),
    .d_i  (isolate_sequence_trigger_i),
    .q_o  (isolate_sequence_trigger_sync_ref)
  );

  prim_sync3r #(
    .WIDTH(32)
  ) u_isolate_req_ack_sync_ref (
    .clk_i (clk_ref_i),
    .d_i   (isolate_req_ack_i),
    .rst_ni(rst_primary_ref_ni),
    .q_o   (isolate_req_ack_sync_ref)
  );

  prim_sync_data_autohs #(
    .WIDTH(32),
    .DEPTH(3)
  ) u_isolate_req_smcen_sync (
    .clk_src_i  (clk_smc_i),
    .rst_src_ni (rst_cold_smc_ni),
    .data_i     (isolate_req_smcen_reg),
    .clk_dst_i  (clk_ref_i),
    .rst_dst_ni (rst_cold_ref_ni),
    .data_o     (isolate_req_smcen_ref_clk)
  );

  prim_sync_data_autohs #(
    .WIDTH($bits(cool_reset_record_t)),
    .DEPTH(3)
  ) u_cool_reset_record_sync (
    .clk_src_i  (clk_ref_i),
    .rst_src_ni (rst_cold_ref_ni),
    .data_i     (cool_reset_record_ref),
    .clk_dst_i  (clk_smc_i),
    .rst_dst_ni (rst_cold_smc_ni),
    .data_o     (cool_reset_record_smc)
  );

  prim_sync_data_autohs #(
    .WIDTH(32),
    .DEPTH(3)
  ) u_flr_set_cnt_sync (
    .clk_src_i  (clk_smc_i),
    .rst_src_ni (rst_cold_smc_ni),
    .data_i     (flr_set_cnt),
    .clk_dst_i  (clk_ref_i),
    .rst_dst_ni (rst_cold_ref_ni),
    .data_o     (flr_set_cnt_ref_clk)
  );

  prim_sync_data_autohs #(
    .WIDTH(32),
    .DEPTH(3)
  ) u_flr_reset_set_cnt_sync (
    .clk_src_i  (clk_smc_i),
    .rst_src_ni (rst_cold_smc_ni),
    .data_i     (flr_reset_set_cnt),
    .clk_dst_i  (clk_ref_i),
    .rst_dst_ni (rst_cold_ref_ni),
    .data_o     (flr_reset_set_cnt_ref_clk)
  );

  ///////////////////////
  // Posedge Detection //
  ///////////////////////

  // Detect rising edge of isolate_sequence_trigger_sync_ref
  `OCAH_FF(isolate_sequence_trigger_sync_ref_q, isolate_sequence_trigger_sync_ref, 1'b0, clk_ref_i,
           rst_cold_ref_ni)

  assign isolate_sequence_trigger_sync_ref_posedge = isolate_sequence_trigger_sync_ref && !isolate_sequence_trigger_sync_ref_q;

  // Detect rising edge of isolate_sequence_trigger_sync_smc
  `OCAH_FF(isolate_sequence_trigger_sync_smc_q, isolate_sequence_trigger_sync_smc, 1'b0, clk_smc_i,
           rst_cold_smc_ni)

  assign isolate_sequence_trigger_sync_smc_posedge = isolate_sequence_trigger_sync_smc && !isolate_sequence_trigger_sync_smc_q;

  /////////////////////////////////
  // FLR Isolate request control //
  /////////////////////////////////

  // SMC implements isolate_req_reg[] for SMC SW to assert isolation request to subsystems like PCIe and/or ETH.
  `OCAH_FFL(
      isolate_req_reg,
      (isolate_req_reg & ~isolate_req_reg_wr_mask) | (isolate_req_reg_wr_data & isolate_req_reg_wr_mask),
      isolate_req_reg_wr_en, '0, clk_smc_i, rst_cold_smc_ni)

  // Section 4.9 - Implements isolate_req_pinen_reg[] to enable isolate_req_o[] to be impacted by isolate_req_pin.
  // Reset to 0 by PRESETn_extended when isolate_req_pin = 0; No reset when isolate_req_pin = 1.
  always_ff @(posedge clk_smc_i) begin
    if (~rst_cold_smc_ni && ~isolate_req_pin_sync_smc) begin
      isolate_req_pinen_reg <= '0;
    end else begin
      if (isolate_req_pinen_reg_wr_en) begin
        isolate_req_pinen_reg <= (isolate_req_pinen_reg & ~isolate_req_pinen_reg_wr_mask) | (isolate_req_pinen_reg_wr_data & isolate_req_pinen_reg_wr_mask);
      end
    end
  end

  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (~rst_cold_smc_ni) begin
      isolate_req_smc_reg <= 1'b0;
    end else begin
      if (isolate_sequence_trigger_sync_smc_posedge) begin
        isolate_req_smc_reg <= 1'b1;
      end else if (isolate_req_smc_reg_wr_en &&
                   hwif_out_i.ISOLATE_REQ_SMC_REG.wr_biten.isolate_req_smc_reg &&
                   hwif_out_i.ISOLATE_REQ_SMC_REG.wr_data.isolate_req_smc_reg) begin
        isolate_req_smc_reg <= 1'b0;  // De-assertion of isolate_req_smc_reg depends on SMC SW
      end
    end
  end

  // SMC implements isolate_req_reg[] for SMC SW to assert isolation request to subsystems like PCIe and/or ETH.
  `OCAH_FFL(
      isolate_req_smcen_reg,
      (isolate_req_smcen_reg & ~isolate_req_smcen_reg_wr_mask) | (isolate_req_smcen_reg_wr_data & isolate_req_smcen_reg_wr_mask),
      isolate_req_smcen_wr_en, '0, clk_smc_i, rst_cold_smc_ni)

  // Isolate request control logic (OR of SW request, pin request, and FLR request)
  always_comb begin
    for (int i = 0; i < 32; i++) begin
      isolate_req_o[i] = isolate_req_reg[i] | (isolate_req_pinen_reg[i] & isolate_req_pin_sync_smc) | (isolate_req_smcen_reg[i] & isolate_req_smc_reg);
    end
  end

  // Skip memory repair & MBIST during FLR if isolate request is asserted
  assign skip_mem_repair_o = isolate_req_pin_sync_smc | isolate_req_smc_reg;

  //////////////////
  // FLR Counters //
  //////////////////

  // Reset condition for flr counters to retain value depsite cool reset
  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (~rst_cold_smc_ni) begin
      flr_set_cnt       <= '0;
      flr_reset_set_cnt <= '0;
    end else begin
      if (flr_set_cnt_wr_en) begin
        flr_set_cnt <= (flr_set_cnt & ~flr_set_cnt_wr_mask) | (flr_set_cnt_wr_data & flr_set_cnt_wr_mask);
      end
      if (flr_reset_set_cnt_wr_en) begin
        flr_reset_set_cnt <= (flr_reset_set_cnt & ~flr_reset_set_cnt_wr_mask) | (flr_reset_set_cnt_wr_data & flr_reset_set_cnt_wr_mask);
      end
    end
  end

  logic flr_reset_n_n0_scan;

  typedef enum logic [1:0] {
    IDLE       = 2'b00,
    COUNT_DOWN = 2'b01,
    EQUAL_ZERO = 2'b10
  } flr_counter_state_e;

  flr_counter_state_e flr_counter_state, flr_counter_state_nxt;
  flr_counter_state_e flr_reset_counter_state, flr_reset_counter_state_nxt;

  logic [31:0] flr_count_value;
  logic [31:0] flr_reset_count_value;

  logic flr_commit, flr_reset_commit;
  logic flr_counter_expire_nxt;
  logic flr_reset_counter_expire_nxt;

  logic flr_set, flr_reset_set;

  logic isolate_req_acks_done;

  assign isolate_req_acks_done =
      (isolate_req_smcen_ref_clk != '0) &&
      ((isolate_req_ack_sync_ref & isolate_req_smcen_ref_clk) == isolate_req_smcen_ref_clk);

  // Counter for delaying rst_cool_n assertion
  prim_updown_counter #(
    .WIDTH(32),
    .RESET_VALUE(32'b0)
  ) u_flr_counter (
    .clk_i              (clk_ref_i),
    .rst_ni             (rst_cold_ref_ni),        // top level cold reset
    .clear_i            (1'b0),
    .set_i              (flr_set),
    .set_cnt_i          (flr_set_cnt_ref_clk),    // Set value for the counter (synchronized from SMCCLK).
    .incr_en_i          (1'b0),
    .decr_en_i          (1'b1),                   // Decrement always
    .step_i             (32'd1),                  // Increment/decrement by step when enabled - step by 1
    .commit_i           (flr_commit),
    .count_o            (flr_count_value),        // Current counter state
    .cnt_after_commit_o (),
    .err_o              ()
  );

  always_comb begin

    case (flr_counter_state)
      IDLE: begin

        // Do not start counting down if the reset assertion duration has not been set
        if (isolate_sequence_trigger_sync_ref_posedge && (flr_reset_set_cnt_ref_clk != '0)) begin

          // Check if counter value is set to 0 already, go to EQUAL_ZERO
          if (flr_set_cnt_ref_clk == '0) begin

            flr_set                   = 1'b0;
            flr_commit                = 1'b1;
            flr_counter_expire_nxt    = 1'b1;

            flr_counter_state_nxt     = EQUAL_ZERO;
          end else begin

            flr_set                   = 1'b1;
            flr_commit                = 1'b1;
            flr_counter_expire_nxt    = 1'b0;

            flr_counter_state_nxt     = COUNT_DOWN;
          end

        end else begin
          flr_set                   = 1'b0;
          flr_commit                = 1'b0;
          flr_counter_expire_nxt    = 1'b0;

          flr_counter_state_nxt     = IDLE;
        end
      end

      COUNT_DOWN: begin

        flr_set                   = 1'b0;
        flr_commit                = 1'b1;

        // Counter reached one -> zero on next cycle
        if ((flr_count_value == 32'd1) || isolate_req_acks_done) begin
          flr_counter_expire_nxt    = 1'b1;
          flr_counter_state_nxt     = EQUAL_ZERO;
        end else begin
          flr_counter_expire_nxt    = 1'b0;
          flr_counter_state_nxt     = COUNT_DOWN;
        end
      end

      EQUAL_ZERO: begin
        flr_set                   = 1'b0;
        flr_commit                = 1'b0;
        flr_counter_expire_nxt    = 1'b0;
        flr_counter_state_nxt     = IDLE;
      end

      default: begin
        flr_set                   = 1'b0;
        flr_commit                = 1'b0;
        flr_counter_expire_nxt    = 1'b0;
        flr_counter_state_nxt     = IDLE;
      end

    endcase
  end

  // Counter for holding rst_cool_n active
  prim_updown_counter #(
    .WIDTH      (32),
    .RESET_VALUE(32'b0)
  ) u_flr_reset_counter (
    .clk_i             (clk_ref_i),
    .rst_ni            (rst_cold_ref_ni),            // top level cold reset
    .clear_i           (1'b0),
    .set_i             (flr_reset_set),              // Starts counting down once flr_reset_n is asserted
    .set_cnt_i         (flr_reset_set_cnt_ref_clk),  // Set value for the counter (synchronized from SMCCLK).
    .incr_en_i         (1'b0),
    .decr_en_i         (1'b1),                       // Decrement always
    .step_i            (32'd1),                      // Increment/decrement by step when enabled - step by 1
    .commit_i          (flr_reset_commit),
    .count_o           (flr_reset_count_value),      // Current counter state
    .cnt_after_commit_o(),
    .err_o             ()
  );

  always_comb begin

    case (flr_reset_counter_state)
      IDLE: begin

        flr_reset_counter_expire_nxt = 1'b0;

        if (flr_counter_expire_nxt) begin
          flr_reset_set                    = 1'b1;
          flr_reset_commit                 = 1'b1;
          flr_reset_counter_state_nxt      = COUNT_DOWN;
        end else begin
          flr_reset_set                    = 1'b0;
          flr_reset_commit                 = 1'b0;
          flr_reset_counter_state_nxt      = IDLE;
        end
      end

      COUNT_DOWN: begin

        flr_reset_set    = 1'b0;
        flr_reset_commit = 1'b1;

        // Counter reached one -> zero on next cycle
        if (flr_reset_count_value <= 32'd1) begin
          flr_reset_counter_expire_nxt = 1'b1;
          flr_reset_counter_state_nxt  = EQUAL_ZERO;
        end else begin
          flr_reset_counter_expire_nxt = 1'b0;
          flr_reset_counter_state_nxt  = COUNT_DOWN;
        end
      end

      EQUAL_ZERO: begin
        flr_reset_set                    = 1'b0;
        flr_reset_commit                 = 1'b0;
        flr_reset_counter_expire_nxt     = 1'b0;
        flr_reset_counter_state_nxt      = IDLE;
      end

      default: begin
        flr_reset_set                    = 1'b0;
        flr_reset_commit                 = 1'b0;
        flr_reset_counter_expire_nxt     = 1'b0;
        flr_reset_counter_state_nxt      = IDLE;
      end

    endcase
  end

  always_ff @(posedge clk_ref_i or negedge rst_cold_ref_ni) begin
    if (~rst_cold_ref_ni) begin

      flr_counter_state       <= IDLE;
      flr_reset_counter_state <= IDLE;

      flr_reset_n_n0_scan     <= 1'b1;

    end else begin

      flr_counter_state       <= flr_counter_state_nxt;
      flr_reset_counter_state <= flr_reset_counter_state_nxt;

      if (flr_counter_expire_nxt) begin                 // Asserts flr_reset_n when flr_counter_expire_nxt is asserted.
        flr_reset_n_n0_scan <= 1'b0;
      end else if (flr_reset_counter_expire_nxt) begin  // Deassert flr_reset_n when flr_reset_counter_expire_nxt is asserted.
        flr_reset_n_n0_scan <= 1'b1;
      end

    end
  end

  assign rst_cool_no = flr_reset_n_n0_scan;

  ///////////////////////
  // Cool Reset Record //
  ///////////////////////

  logic rst_cool_pin_stable_q;
  logic rst_cool_pin_negedge;

  // Resetting to 0 keeps a pin still low at cold-reset release from reading as a fall.
  `OCAH_FF(rst_cool_pin_stable_q, rst_cool_pin_stable_ni, 1'b0, clk_ref_i, rst_cold_ref_ni)

  // A chiplet whose own cool reset reaches its pin sees the pin fall while rst_cool_no is low.
  assign rst_cool_pin_negedge = rst_cool_pin_stable_q && !rst_cool_pin_stable_ni && rst_cool_no;

  always_ff @(posedge clk_ref_i or negedge rst_cold_ref_ni) begin
    if (!rst_cold_ref_ni) begin
      cool_reset_record_ref <= '{cause: reset_unit_reg_pkg::reset_unit__cool_reset_cause_enum__none,
                                 ack_capture: '0};
    end else if (flr_counter_expire_nxt) begin
      cool_reset_record_ref.cause       <= isolate_req_acks_done ?
          reset_unit_reg_pkg::reset_unit__cool_reset_cause_enum__seq_ack :
          reset_unit_reg_pkg::reset_unit__cool_reset_cause_enum__seq_timeout;
      cool_reset_record_ref.ack_capture <= isolate_req_ack_sync_ref;
    end else if (rst_cool_pin_negedge) begin
      cool_reset_record_ref.cause       <= reset_unit_reg_pkg::reset_unit__cool_reset_cause_enum__pin;
    end
  end

endmodule
