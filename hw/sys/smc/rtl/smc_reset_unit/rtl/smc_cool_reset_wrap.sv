// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-------------------------------------------------
// SMC Cool Reset Wrap (FLR)
//
//-------------------------------------------------

module smc_cool_reset_wrap (
  input  logic                                   clk_ref_i,
  input  logic                                   rst_cold_ref_ni,             // cold reset, reference clock domain

  input  logic                                   clk_smc_i,
  input  logic                                   rst_cold_smc_ni,             // cold reset, SMC clock domain

  // Register Interface
  input  reset_unit_reg_pkg::reset_unit__out_t   hwif_out,
  output reset_unit_reg_pkg::reset_unit__in_t    hwif_in,

  // FLR Resets
  input  logic                                   isolate_req_pin_i,           // Set which subsystems are isolated from cool reset from external pin
  input  logic                                   cfg_flr_pf_active_i,         // Indicates that FLR is requested from PCIe
  input  logic                                   rst_cool_ni,                 // Incoming cool reset request from primary chiplet to place in internal register for visibility
  output logic [31:0]                            isolate_req_o,               // Controls isolation of subsystems like PCIe and/or ETH during FLR
  output logic                                   skip_mem_repair_o,           // Signal to skip memory repair & MBIST during FLR
  output logic                                   rst_cool_no                  // Cool reset from primary chiplet to other chiplets
);

  /////////////////////////
  // Signal Declarations //
  /////////////////////////

  // Register Interface Signals
  logic                        isolate_req_pin_sync_smc;
  logic                        cfg_flr_pf_active_sync_smc;
  logic                        cfg_flr_pf_active_sync_ref;

  logic                        rst_cool_ni_sync_smc;
  logic                        rst_cool_no_sync_smc;

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
  logic cfg_flr_pf_active_sync_ref_q, cfg_flr_pf_active_sync_ref_posedge;
  logic cfg_flr_pf_active_sync_smc_q, cfg_flr_pf_active_sync_smc_posedge;

  ////////////////////////
  // Register Interface //
  ////////////////////////

  always_comb begin
    hwif_in = '{default: '0};

    // ISOLATE_REQ_VIS
    hwif_in.ISOLATE_REQ_VIS.isolate_req_pin.next                     = isolate_req_pin_sync_smc;
    hwif_in.ISOLATE_REQ_VIS.cool_reset_n_i.next                      = rst_cool_ni_sync_smc;
    hwif_in.ISOLATE_REQ_VIS.cool_reset_n_o.next                      = rst_cool_no_sync_smc;

    // ISOLATE_REQ_REG
    hwif_in.ISOLATE_REQ_REG.rd_ack                                    = hwif_out.ISOLATE_REQ_REG.req && !hwif_out.ISOLATE_REQ_REG.req_is_wr;
    hwif_in.ISOLATE_REQ_REG.rd_data                                   = isolate_req_reg;
    hwif_in.ISOLATE_REQ_REG.wr_ack                                    = isolate_req_reg_wr_en;

    // ISOLATE_REQ_PINEN_REG
    hwif_in.ISOLATE_REQ_PINEN_REG.rd_ack                              = hwif_out.ISOLATE_REQ_PINEN_REG.req && !hwif_out.ISOLATE_REQ_PINEN_REG.req_is_wr;
    hwif_in.ISOLATE_REQ_PINEN_REG.rd_data                             = isolate_req_pinen_reg;
    hwif_in.ISOLATE_REQ_PINEN_REG.wr_ack                              = isolate_req_pinen_reg_wr_en;

    // ISOLATE_REQ_SMC_REG
    hwif_in.ISOLATE_REQ_SMC_REG.rd_ack                                = hwif_out.ISOLATE_REQ_SMC_REG.req && !hwif_out.ISOLATE_REQ_SMC_REG.req_is_wr;
    hwif_in.ISOLATE_REQ_SMC_REG.rd_data                               = {31'b0, isolate_req_smc_reg};
    hwif_in.ISOLATE_REQ_SMC_REG.wr_ack                                = isolate_req_smc_reg_wr_en;

    // ISOLATE_REQ_SMCEN_REG
    hwif_in.ISOLATE_REQ_SMCEN_REG.rd_ack                              = hwif_out.ISOLATE_REQ_SMCEN_REG.req && !hwif_out.ISOLATE_REQ_SMCEN_REG.req_is_wr;
    hwif_in.ISOLATE_REQ_SMCEN_REG.rd_data                             = isolate_req_smcen_reg;
    hwif_in.ISOLATE_REQ_SMCEN_REG.wr_ack                              = isolate_req_smcen_wr_en;

    // ISOLATE_REQ_FLR_COUNTER_VALUE
    hwif_in.ISOLATE_REQ_FLR_COUNTER_VALUE.rd_ack                      = hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.req && !hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.req_is_wr;
    hwif_in.ISOLATE_REQ_FLR_COUNTER_VALUE.rd_data                     = flr_set_cnt;
    hwif_in.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_ack                      = flr_set_cnt_wr_en;

    // ISOLATE_REQ_FLR_RESET_COUNTER_VALUE
    hwif_in.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.rd_ack                = hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req && !hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req_is_wr;
    hwif_in.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.rd_data               = flr_reset_set_cnt;
    hwif_in.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_ack                = flr_reset_set_cnt_wr_en;
  end

  // ISOLATE_REQ_REG
  assign isolate_req_reg_wr_data                                           = hwif_out.ISOLATE_REQ_REG.wr_data;
  assign isolate_req_reg_wr_mask                                           = hwif_out.ISOLATE_REQ_REG.wr_biten;
  assign isolate_req_reg_wr_en                                             = hwif_out.ISOLATE_REQ_REG.req && hwif_out.ISOLATE_REQ_REG.req_is_wr;

  // ISOLATE_REQ_PINEN_REG
  assign isolate_req_pinen_reg_wr_data                                     = hwif_out.ISOLATE_REQ_PINEN_REG.wr_data;
  assign isolate_req_pinen_reg_wr_mask                                     = hwif_out.ISOLATE_REQ_PINEN_REG.wr_biten;
  assign isolate_req_pinen_reg_wr_en                                       = hwif_out.ISOLATE_REQ_PINEN_REG.req && hwif_out.ISOLATE_REQ_PINEN_REG.req_is_wr;

  // ISOLATE_REQ_SMC_REG
  assign isolate_req_smc_reg_wr_en                                         = hwif_out.ISOLATE_REQ_SMC_REG.req && hwif_out.ISOLATE_REQ_SMC_REG.req_is_wr;

  // ISOLATE_REQ_SMCEN_REG
  assign isolate_req_smcen_reg_wr_data                                     = hwif_out.ISOLATE_REQ_SMCEN_REG.wr_data;
  assign isolate_req_smcen_reg_wr_mask                                     = hwif_out.ISOLATE_REQ_SMCEN_REG.wr_biten;
  assign isolate_req_smcen_wr_en                                           = hwif_out.ISOLATE_REQ_SMCEN_REG.req && hwif_out.ISOLATE_REQ_SMCEN_REG.req_is_wr;

  // ISOLATE_REQ_FLR_COUNTER_VALUE
  assign flr_set_cnt_wr_data                                               = hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_data;
  assign flr_set_cnt_wr_mask                                               = hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.wr_biten;
  assign flr_set_cnt_wr_en                                                 = hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.req && hwif_out.ISOLATE_REQ_FLR_COUNTER_VALUE.req_is_wr;

  // ISOLATE_REQ_FLR_RESET_COUNTER_VALUE
  assign flr_reset_set_cnt_wr_data                                         = hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_data;
  assign flr_reset_set_cnt_wr_mask                                         = hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.wr_biten;
  assign flr_reset_set_cnt_wr_en                                           = hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req && hwif_out.ISOLATE_REQ_FLR_RESET_COUNTER_VALUE.req_is_wr;

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
  ) u_cfg_flr_pf_active_sync_smc (
    .clk_i(clk_smc_i),
    .d_i  (cfg_flr_pf_active_i),
    .q_o  (cfg_flr_pf_active_sync_smc)
  );

  prim_sync3 #(
    .WIDTH(1)
  ) u_cfg_flr_pf_active_sync_ref (
    .clk_i(clk_ref_i),
    .d_i  (cfg_flr_pf_active_i),
    .q_o  (cfg_flr_pf_active_sync_ref)
  );

  prim_sync3 #(
    .WIDTH(1)
  ) u_rst_cool_ni_sync_smc (
    .clk_i(clk_smc_i),
    .d_i  (rst_cool_ni),
    .q_o  (rst_cool_ni_sync_smc)
  );

  prim_sync3 #(
    .WIDTH(1)
  ) u_rst_cool_no_sync_smc (
    .clk_i(clk_smc_i),
    .d_i  (rst_cool_no),
    .q_o  (rst_cool_no_sync_smc)
  );

  prim_sync_data_autohs #(
    .WIDTH(32),
    .DEPTH(3)
  ) u_flr_set_cnt_sync (
    .clk_src_i    (clk_smc_i),
    .reset_src_ni (rst_cold_smc_ni),
    .data_i       (flr_set_cnt),
    .clk_dst_i    (clk_ref_i),
    .reset_dst_ni (rst_cold_ref_ni),
    .data_o       (flr_set_cnt_ref_clk)
  );

  prim_sync_data_autohs #(
    .WIDTH(32),
    .DEPTH(3)
  ) u_flr_reset_set_cnt_sync (
    .clk_src_i    (clk_smc_i),
    .reset_src_ni (rst_cold_smc_ni),
    .data_i       (flr_reset_set_cnt),
    .clk_dst_i    (clk_ref_i),
    .reset_dst_ni (rst_cold_ref_ni),
    .data_o       (flr_reset_set_cnt_ref_clk)
  );

  ///////////////////////
  // Posedge Detection //
  ///////////////////////

  // Detect rising edge of cfg_flr_pf_active_sync_ref
  always_ff @(posedge clk_ref_i or negedge rst_cold_ref_ni) begin
    if (!rst_cold_ref_ni) begin
      cfg_flr_pf_active_sync_ref_q <= 1'b0;
    end else begin
      cfg_flr_pf_active_sync_ref_q <= cfg_flr_pf_active_sync_ref;
    end
  end

  assign cfg_flr_pf_active_sync_ref_posedge = cfg_flr_pf_active_sync_ref && !cfg_flr_pf_active_sync_ref_q;

  // Detect rising edge of cfg_flr_pf_active_sync_smc
  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (!rst_cold_smc_ni) begin
      cfg_flr_pf_active_sync_smc_q <= 1'b0;
    end else begin
      cfg_flr_pf_active_sync_smc_q <= cfg_flr_pf_active_sync_smc;
    end
  end

  assign cfg_flr_pf_active_sync_smc_posedge = cfg_flr_pf_active_sync_smc && !cfg_flr_pf_active_sync_smc_q;

  /////////////////////////////////
  // FLR Isolate request control //
  /////////////////////////////////

  // SMC implements isolate_req_reg[] for SMC SW to assert isolation request to subsystems like PCIe and/or ETH.
  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (~rst_cold_smc_ni) begin
      isolate_req_reg <= '0;
    end else begin
      if (isolate_req_reg_wr_en) begin
        isolate_req_reg <= (isolate_req_reg & ~isolate_req_reg_wr_mask) | (isolate_req_reg_wr_data & isolate_req_reg_wr_mask);
      end
    end
  end

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

  // SMC implements isolate_req_smc_reg to assert isolate_req_o[] once cfg_flr_pf_active is asserted
  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (~rst_cold_smc_ni) begin
      isolate_req_smc_reg <= 1'b0;
    end else begin
      if (cfg_flr_pf_active_sync_smc_posedge) begin
        isolate_req_smc_reg <= 1'b1; // Asserts isolate_req_smc_reg once cfg_flr_pf_active is asserted
      end else if (isolate_req_smc_reg_wr_en && (|hwif_out.ISOLATE_REQ_SMC_REG.wr_biten)) begin
        isolate_req_smc_reg <= 1'b0;  // De-assertion of isolate_req_smc_reg depends on SMC SW
      end
    end
  end

  // SMC implements isolate_req_reg[] for SMC SW to assert isolation request to subsystems like PCIe and/or ETH.
  always_ff @(posedge clk_smc_i or negedge rst_cold_smc_ni) begin
    if (~rst_cold_smc_ni) begin
      isolate_req_smcen_reg <= '0;
    end else begin
      if (isolate_req_smcen_wr_en) begin
        isolate_req_smcen_reg <= (isolate_req_smcen_reg & ~isolate_req_smcen_reg_wr_mask) | (isolate_req_smcen_reg_wr_data & isolate_req_smcen_reg_wr_mask);
      end
    end
  end

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

  // Counter for delaying rst_cool_n assertion
  prim_updown_counter #(
    .Width(32),
    .ResetValue(32'b0)
  ) u_flr_counter (
    .clk_i              (clk_ref_i),
    .rst_ni             (rst_cold_ref_ni),        // top level cold reset
    .clear_i            (1'b0),
    .set_i              (flr_set),                // Starts counting down once cfg_flr_pf_active is asserted
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
        if (cfg_flr_pf_active_sync_ref_posedge && (flr_reset_set_cnt_ref_clk != '0)) begin

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
        if (flr_count_value == 32'd1) begin
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
    .Width     (32),
    .ResetValue(32'b0)
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

endmodule
