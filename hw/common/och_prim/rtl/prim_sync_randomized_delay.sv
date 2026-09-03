// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Randomized Delay Synchronizer
//
//--------------------------------------------------
module prim_sync_randomized_delay #(
  parameter int unsigned WIDTH = 1,

`ifdef RANDOM_DELAY_TYP_OVR
  parameter int unsigned RANDOM_DELAY_TYPE = `RANDOM_DELAY_TYP_OVR,
`else
  parameter int unsigned RANDOM_DELAY_TYPE = 1,
`endif
  // RANDOM_DELAY_TYPE =
  // 0 => no delay
  // 1 => 0 or up to 1 i_clk cycles of delay (DEFAULT)
  // 2 => 0, 0.5, 1, 1.5 i_clk cycles of delay
  // 3 => 0, 1, 2, 3 i_clk cycles of delay
  // 4 => 0 or up to 0.5 i_clk cycles of delay
  // otherwise => no delay

  parameter bit RANDOM_DELAY_RESET = 1'b1,  // 0 ~ 1
  // RANDOM_DELAY_RESET =
  // 0 => dont reset the delay flops
  // otherwise => reset the delay flops

  parameter bit RANDOM_DELAY_GRAY_CODE = 1'b0,  // 0 ~ 1
  // RANDOM_DELAY_GRAY_CODE =
  // 0 => each bit has its own random mux sel
  // otherwise => all bits have the same random mux sel

  parameter bit RANDOM_DELAY_MUX_OVR = 1'b0,  // 0 ~ 3
  // RANDOM_DELAY_MUX_OVR =
  // 0 => Use internal random mux_sel
  // otherwise => Use RANDOM_DELAY_MUX_OVR value for all muxs
  //
  parameter bit RESET_POLARITY = 1'b0  // 0 ~ 1
  // RESET_POLARITY =
  // 0 => 'reset' to zero when i_reset_n is low
  // 1 => 'set'   to one  when i_reset_n is low
) (
  input logic i_clk,
  input logic [WIDTH-1:0] i_d,
  input logic i_reset_n,  // Active Low Reset, if synchronizer is not resettable tie to 1
  input logic [WIDTH*2-1:0] i_mux_sel_ovr,  // Mux Select Override Value, NOT USED FOR NOW

  output logic [WIDTH*2-1:0] o_mux_sel,  // Output Mux Select, NOT USED FOR NOW
  output logic [WIDTH-1:0]   o_d_del     // Delayed Data
);

`ifdef SYNTHESIS  // if we are synthesizing ignore random delay logic
  assign o_d_del   = i_d;
  assign o_mux_sel = {WIDTH{2'd0}};
`else
`ifndef RANDOM_DELAY_ENABLE  // if modeling random delay is not enabled ignore random delay logic
  assign o_d_del   = i_d;
  assign o_mux_sel = {WIDTH{2'd0}};
`else  // Otherrwise use random delay logic
  reg [WIDTH-1:0] d_q1, d_q2, d_q3;
  reg     [WIDTH-1:0]   d_mux;
  logic   [WIDTH*2-1:0] mux_sel;
  reg     [1:0]         mux_sel_gray;
  reg     [1:0]         mux_sel_gray_init;

  integer               myseed;
  integer               myseed2;
  integer               myrand;
  genvar i;

  assign o_d_del   = d_mux;
  assign o_mux_sel = mux_sel;

  // initialize randomizer
  initial begin
    myseed = $get_initial_random_seed();
    if (myseed == 0) myseed = 32'hdeadbeef;
    myseed2 = myseed;
    myrand = $urandom(myseed);

    // Gray mode: choose a starting point at time zero, and then vary *by
    // a maximum of one* from that starting point each cycle.
    mux_sel_gray_init = $urandom % 2;

  end

  // Randomly choose a mux_sel value every time input transitions
  initial begin
    mux_sel = {WIDTH{2'd0}};
  end

  if (RANDOM_DELAY_MUX_OVR != 0) begin : gen_random_mux_sel_ovr
    for (i = 0; i < WIDTH; i = i + 1) begin : gen_mux_sel_ovr
      assign mux_sel[2*i+:2] = RANDOM_DELAY_MUX_OVR;
    end
  end else if (RANDOM_DELAY_GRAY_CODE == 1) begin : gen_random_mux_sel_gray
    always @(i_clk) begin
      mux_sel_gray <= mux_sel_gray_init + ($urandom % 2);
      for (integer j = 0; j < WIDTH; j = j + 1) begin
        mux_sel[2*j+:2] <= mux_sel_gray;
      end
    end
  end else begin : gen_random_mux_sel
    for (i = 0; i < WIDTH; i = i + 1) begin : gen_mux_sel_random
      always @(i_d[i]) begin
        mux_sel[2*i+:2] = $urandom;
      end
    end
  end

  // Generate Delay Flops
  generate

    if (RANDOM_DELAY_TYPE == 0) begin : gen_no_delay
      assign d_mux = i_d;
    end else if (RANDOM_DELAY_TYPE == 1) begin : gen_type_1_delay
      // First flop at posedge, 1 cycle delay
      always @(posedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= i_d;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        assign d_mux[i] = mux_sel[2*i] ? d_q1[i] : i_d[i];
      end
    end else if (RANDOM_DELAY_TYPE == 2) begin : gen_type_2_delay
      // First flop at negedge, 0.5 cycle delay
      always @(negedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= i_d;
      end
      // Second flop at posedge, 1 cycle delay
      always @(posedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q2 <= {WIDTH{RESET_POLARITY}};
        else d_q2 <= d_q1;
      end
      // Third flop at negedge, 1.5 cycle delay
      always @(negedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q3 <= {WIDTH{RESET_POLARITY}};
        else d_q3 <= d_q2;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          unique case (mux_sel[2*i+:2])
            2'b00: d_mux[i] = i_d[i];
            2'b01: d_mux[i] = d_q1[i];
            2'b10: d_mux[i] = d_q2[i];
            2'b11: d_mux[i] = d_q3[i];
          endcase
        end
      end
    end else if (RANDOM_DELAY_TYPE == 3) begin : gen_type_3_delay
      // First flop at posedge, 1 cycle delay
      always @(posedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= i_d;
      end
      // Second flop at posedge, 2 cycle delay
      always @(posedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q2 <= {WIDTH{RESET_POLARITY}};
        else d_q2 <= d_q1;
      end
      // Third flop at posedge, 3 cycle delay
      always @(posedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q3 <= {WIDTH{RESET_POLARITY}};
        else d_q3 <= d_q2;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          unique case (mux_sel[2*i+:2])
            2'b00: d_mux[i] = i_d[i];
            2'b01: d_mux[i] = d_q1[i];
            2'b10: d_mux[i] = d_q2[i];
            2'b11: d_mux[i] = d_q3[i];
          endcase
        end
      end
    end else if (RANDOM_DELAY_TYPE == 4) begin : gen_type_4_delay
      // First flop at negedge, 0.5 cycle delay
      always @(negedge i_clk or negedge i_reset_n) begin
        if ((!i_reset_n) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= i_d;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          d_mux[i] = mux_sel[2*i] ? d_q1[i] : i_d[i];
        end
      end
    end else begin : gen_unknown_delay
      always_comb begin
        d_mux = i_d;
      end
    end
  endgenerate

`endif  // `ifndef MODEL_MISSAMPLES
`endif  // `ifdef SYNTHESIS

endmodule
