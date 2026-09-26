// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Insert a simulation-only random delay ahead of a CDC synchronizer.
//
// Tie d_del_o to d_i in synthesis, or when random-delay modeling is disabled.
//
// RANDOM_DELAY_TYPE selects the delay set:
//
// - 0: none.
// - 1 (default): zero or up to one clk_i cycle.
// - 2: zero, 0.5, 1, or 1.5.
// - 3: zero through three.
// - 4: zero or up to 0.5.
// - Any other value: none.
//
// The remaining parameters control the delay flops:
//
// - RANDOM_DELAY_RESET clears the delay flops on rst_ni when set.
// - RANDOM_DELAY_GRAY_CODE shares one mux select across WIDTH bits.
// - RANDOM_DELAY_MUX_OVR forces a fixed select.
// - RESET_POLARITY chooses clear versus set when rst_ni asserts.

module prim_sync_randomized_delay #(
  parameter int unsigned WIDTH = 1,  // Datapath width.

`ifdef RANDOM_DELAY_TYP_OVR
  parameter int unsigned RANDOM_DELAY_TYPE = `RANDOM_DELAY_TYP_OVR,  // Delay set: 0 none; 1 zero or up to 1 clk_i cycle (default);
                                                                     // 2 zero/0.5/1/1.5; 3 zero..3; 4 zero or
                                                                     // up to 0.5; else none.
`else
  parameter int unsigned RANDOM_DELAY_TYPE = 1,  // Delay set: 0 none; 1 zero or up to 1 clk_i cycle (default);
                                                 // 2 zero/0.5/1/1.5; 3 zero..3; 4 zero or
                                                 // up to 0.5; else none.
`endif

  parameter bit RANDOM_DELAY_RESET = 1'b1,  // 1 clears delay flops on rst_ni; 0 leaves them alone.

  parameter bit RANDOM_DELAY_GRAY_CODE = 1'b0,  // 1 shares one mux select across bits; 0 gives each bit its own.

  parameter bit RANDOM_DELAY_MUX_OVR = 1'b0,  // 0 uses the internal random mux select; nonzero forces a fixed select.
  parameter bit RESET_POLARITY = 1'b0  // 0 clears flops when rst_ni is low; 1 sets them to one.
) (
  input logic clk_i,  // Delay clock.
  input logic [WIDTH-1:0] d_i,  // Data into the delay.
  input logic rst_ni,  // Active-low reset; tie high if the synchronizer is not resettable.
  input logic [WIDTH*2-1:0] mux_sel_ovr_i,  // Mux-select override vector; unused.

  output logic [WIDTH*2-1:0] mux_sel_o,  // Observed mux-select vector; unused.
  output logic [WIDTH-1:0]   d_del_o  // Delayed data toward the synchronizer.
);

`ifdef SYNTHESIS  // if we are synthesizing ignore random delay logic
  assign d_del_o   = d_i;
  assign mux_sel_o = {WIDTH{2'd0}};
`else
`ifndef RANDOM_DELAY_ENABLE  // if modeling random delay is not enabled ignore random delay logic
  assign d_del_o   = d_i;
  assign mux_sel_o = {WIDTH{2'd0}};
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

  assign d_del_o   = d_mux;
  assign mux_sel_o = mux_sel;

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
    always @(clk_i) begin
      mux_sel_gray <= mux_sel_gray_init + ($urandom % 2);
      for (integer j = 0; j < WIDTH; j = j + 1) begin
        mux_sel[2*j+:2] <= mux_sel_gray;
      end
    end
  end else begin : gen_random_mux_sel
    for (i = 0; i < WIDTH; i = i + 1) begin : gen_mux_sel_random
      always @(d_i[i]) begin
        mux_sel[2*i+:2] = $urandom;
      end
    end
  end

  // Generate Delay Flops
  generate

    if (RANDOM_DELAY_TYPE == 0) begin : gen_no_delay
      assign d_mux = d_i;
    end else if (RANDOM_DELAY_TYPE == 1) begin : gen_type_1_delay
      // First flop at posedge, 1 cycle delay
      always @(posedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= d_i;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        assign d_mux[i] = mux_sel[2*i] ? d_q1[i] : d_i[i];
      end
    end else if (RANDOM_DELAY_TYPE == 2) begin : gen_type_2_delay
      // First flop at negedge, 0.5 cycle delay
      always @(negedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= d_i;
      end
      // Second flop at posedge, 1 cycle delay
      always @(posedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q2 <= {WIDTH{RESET_POLARITY}};
        else d_q2 <= d_q1;
      end
      // Third flop at negedge, 1.5 cycle delay
      always @(negedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q3 <= {WIDTH{RESET_POLARITY}};
        else d_q3 <= d_q2;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          unique case (mux_sel[2*i+:2])
            2'b00: d_mux[i] = d_i[i];
            2'b01: d_mux[i] = d_q1[i];
            2'b10: d_mux[i] = d_q2[i];
            2'b11: d_mux[i] = d_q3[i];
          endcase
        end
      end
    end else if (RANDOM_DELAY_TYPE == 3) begin : gen_type_3_delay
      // First flop at posedge, 1 cycle delay
      always @(posedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= d_i;
      end
      // Second flop at posedge, 2 cycle delay
      always @(posedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q2 <= {WIDTH{RESET_POLARITY}};
        else d_q2 <= d_q1;
      end
      // Third flop at posedge, 3 cycle delay
      always @(posedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q3 <= {WIDTH{RESET_POLARITY}};
        else d_q3 <= d_q2;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          unique case (mux_sel[2*i+:2])
            2'b00: d_mux[i] = d_i[i];
            2'b01: d_mux[i] = d_q1[i];
            2'b10: d_mux[i] = d_q2[i];
            2'b11: d_mux[i] = d_q3[i];
          endcase
        end
      end
    end else if (RANDOM_DELAY_TYPE == 4) begin : gen_type_4_delay
      // First flop at negedge, 0.5 cycle delay
      always @(negedge clk_i or negedge rst_ni) begin
        if ((!rst_ni) && (RANDOM_DELAY_RESET > 0)) d_q1 <= {WIDTH{RESET_POLARITY}};
        else d_q1 <= d_i;
      end
      // Data Mux
      for (i = 0; i < WIDTH; i = i + 1) begin : gen_data_mux
        always_comb begin
          d_mux[i] = mux_sel[2*i] ? d_q1[i] : d_i[i];
        end
      end
    end else begin : gen_unknown_delay
      always_comb begin
        d_mux = d_i;
      end
    end
  endgenerate

`endif  // `ifndef MODEL_MISSAMPLES
`endif  // `ifdef SYNTHESIS

endmodule
