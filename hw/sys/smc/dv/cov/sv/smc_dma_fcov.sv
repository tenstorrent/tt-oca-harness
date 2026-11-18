// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC DMA functional coverage: the stream-0 command launch, what the
// programmed length turns into on the AXI master, the clock gating of the
// frontend against the request-manager/backend clock, and the launch
// geometry of smc_dma_geometry_cg.
//
// The DMA carries two independent gaters, so "gated together" is covered as
// both gated clocks held in the same sample rather than as one enable.
//
// One instance in the shared tb_top serves both flows. Every port is a
// smc_tb_signal_list.svh signal.
//
// CONVENTION (see dtp_fcov.sv): every cover-property body and disable-iff
// argument is a single continuous-assign wire; no declaration initializers
// on always_ff-driven variables; declare wires before use.

`include "ocah_fcov_macros.svh"

module smc_dma_fcov (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // Stream-0 command registers.
  input wire next_id_re_i,
  input wire [31:0] next_id_i,
  input wire [9:0] status0_i,
  input wire [31:0] done_id_i,
  input wire done_id_re_i,
  input wire [63:0] src_addr_i,
  input wire [63:0] dst_addr_i,
  input wire [63:0] length_i,
  input wire [63:0] reps_i,

  // SEP_IN write channels, for the DMA CONFIG register as written.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i,

  // Frontend request handshake and completion.
  input wire fe_req_valid_i,
  input wire fe_req_ready_i,
  input wire trans_complete_i,

  // AXI master port.
  input wire mst_awvalid_i,
  input wire mst_awready_i,
  input wire [55:0] mst_awaddr_i,
  input wire [7:0] mst_awlen_i,
  input wire mst_wvalid_i,
  input wire mst_wready_i,
  input wire mst_wlast_i,
  input wire [7:0] mst_wstrb_i,

  // Clock gating.
  input wire cg_en_i,
  input wire gated_clk_i,
  input wire frontend_gated_clk_i,
  input wire frontend_wakeup_i,
  input wire backend_busy_i
);

  import smc_top_addrmap_pkg::SMC_TOP_DMA_CTRL_CONFIG_BASE_ADDR;

  wire in_reset = (rst_cold_ni !== 1'b1);

  // ------------------------------------------------------------------
  // Stream-0 launch. Reading NEXT_ID_0 is the launch: the read strobe is
  // the event, and the returned transfer id is never 0.
  // ------------------------------------------------------------------
  wire next_id_read_e = (next_id_re_i === 1'b1);
  wire next_id_nonzero_e = next_id_read_e && (next_id_i !== 32'd0) && (^next_id_i !== 1'bx);
  `OCAH_FCOV_COVER(c_next_id_0_nonzero_on_valid_setup, next_id_nonzero_e, clk_smc_i, in_reset)

  // The read reaches the frontend as an accepted request. The read strobe
  // alone would be covered by a read of an unconfigured DMA.
  logic next_id_read_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) next_id_read_q <= 1'b0;
    else if (next_id_read_e) next_id_read_q <= 1'b1;
    else if (fe_req_valid_i === 1'b1 && fe_req_ready_i === 1'b1) next_id_read_q <= 1'b0;
  end

  wire fe_req_acc = (fe_req_valid_i === 1'b1) && (fe_req_ready_i === 1'b1);
  wire launch_e = fe_req_acc && next_id_read_q;
  wire shared_regs_consumed_e = launch_e && (src_addr_i !== 64'd0) && (dst_addr_i !== 64'd0)
      && (length_i !== 64'd0);
  `OCAH_FCOV_COVER(c_next_id_0_launches_transfer, launch_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_shared_registers_consumed, shared_regs_consumed_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // STATUS_0 and DONE_0 across the launched transfer. STATUS_0 bit 9 is the
  // midend-busy lane; the low lanes report whether another command can be
  // issued, so "busy" is that lane clear while a transfer is in flight.
  // ------------------------------------------------------------------
  logic transfer_in_flight_q;
  logic [31:0] done_id_q;
  logic done_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      transfer_in_flight_q <= 1'b0;
      done_id_q <= '0;
      done_seen_q <= 1'b0;
    end else begin
      if (launch_e) transfer_in_flight_q <= 1'b1;
      else if (trans_complete_i === 1'b1) transfer_in_flight_q <= 1'b0;
      done_id_q <= done_id_i;
      if (done_id_i !== 32'd0 && (^done_id_i !== 1'bx)) done_seen_q <= 1'b1;
    end
  end

  wire status0_busy_e = transfer_in_flight_q && (status0_i !== 10'h3FF) && (^status0_i !== 1'bx);
  wire done0_set_e = (done_id_i !== done_id_q) && (done_id_i !== 32'd0) && (^done_id_q !== 1'bx);
  // dma_ctrl.rdl DONE: "Retirement counter for the stream. Resets to 1 and adds 1 per
  // retirement", so a read after a completion returns the retired count and leaves it in place.
  wire done0_holds_e = done_seen_q && (done_id_re_i === 1'b1) && (done_id_q !== 32'd0)
      && (done_id_i === done_id_q);
  `OCAH_FCOV_COVER(c_status0_busy_during, status0_busy_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_done0_set_on_completion, done0_set_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_done0_holds_after_read, done0_holds_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Programmed length against what the master moved. The byte counter sums
  // the strobes of every accepted write beat between launch and completion
  // and is compared with the programmed length at completion, so the point
  // says the programmed byte count arrived, not merely that beats moved.
  // ------------------------------------------------------------------
  wire aw_acc = (mst_awvalid_i === 1'b1) && (mst_awready_i === 1'b1);
  wire w_acc = (mst_wvalid_i === 1'b1) && (mst_wready_i === 1'b1);

  logic [7:0] strb_ones;
  always_comb begin
    strb_ones = '0;
    for (int unsigned b = 0; b < 8; b++) begin
      if (mst_wstrb_i[b] === 1'b1) strb_ones = strb_ones + 8'd1;
    end
  end

  logic [63:0] bytes_written_q;
  logic [55:0] first_wr_addr_q;
  logic [63:0] launch_length_q;
  logic [63:0] launch_dst_q;
  logic first_aw_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      bytes_written_q <= '0;
      first_wr_addr_q <= '0;
      launch_length_q <= '0;
      launch_dst_q <= '0;
      first_aw_q <= 1'b1;
    end else if (launch_e) begin
      bytes_written_q <= '0;
      first_wr_addr_q <= '0;
      launch_length_q <= length_i;
      launch_dst_q <= dst_addr_i;
      first_aw_q <= 1'b1;
    end else begin
      if (w_acc) bytes_written_q <= bytes_written_q + 64'(strb_ones);
      if (aw_acc && first_aw_q) begin
        first_wr_addr_q <= mst_awaddr_i;
        first_aw_q <= 1'b0;
      end
    end
  end

  wire len_one_byte_e = launch_e && (length_i === 64'd1);
  wire len_single_beat_e = aw_acc && transfer_in_flight_q && (mst_awlen_i === 8'd0);
  wire len_multi_burst_e = aw_acc && transfer_in_flight_q && (mst_awlen_i !== 8'd0)
      && (^mst_awlen_i !== 1'bx);
  wire dest_contents_match_e = (trans_complete_i === 1'b1) && (launch_length_q !== 64'd0)
      && (bytes_written_q === launch_length_q) && (56'(launch_dst_q) === first_wr_addr_q);
  `OCAH_FCOV_COVER(c_len_one_byte, len_one_byte_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_len_single_beat, len_single_beat_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_len_multi_burst, len_multi_burst_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_dest_contents_match, dest_contents_match_e, clk_smc_i, in_reset)

  // The last beat of a burst, kept separate from the byte count so a burst
  // that terminates without WLAST stays visible as a hole.
  wire w_last_acc_e = w_acc && (mst_wlast_i === 1'b1);
  `OCAH_FCOV_COVER(c_dma_wlast_accepted, w_last_acc_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Clock gating. Both gated clocks are sampled for movement; "gated
  // together" is both held in the same sample, after both were seen moving.
  // ------------------------------------------------------------------
  // A gated clock is observed through a flop it toggles itself. Sampling the
  // clock net on the edge of the clock it is gated from reads the same level
  // every cycle whether it runs or not; the flop changes between two samples
  // exactly when the gated clock had an edge.
  logic gated_clk_div_q, frontend_clk_div_q;
  always_ff @(posedge gated_clk_i) gated_clk_div_q <= (gated_clk_div_q !== 1'b1);
  always_ff @(posedge frontend_gated_clk_i) frontend_clk_div_q <= (frontend_clk_div_q !== 1'b1);

  logic gated_clk_q, frontend_clk_q;
  logic gated_clk_moved_q, frontend_clk_moved_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      gated_clk_q <= 1'b0;
      frontend_clk_q <= 1'b0;
      gated_clk_moved_q <= 1'b0;
      frontend_clk_moved_q <= 1'b0;
    end else begin
      gated_clk_q <= gated_clk_div_q;
      frontend_clk_q <= frontend_clk_div_q;
      if (gated_clk_div_q !== gated_clk_q) gated_clk_moved_q <= 1'b1;
      if (frontend_clk_div_q !== frontend_clk_q) frontend_clk_moved_q <= 1'b1;
    end
  end

  wire gated_clk_toggling = (gated_clk_div_q !== gated_clk_q);
  wire frontend_clk_toggling = (frontend_clk_div_q !== frontend_clk_q);
  wire all_blocks_gated_e = gated_clk_moved_q && frontend_clk_moved_q && !gated_clk_toggling
      && !frontend_clk_toggling;
  `OCAH_FCOV_COVER(c_all_three_blocks_gated_together, all_blocks_gated_e, clk_smc_i, in_reset)

  wire cg_open = (cg_en_i === 1'b1);
  wire wakeup = (frontend_wakeup_i === 1'b1);
  wire backend_busy = (backend_busy_i === 1'b1);

  logic cg_open_seen_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) cg_open_seen_q <= 1'b0;
    else if (cg_open) cg_open_seen_q <= 1'b1;
  end

  wire enable_from_wakeup_e = cg_open && wakeup && !backend_busy;
  wire enable_from_backend_e = cg_open && backend_busy && !wakeup;
  wire gated_when_neither_e = cg_open_seen_q && !cg_open && !wakeup && !backend_busy;
  `OCAH_FCOV_COVER(c_enable_from_frontend_wakeup, enable_from_wakeup_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_enable_from_backend_busy, enable_from_backend_e, clk_smc_i, in_reset)
  `OCAH_FCOV_COVER(c_gated_when_neither, gated_when_neither_e, clk_smc_i, in_reset)

  // ------------------------------------------------------------------
  // Covergroups: the burst-shape and gate crosses the flat point list cannot
  // express.
  // ------------------------------------------------------------------
  covergroup cg_dma_burst with function sample (logic [7:0] awlen, logic [7:0] strb_count);
    option.per_instance = 1;
    cp_awlen: coverpoint awlen {
      bins single = {0}; bins short_burst = {[1 : 7]}; bins long_burst = {[8 : 255]};
    }
    // Every write beat of a transfer carries at least one of its bytes: the
    // length is non-zero (dma.adoc, a length-0 command moves no data) and
    // the backend writes only the bytes of the programmed range.
    cp_strb: coverpoint strb_count {
      bins partial = {[1 : 7]}; bins full = {8}; ignore_bins no_byte = {0};
    }
    x_shape: cross cp_awlen, cp_strb;
  endgroup

  covergroup cg_dma_gates with function sample (
      logic cg_en, logic wakeup, logic backend, logic fe_clk_moving, logic be_clk_moving
  );
    option.per_instance = 1;
    cp_cg_en: coverpoint cg_en;
    cp_wakeup: coverpoint wakeup;
    cp_backend: coverpoint backend;
    cp_fe_clk: coverpoint fe_clk_moving {bins held = {1'b0}; bins running = {1'b1};}
    cp_be_clk: coverpoint be_clk_moving {bins held = {1'b0}; bins running = {1'b1};}
    // {fe_clk_moving, be_clk_moving}. The backend clock runs while the
    // frontend or backend is busy, and the frontend clock runs then too and
    // also while the control port has a transaction outstanding, with the
    // same hysteresis (dma.adoc, SMC DMA Clock Gating Configuration), so the
    // frontend clock is never held while the backend clock runs.
    cp_gaters: coverpoint {
      fe_clk_moving, be_clk_moving
    } {
      bins held_held = {2'b00}; bins running_held = {2'b10}; bins running_running = {2'b11};
    }
    x_sources: cross cp_wakeup, cp_backend;
  endgroup

  cg_dma_burst u_cg_dma_burst = new();
  cg_dma_gates u_cg_dma_gates = new();

  // The strobes live on the W channel, so the shape is sampled per accepted
  // write beat with the length of the burst that beat belongs to.
  logic [7:0] burst_awlen_q;
  always_ff @(posedge clk_smc_i) begin
    if (aw_acc) burst_awlen_q <= mst_awlen_i;
  end
  wire [7:0] beat_awlen = aw_acc ? mst_awlen_i : burst_awlen_q;

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      if (w_acc) u_cg_dma_burst.sample(beat_awlen, strb_ones);
      u_cg_dma_gates.sample(cg_en_i, frontend_wakeup_i, backend_busy_i, frontend_clk_toggling,
                            gated_clk_toggling);
    end
  end

  // ------------------------------------------------------------------
  // smc_dma_geometry_cg (SMC_FCOV.adoc, smc_dma_geometry_cg): the geometry
  // and CONFIG of each launch inside the owner's graded window.
  // ------------------------------------------------------------------
  // CONFIG fields per dma_ctrl.rdl: DECOUPLE_AW [0], SRC_REDUCE_LEN [2],
  // DST_REDUCE_LEN [3], ENABLED_ND [10]; the positions mirror the
  // DMA_CTRL__CONFIG__*_bp of the generated dma_ctrl.h and the
  // DMA_CTRL_CONFIG_*_SHIFT of smc_reg.svh, which this build does not include.
  localparam logic [55:0] DmaConfigAddr = 56'(SMC_TOP_DMA_CTRL_CONFIG_BASE_ADDR);
  localparam int unsigned CfgDecoupleAw = 0;
  localparam int unsigned CfgSrcReduce = 2;
  localparam int unsigned CfgDstReduce = 3;
  localparam int unsigned CfgEnabledNd = 10;

  // CONFIG as written over SEP_IN: the last write that completed OKAY at the
  // CONFIG address, taken from the low 32-bit lane of its single beat with all
  // four strobes assumed set. One SEP_IN write is outstanding at a time. A DMA
  // reset clears the register without a write and this copy follows the cold
  // reset only, so it holds inside a window that drives no other reset.
  wire cfg_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire cfg_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire cfg_b_okay = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1)
      && (sep_bresp_i === 2'b00);

  logic cfg_addr_hit_q;
  logic [31:0] cfg_wdata_q;
  logic [31:0] dma_config_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      cfg_addr_hit_q <= 1'b0;
      cfg_wdata_q <= '0;
      dma_config_q <= '0;
    end else begin
      if (cfg_aw_acc) cfg_addr_hit_q <= (sep_awaddr_i === DmaConfigAddr);
      if (cfg_w_last_acc) cfg_wdata_q <= sep_wdata_i[31:0];
      if (cfg_b_okay && cfg_addr_hit_q) dma_config_q <= cfg_wdata_q;
    end
  end

  // Launch class. A copy moves data: ENABLED_ND set and LENGTH non-zero.
  // dma.adoc names the two commands that move no data: LENGTH 0, and
  // ENABLED_ND clear. A launch with both has no class bin.
  localparam logic [1:0] LaunchCopy = 2'd0;
  localparam logic [1:0] LaunchZeroLength = 2'd1;
  localparam logic [1:0] LaunchNdClear = 2'd2;
  localparam logic [1:0] LaunchNone = 2'd3;
  wire cfg_nd = (dma_config_q[CfgEnabledNd] === 1'b1);
  wire len_zero = (length_i === 64'd0);
  wire [1:0] launch_cls = (cfg_nd && !len_zero) ? LaunchCopy
                        : (cfg_nd && len_zero)  ? LaunchZeroLength
                        : (!cfg_nd && !len_zero) ? LaunchNdClear : LaunchNone;
  wire copy_launch = (launch_cls == LaunchCopy);

  // Row buckets of SMC_FCOV.adoc. LENGTH: 1, 2 to 7, 8, 9 to 255, 256 and
  // above; NUM_REPETITIONS: 1, 2, 3 to 15, 16 and above. A value outside the
  // buckets (0) maps to code 7, which no bin lists.
  function automatic logic [2:0] len_bucket(input logic [63:0] len);
    if (len == 64'd1) return 3'd0;
    if (len >= 64'd2 && len <= 64'd7) return 3'd1;
    if (len == 64'd8) return 3'd2;
    if (len >= 64'd9 && len <= 64'd255) return 3'd3;
    if (len >= 64'd256) return 3'd4;
    return 3'd7;
  endfunction

  function automatic logic [2:0] reps_bucket(input logic [63:0] reps);
    if (reps == 64'd1) return 3'd0;
    if (reps == 64'd2) return 3'd1;
    if (reps >= 64'd3 && reps <= 64'd15) return 3'd2;
    if (reps >= 64'd16) return 3'd3;
    return 3'd7;
  endfunction

  // Each copy coverpoint is a tuple led by the copy flag, and every bin
  // lists flag 1, so a no-data launch, which reuses a drawn transfer's
  // geometry and CONFIG, adds no count to a copy cell. Every cell of a row
  // has a bin; no bin and no ignore_bins share a value.
  covergroup smc_dma_geometry_cg with function sample (
      logic copy,
      logic [2:0] len_b,
      logic [2:0] reps_b,
      logic src_unal,
      logic dst_unal,
      logic src_reduce,
      logic dst_reduce,
      logic decouple_aw,
      logic [1:0] cls
  );
    option.per_instance = 1;
    // {copy, LENGTH bucket, NUM_REPETITIONS bucket}: 20 cells.
    cp_length_reps: coverpoint {
      copy, len_b, reps_b
    } {
      bins l1_r1 = {7'b1_000_000};
      bins l1_r2 = {7'b1_000_001};
      bins l1_r3_15 = {7'b1_000_010};
      bins l1_r16up = {7'b1_000_011};
      bins l2_7_r1 = {7'b1_001_000};
      bins l2_7_r2 = {7'b1_001_001};
      bins l2_7_r3_15 = {7'b1_001_010};
      bins l2_7_r16up = {7'b1_001_011};
      bins l8_r1 = {7'b1_010_000};
      bins l8_r2 = {7'b1_010_001};
      bins l8_r3_15 = {7'b1_010_010};
      bins l8_r16up = {7'b1_010_011};
      bins l9_255_r1 = {7'b1_011_000};
      bins l9_255_r2 = {7'b1_011_001};
      bins l9_255_r3_15 = {7'b1_011_010};
      bins l9_255_r16up = {7'b1_011_011};
      bins l256up_r1 = {7'b1_100_000};
      bins l256up_r2 = {7'b1_100_001};
      bins l256up_r3_15 = {7'b1_100_010};
      bins l256up_r16up = {7'b1_100_011};
    }
    // {copy, source offset in the word non-zero, destination offset
    // non-zero}: 4 cells.
    cp_start: coverpoint {
      copy, src_unal, dst_unal
    } {
      bins s0_d0 = {3'b1_0_0};
      bins s0_d1_7 = {3'b1_0_1};
      bins s1_7_d0 = {3'b1_1_0};
      bins s1_7_d1_7 = {3'b1_1_1};
    }
    // cp_start crossed with cp_length_reps: 80 cells.
    cp_start_x_length_reps: coverpoint {
      copy, len_b, reps_b, src_unal, dst_unal
    } {
      bins l1_r1_s0_d0 = {9'b1_000_000_0_0};
      bins l1_r1_s0_d1_7 = {9'b1_000_000_0_1};
      bins l1_r1_s1_7_d0 = {9'b1_000_000_1_0};
      bins l1_r1_s1_7_d1_7 = {9'b1_000_000_1_1};
      bins l1_r2_s0_d0 = {9'b1_000_001_0_0};
      bins l1_r2_s0_d1_7 = {9'b1_000_001_0_1};
      bins l1_r2_s1_7_d0 = {9'b1_000_001_1_0};
      bins l1_r2_s1_7_d1_7 = {9'b1_000_001_1_1};
      bins l1_r3_15_s0_d0 = {9'b1_000_010_0_0};
      bins l1_r3_15_s0_d1_7 = {9'b1_000_010_0_1};
      bins l1_r3_15_s1_7_d0 = {9'b1_000_010_1_0};
      bins l1_r3_15_s1_7_d1_7 = {9'b1_000_010_1_1};
      bins l1_r16up_s0_d0 = {9'b1_000_011_0_0};
      bins l1_r16up_s0_d1_7 = {9'b1_000_011_0_1};
      bins l1_r16up_s1_7_d0 = {9'b1_000_011_1_0};
      bins l1_r16up_s1_7_d1_7 = {9'b1_000_011_1_1};
      bins l2_7_r1_s0_d0 = {9'b1_001_000_0_0};
      bins l2_7_r1_s0_d1_7 = {9'b1_001_000_0_1};
      bins l2_7_r1_s1_7_d0 = {9'b1_001_000_1_0};
      bins l2_7_r1_s1_7_d1_7 = {9'b1_001_000_1_1};
      bins l2_7_r2_s0_d0 = {9'b1_001_001_0_0};
      bins l2_7_r2_s0_d1_7 = {9'b1_001_001_0_1};
      bins l2_7_r2_s1_7_d0 = {9'b1_001_001_1_0};
      bins l2_7_r2_s1_7_d1_7 = {9'b1_001_001_1_1};
      bins l2_7_r3_15_s0_d0 = {9'b1_001_010_0_0};
      bins l2_7_r3_15_s0_d1_7 = {9'b1_001_010_0_1};
      bins l2_7_r3_15_s1_7_d0 = {9'b1_001_010_1_0};
      bins l2_7_r3_15_s1_7_d1_7 = {9'b1_001_010_1_1};
      bins l2_7_r16up_s0_d0 = {9'b1_001_011_0_0};
      bins l2_7_r16up_s0_d1_7 = {9'b1_001_011_0_1};
      bins l2_7_r16up_s1_7_d0 = {9'b1_001_011_1_0};
      bins l2_7_r16up_s1_7_d1_7 = {9'b1_001_011_1_1};
      bins l8_r1_s0_d0 = {9'b1_010_000_0_0};
      bins l8_r1_s0_d1_7 = {9'b1_010_000_0_1};
      bins l8_r1_s1_7_d0 = {9'b1_010_000_1_0};
      bins l8_r1_s1_7_d1_7 = {9'b1_010_000_1_1};
      bins l8_r2_s0_d0 = {9'b1_010_001_0_0};
      bins l8_r2_s0_d1_7 = {9'b1_010_001_0_1};
      bins l8_r2_s1_7_d0 = {9'b1_010_001_1_0};
      bins l8_r2_s1_7_d1_7 = {9'b1_010_001_1_1};
      bins l8_r3_15_s0_d0 = {9'b1_010_010_0_0};
      bins l8_r3_15_s0_d1_7 = {9'b1_010_010_0_1};
      bins l8_r3_15_s1_7_d0 = {9'b1_010_010_1_0};
      bins l8_r3_15_s1_7_d1_7 = {9'b1_010_010_1_1};
      bins l8_r16up_s0_d0 = {9'b1_010_011_0_0};
      bins l8_r16up_s0_d1_7 = {9'b1_010_011_0_1};
      bins l8_r16up_s1_7_d0 = {9'b1_010_011_1_0};
      bins l8_r16up_s1_7_d1_7 = {9'b1_010_011_1_1};
      bins l9_255_r1_s0_d0 = {9'b1_011_000_0_0};
      bins l9_255_r1_s0_d1_7 = {9'b1_011_000_0_1};
      bins l9_255_r1_s1_7_d0 = {9'b1_011_000_1_0};
      bins l9_255_r1_s1_7_d1_7 = {9'b1_011_000_1_1};
      bins l9_255_r2_s0_d0 = {9'b1_011_001_0_0};
      bins l9_255_r2_s0_d1_7 = {9'b1_011_001_0_1};
      bins l9_255_r2_s1_7_d0 = {9'b1_011_001_1_0};
      bins l9_255_r2_s1_7_d1_7 = {9'b1_011_001_1_1};
      bins l9_255_r3_15_s0_d0 = {9'b1_011_010_0_0};
      bins l9_255_r3_15_s0_d1_7 = {9'b1_011_010_0_1};
      bins l9_255_r3_15_s1_7_d0 = {9'b1_011_010_1_0};
      bins l9_255_r3_15_s1_7_d1_7 = {9'b1_011_010_1_1};
      bins l9_255_r16up_s0_d0 = {9'b1_011_011_0_0};
      bins l9_255_r16up_s0_d1_7 = {9'b1_011_011_0_1};
      bins l9_255_r16up_s1_7_d0 = {9'b1_011_011_1_0};
      bins l9_255_r16up_s1_7_d1_7 = {9'b1_011_011_1_1};
      bins l256up_r1_s0_d0 = {9'b1_100_000_0_0};
      bins l256up_r1_s0_d1_7 = {9'b1_100_000_0_1};
      bins l256up_r1_s1_7_d0 = {9'b1_100_000_1_0};
      bins l256up_r1_s1_7_d1_7 = {9'b1_100_000_1_1};
      bins l256up_r2_s0_d0 = {9'b1_100_001_0_0};
      bins l256up_r2_s0_d1_7 = {9'b1_100_001_0_1};
      bins l256up_r2_s1_7_d0 = {9'b1_100_001_1_0};
      bins l256up_r2_s1_7_d1_7 = {9'b1_100_001_1_1};
      bins l256up_r3_15_s0_d0 = {9'b1_100_010_0_0};
      bins l256up_r3_15_s0_d1_7 = {9'b1_100_010_0_1};
      bins l256up_r3_15_s1_7_d0 = {9'b1_100_010_1_0};
      bins l256up_r3_15_s1_7_d1_7 = {9'b1_100_010_1_1};
      bins l256up_r16up_s0_d0 = {9'b1_100_011_0_0};
      bins l256up_r16up_s0_d1_7 = {9'b1_100_011_0_1};
      bins l256up_r16up_s1_7_d0 = {9'b1_100_011_1_0};
      bins l256up_r16up_s1_7_d1_7 = {9'b1_100_011_1_1};
    }
    // {copy, SRC_REDUCE_LEN, DST_REDUCE_LEN, DECOUPLE_AW}: 8 cells. The
    // *_MAX_LLEN bounds are what the owner checks each burst against, not bins.
    cp_burst_cfg: coverpoint {
      copy, src_reduce, dst_reduce, decouple_aw
    } {
      bins sred0_dred0_aw0 = {4'b1_0_0_0};
      bins sred0_dred0_aw1 = {4'b1_0_0_1};
      bins sred0_dred1_aw0 = {4'b1_0_1_0};
      bins sred0_dred1_aw1 = {4'b1_0_1_1};
      bins sred1_dred0_aw0 = {4'b1_1_0_0};
      bins sred1_dred0_aw1 = {4'b1_1_0_1};
      bins sred1_dred1_aw0 = {4'b1_1_1_0};
      bins sred1_dred1_aw1 = {4'b1_1_1_1};
    }
    // The two launches that move no data: 2 cells.
    cp_no_data: coverpoint cls {
      bins zero_length = {LaunchZeroLength}; bins nd_clear = {LaunchNdClear};
    }
  endgroup

  smc_dma_geometry_cg u_cg_dma_geometry = new();

  // One sample per launch: the NEXT_ID_0 read strobe, with the registers the
  // command consumed, only while the owning leaf holds tb_fcov_gate high.
  wire geometry_sample_e = next_id_read_e && (fcov_gate_i === 1'b1);
  always_ff @(posedge clk_smc_i) begin
    if (!in_reset && geometry_sample_e) begin
      u_cg_dma_geometry.sample(copy_launch, len_bucket(length_i), reps_bucket(reps_i),
                               (src_addr_i[2:0] != 3'd0), (dst_addr_i[2:0] != 3'd0),
                               dma_config_q[CfgSrcReduce], dma_config_q[CfgDstReduce],
                               dma_config_q[CfgDecoupleAw], launch_cls);
    end
  end

endmodule : smc_dma_fcov
