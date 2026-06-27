// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

// Trace Hop - Block that connects the TNIF to the Trace funnel

module dfd_trace_hop
  import dfd_tn_pkg::*;
#(
  parameter IS_REPEATER = 1'b0,
  parameter NUM_CORES_IN_PATH = 4,
  parameter RELATIVE_CORE_IDX = 0,
  parameter NUM_REPEATER_STAGES = 1,
  parameter NUM_UPSTREAM_REPEATERS = 0,
  parameter NUM_HOPS_TO_TAIL = 0,
  
  parameter DATA_WIDTH_IN_BYTES = 16,
  parameter DATA_WIDTH = DATA_WIDTH_IN_BYTES*8
) (
  input  logic                                            clk,
  input  logic                                            reset_n,

  // Functional Block Interface
  input  logic                                            fblk_tr_vld,
  input  logic                                            fblk_tr_src, 
  input  logic [DATA_WIDTH-1:0]                           fblk_tr_data,
  output logic                                            fblk_tr_gnt,
  output logic                                            fblk_tr_ntrace_bp,
  output logic                                            fblk_tr_dst_bp,
  output logic                                            fblk_tr_ntrace_flush,
  output logic                                            fblk_tr_dst_flush,  

  // Upstream network interface
  input  logic [NUM_CORES_IN_PATH-1:0]                    upstrm_tr_vld,
  input  logic                                            upstrm_tr_src, 
  input  logic [DATA_WIDTH-1:0]                           upstrm_tr_data,
  output logic                                            upstrm_tr_ntrace_bp,
  output logic                                            upstrm_tr_dst_bp,
  output logic                                            upstrm_tr_ntrace_flush,
  output logic                                            upstrm_tr_dst_flush,
  output logic [NUM_CORES_IN_PATH-1:0]                    upstrm_tr_enabled_srcs,

  // Downstream network interface
  output logic [NUM_CORES_IN_PATH-1:0]                    dnstrm_tr_vld,
  output logic                                            dnstrm_tr_src, 
  output logic [DATA_WIDTH-1:0]                           dnstrm_tr_data,
  input  logic                                            dnstrm_tr_ntrace_bp,
  input  logic                                            dnstrm_tr_dst_bp,
  input  logic                                            dnstrm_tr_ntrace_flush,
  input  logic                                            dnstrm_tr_dst_flush,
  input  logic [NUM_CORES_IN_PATH-1:0]                    dnstrm_tr_enabled_srcs
);
  
  // --------------------------------------------------------------------------
  // Internal Signals
  // --------------------------------------------------------------------------
  logic [11:0] tr_gnt_to_fblk, next_tr_gnt_to_fblk, tr_gnt_reset;
  logic [5:0] tr_init_setup_cnt;
  logic tr_init_setup_done, tr_init_setup_done_d1, tr_init_setup_done_posedge;
  logic [1:0] num_disabled_cores_as_repeaters;
  logic [2:0] num_cores_enabled;
  logic fblk_tr_gnt_d1, fblk_tr_gnt_d2;

  // --------------------------------------------------------------------------
  // Initial setup delay counter to enable the grant shift register
  // --------------------------------------------------------------------------
  dfd_rv_dff_clr #(.WIDTH(6)) tr_init_setup_cnt_ff (.o_q(tr_init_setup_cnt), .i_d($bits(tr_init_setup_cnt)'(tr_init_setup_cnt+1'b1)), .i_clr(~|upstrm_tr_enabled_srcs), .i_en(|upstrm_tr_enabled_srcs & ~tr_init_setup_done), .i_clk(clk), .i_reset_n(reset_n));
  assign tr_init_setup_done = (tr_init_setup_cnt == ($bits(tr_init_setup_cnt)'(NUM_UPSTREAM_REPEATERS + NUM_HOPS_TO_TAIL) + $bits(tr_init_setup_cnt)'(num_disabled_cores_as_repeaters))) & |upstrm_tr_enabled_srcs;

  always_comb begin
    num_disabled_cores_as_repeaters = '0;
    for (int i=(RELATIVE_CORE_IDX+1); i<NUM_CORES_IN_PATH; i++) begin
      if (~upstrm_tr_enabled_srcs[i])
        num_disabled_cores_as_repeaters = num_disabled_cores_as_repeaters + 1'b1;
      else 
        num_disabled_cores_as_repeaters = num_disabled_cores_as_repeaters; 
    end
  end

  always_comb begin
    num_cores_enabled = '0;
    for (int i=0; i<NUM_CORES_IN_PATH; i++) begin
      num_cores_enabled = $bits(num_cores_enabled)'(num_cores_enabled + $bits(num_cores_enabled)'(upstrm_tr_enabled_srcs[i]));
    end
  end

  dfd_rv_dff #(.WIDTH(1)) tr_init_setup_done_d1_ff (.o_q(tr_init_setup_done_d1), .i_d(tr_init_setup_done), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  assign tr_init_setup_done_posedge = tr_init_setup_done & ~tr_init_setup_done_d1;
  
  // --------------------------------------------------------------------------
  // Shift Register to provide grant to TNIF
  // --------------------------------------------------------------------------
  assign next_tr_gnt_to_fblk = {tr_gnt_to_fblk[10:0],tr_gnt_to_fblk[11]};
  assign tr_gnt_reset = (num_cores_enabled == 3'h4)?12'b000100010001:((num_cores_enabled == 3'h3)?12'b001001001001:((num_cores_enabled == 3'h2)?12'b010101010101:12'b111111111111));
  dfd_rv_dff #(.WIDTH(12)) tr_gnt_to_fblk_ff (.o_q(tr_gnt_to_fblk), .i_d(tr_init_setup_done_posedge?tr_gnt_reset:next_tr_gnt_to_fblk), .i_en(tr_init_setup_done), .i_clk(clk), .i_reset_n(reset_n));  
  
  // --------------------------------------------------------------------------
  // Flops with Mux-ed inputs combining the upstream and the functional-block
  // --------------------------------------------------------------------------
  dfd_rv_dff_staging #(.WIDTH(NUM_CORES_IN_PATH), .DEPTH(NUM_REPEATER_STAGES)) tr_vld_stg_ff (.o_q(dnstrm_tr_vld), .i_d((~IS_REPEATER & fblk_tr_gnt_d2) ? {{(NUM_CORES_IN_PATH-RELATIVE_CORE_IDX-1){1'b0}}, fblk_tr_vld, {RELATIVE_CORE_IDX{1'b0}}} : upstrm_tr_vld), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(1), .DEPTH(NUM_REPEATER_STAGES)) tr_src_stg_ff (.o_q(dnstrm_tr_src), .i_d((~IS_REPEATER & fblk_tr_gnt_d2) ? fblk_tr_src : upstrm_tr_src), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(DATA_WIDTH), .DEPTH(NUM_REPEATER_STAGES)) tr_data_stg_ff (.o_q(dnstrm_tr_data), .i_d((~IS_REPEATER & fblk_tr_gnt_d2) ? (fblk_tr_data & {DATA_WIDTH{fblk_tr_vld}}) : upstrm_tr_data), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff_staging #(.WIDTH(1), .DEPTH(NUM_REPEATER_STAGES)) tr_ntrace_bp_stg_ff (.o_q(upstrm_tr_ntrace_bp), .i_d(dnstrm_tr_ntrace_bp), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(1), .DEPTH(NUM_REPEATER_STAGES)) tr_dst_bp_stg_ff (.o_q(upstrm_tr_dst_bp), .i_d(dnstrm_tr_dst_bp), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(1), .DEPTH(NUM_REPEATER_STAGES)) tr_ntrace_flush_stg_ff (.o_q(upstrm_tr_ntrace_flush), .i_d(dnstrm_tr_ntrace_flush), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(1), .DEPTH(NUM_REPEATER_STAGES)) tr_dst_flush_stg_ff (.o_q(upstrm_tr_dst_flush), .i_d(dnstrm_tr_dst_flush), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff_staging #(.WIDTH(NUM_CORES_IN_PATH), .DEPTH(NUM_REPEATER_STAGES)) tr_enabled_srcs_stg_ff (.o_q(upstrm_tr_enabled_srcs), .i_d(dnstrm_tr_enabled_srcs), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  dfd_rv_dff #(.WIDTH(1)) fblk_tr_gnt_d1_ff(.o_q(fblk_tr_gnt_d1), .i_d(fblk_tr_gnt), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));
  dfd_rv_dff #(.WIDTH(1)) fblk_tr_gnt_d2_ff(.o_q(fblk_tr_gnt_d2), .i_d(fblk_tr_gnt_d1), .i_en(1'b1), .i_clk(clk), .i_reset_n(reset_n));

  // --------------------------------------------------------------------------
  // Grant and Select signals
  // --------------------------------------------------------------------------
  assign fblk_tr_gnt = tr_gnt_to_fblk[0] & upstrm_tr_enabled_srcs[RELATIVE_CORE_IDX];
  assign fblk_tr_dst_bp = upstrm_tr_dst_bp & upstrm_tr_enabled_srcs[RELATIVE_CORE_IDX];
  assign fblk_tr_ntrace_bp = upstrm_tr_ntrace_bp & upstrm_tr_enabled_srcs[RELATIVE_CORE_IDX];
  assign fblk_tr_dst_flush = upstrm_tr_dst_flush & upstrm_tr_enabled_srcs[RELATIVE_CORE_IDX];
  assign fblk_tr_ntrace_flush = upstrm_tr_ntrace_flush & upstrm_tr_enabled_srcs[RELATIVE_CORE_IDX];

endmodule

