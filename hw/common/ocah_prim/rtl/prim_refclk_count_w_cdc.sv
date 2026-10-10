// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Count on refclk_i and synchronize the value into out_clk_i.
//
// cnt_en_i enables counting; cnt_update_i, in the out_clk_i domain, sends
// cnt_update_value_i through a one-entry async FIFO and the counter loads it on refclk_i.
// An update that arrives while counting is disabled is discarded, and a second update
// written before the first has crossed is dropped.
// REF_COUNT_WIDTH defaults to 54, about five years at 100 MHz.
// prst_ni is the async reset for the reference domain; it is also synchronized into
// out_clk_i for the FIFO write side.
// Split the counter into parallel chunks for timing.
// count_o crosses into out_clk_i in Gray code through a three-flop synchronizer.

`include "ocah_registers.svh"

module prim_refclk_count_w_cdc #(
  parameter int unsigned REF_COUNT_WIDTH = 54,  // Reference counter width; ~5 years at 100 MHz when
                                                // 54.

  localparam type ref_count_t = logic [REF_COUNT_WIDTH-1:0]  // Counter type alias.
) (
  input logic refclk_i,  // Reference clock.
  input logic prst_ni,  // Async reset in the reference domain, active-low.
  input logic out_clk_i,  // Destination clock for the CDC'd count and clock of cnt_update_i.

  input logic cnt_en_i,  // Enables counting on refclk_i; asynchronous, synchronized into refclk_i.
  input logic cnt_update_i,  // Single-cycle update strobe in the out_clk_i domain.
  input ref_count_t cnt_update_value_i,  // Value loaded when cnt_update_i is high; out_clk_i
                                         // domain.

  output ref_count_t count_o  // Count synchronized into out_clk_i.
);

  // for timing purposes, split bin count into chunks
  // and calculate the chunks in parallel
  localparam int unsigned ChunkSize = 16;
  localparam int unsigned NumChunks = (REF_COUNT_WIDTH + ChunkSize - 1) / ChunkSize;
  localparam int unsigned FinalChunkWidth = (ChunkSize * NumChunks) - REF_COUNT_WIDTH;

  // need overflow bit
  typedef logic [ChunkSize:0] chunk_count_t;

  ref_count_t gray_count, gray_count_sync;
  ref_count_t bin_count, bin_count_next;

  chunk_count_t [NumChunks-1:0] bin_count_chunk;
  logic [NumChunks-1:0] chunk_overflow;

  ref_count_t ref_count_sync_gray;
  logic ref_cnt_en;

  prim_sync3 #(
    .WIDTH(1)
  ) u_sync_cnt_en_count (
    .clk_i(refclk_i),
    .d_i  (cnt_en_i),
    .q_o  (ref_cnt_en)
  );

  logic prstb_synced_write;
  logic prstb_synced_rd;

  prim_sync_reset #(
    .WIDTH(16)
  ) u_prst_wr_clk_domain_sync (
    .clk_i(out_clk_i),
    .rst_ni(prst_ni),
    .test_mode_i(1'b0),
    .scan_rst_ni(1'b0),
    .sync_rst_no(prstb_synced_write)
  );
  prim_sync_reset #(
    .WIDTH(16)
  ) u_prst_rd_clk_domain_sync (
    .clk_i(refclk_i),
    .rst_ni(prst_ni),
    .test_mode_i(1'b0),
    .scan_rst_ni(1'b0),
    .sync_rst_no(prstb_synced_rd)
  );

  ref_count_t cnt_update_value_sync;
  logic       cnt_update_value_valid;

  // Depth kept in a localparam so the occupancy-output widths below stay in step
  // with the instantiation; prim_fifo_async derives DepthW = $clog2(Depth+1).
  localparam int unsigned CntFifoDepth = 1;
  localparam int unsigned CntFifoDepthW = $clog2(CntFifoDepth + 1);

  logic                       cnt_fifo_wready;
  logic [CntFifoDepthW-1:0]   cnt_fifo_wdepth;
  logic [CntFifoDepthW-1:0]   cnt_fifo_rdepth;

  prim_fifo_async #(
    .Width(REF_COUNT_WIDTH),
    .Depth(CntFifoDepth),
    .OutputZeroIfEmpty(0)
  ) u_cnt_update_async_fifo (
    .clk_wr_i(out_clk_i),
    .rst_wr_ni(prstb_synced_write), // async reset, should be okay to use same reset
    .wvalid_i(cnt_update_i),
    .wready_o(cnt_fifo_wready),
    .wdata_i(cnt_update_value_i),
    .wdepth_o(cnt_fifo_wdepth),

    .clk_rd_i(refclk_i),
    .rst_rd_ni(prstb_synced_rd),
    .rvalid_o(cnt_update_value_valid),
    .rready_i(1'b1), // always ready
    .rdata_o(cnt_update_value_sync),
    .rdepth_o(cnt_fifo_rdepth)
  );

  // The FIFO is Depth(1), so a counter update arriving before the previous one has
  // crossed to refclk_i would be dropped with no error indication. No current writer
  // does that (the only writes are single write-then-poll), but nothing enforces it,
  // so catch it in simulation if it ever happens.
  `OCAH_OT_ASSERT(CntUpdateAccepted_A, cnt_update_i |-> cnt_fifo_wready, out_clk_i,
                  !prstb_synced_write)

  // Tie off unused signals to satisfy lint. Keep in separate reductions because they live in diff clk domains
  logic unused_cnt_fifo_wready;
  logic unused_cnt_fifo_wdepth;
  logic unused_cnt_fifo_rdepth;
  assign unused_cnt_fifo_wready = ^cnt_fifo_wready;
  assign unused_cnt_fifo_wdepth = ^cnt_fifo_wdepth;
  assign unused_cnt_fifo_rdepth = ^cnt_fifo_rdepth;

  always_ff @(posedge refclk_i or negedge prstb_synced_rd) begin
    if (!prstb_synced_rd) begin
      bin_count <= ref_count_t'(0);
    end else if (ref_cnt_en) begin
      bin_count <= bin_count_next;
    end
  end

  // ---
  // The below ensures the counter calculation is parallelized
  // ---
  // 1 is added to each chunk to calculate ahead of time what the next
  //  value of the chunk would be
  // Only apply the chunk value to the bin_count_next if every chunk
  //  before it will overflow, meaning the current chunk in the counter
  //  also needs to update its value
  // This constrains the critical path of this counter to be ChunkSize
  //  number of ADDERs + the delay of a (NumChunks-1) input AND gate
  for (genvar i = 0; i < NumChunks; i++) begin : gen_gray_code_counter
    assign chunk_overflow[i] = bin_count_chunk[i][ChunkSize];
    // first chunk and not last chunk, no previous chunks to check, just assign directly
    if ((i == 0) && (i != (NumChunks - 1))) begin : gen_first_chunk
      always_comb begin
        bin_count_chunk[i] = {1'b0, bin_count[ChunkSize-1:0]};
        if (cnt_update_value_valid) begin
          bin_count_next[ChunkSize-1:0] = cnt_update_value_sync[ChunkSize-1:0];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[ChunkSize-1:0] = bin_count[ChunkSize-1:0];
          end else begin
            bin_count_chunk[i] = bin_count[ChunkSize-1:0] + chunk_count_t'(1);

            bin_count_next[ChunkSize-1:0] = bin_count_chunk[i][ChunkSize-1:0];
          end
        end
      end
      // middle chunks, need to check if prev chunks all overflowed to know what to assign
    end else if (i != (NumChunks - 1)) begin : gen_middle_chunk
      always_comb begin
        bin_count_chunk[i] = {1'b0, bin_count[((i+1)*ChunkSize-1):(i*ChunkSize)]};
        if (cnt_update_value_valid) begin
          bin_count_next[((i+1)*ChunkSize-1):(i*ChunkSize)] = cnt_update_value_sync[((i+1)*ChunkSize-1):(i*ChunkSize)];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[((i+1)*ChunkSize-1):(i*ChunkSize)] = bin_count[((i+1)*ChunkSize-1):(i*ChunkSize)];
          end else begin
            bin_count_chunk[i] = bin_count[((i+1)*ChunkSize-1):(i*ChunkSize)] + chunk_count_t'(1);

            bin_count_next[((i+1)*ChunkSize-1):(i*ChunkSize)] = &(chunk_overflow[i-1:0]) ? bin_count_chunk[i][ChunkSize-1:0] : bin_count[((i+1)*ChunkSize-1):(i*ChunkSize)];
          end
        end
      end
      // last chunk, same as middle chunks but also change assignment width for lint
    end else begin : gen_last_chunk
      always_comb begin
        bin_count_chunk[i] = {
          1'b0, {FinalChunkWidth{1'b0}}, bin_count[(REF_COUNT_WIDTH-1):(i*ChunkSize)]
        };
        if (cnt_update_value_valid) begin
          bin_count_next[(REF_COUNT_WIDTH-1):(i*ChunkSize)] = cnt_update_value_sync[(REF_COUNT_WIDTH-1):(i*ChunkSize)];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[(REF_COUNT_WIDTH-1):(i*ChunkSize)] = bin_count[(REF_COUNT_WIDTH-1):(i*ChunkSize)];
          end else begin
            bin_count_chunk[i] = {{FinalChunkWidth{1'b0}},bin_count[(REF_COUNT_WIDTH-1):(i*ChunkSize)]} + chunk_count_t'(1);

            bin_count_next[(REF_COUNT_WIDTH-1):(i*ChunkSize)]  = &(chunk_overflow[i-1:0]) ? bin_count_chunk[i][REF_COUNT_WIDTH-(i*ChunkSize)-1:0] : bin_count[(REF_COUNT_WIDTH-1):(i*ChunkSize)];
          end
        end
      end
    end
  end

  prim_bin2gray #(
    .N(REF_COUNT_WIDTH)
  ) u_prim_bin2gray (
    .a_i(bin_count),
    .z_o(gray_count)
  );

  `OCAH_FF(gray_count_sync, gray_count, ref_count_t'(0), refclk_i, prstb_synced_rd)

  prim_sync3 #(
    .WIDTH(REF_COUNT_WIDTH)
  ) u_sync_ref_count (
    .clk_i(out_clk_i),
    .d_i  (gray_count_sync),
    .q_o  (ref_count_sync_gray)
  );

  prim_gray2bin #(
    .N(REF_COUNT_WIDTH)
  ) u_prim_gray2bin (
    .a_i(ref_count_sync_gray),
    .z_o(count_o)
  );

endmodule
