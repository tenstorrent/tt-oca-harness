// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//--------------------------------------------------
// Reference clock counter with CDC
//
//--------------------------------------------------
module prim_refclk_count_w_cdc #(
  parameter int unsigned REF_COUNT_WIDTH = 54,  // ~5 years at 100MHz

  localparam type ref_count_t = logic [REF_COUNT_WIDTH-1:0]
) (
  input logic refclk_i,
  input logic prst_ni,
  input logic out_clk_i,

  input logic cnt_en_i,
  input logic cnt_update_i,
  input ref_count_t cnt_update_value_i,

  output ref_count_t count_o
);

  // for timing purposes, split bin count into chunks
  // and calculate the chunks in parallel
  localparam int unsigned CHUNK_SIZE = 16;
  localparam int unsigned NUM_CHUNKS = (REF_COUNT_WIDTH + CHUNK_SIZE - 1) / CHUNK_SIZE;
  localparam int unsigned FINAL_CHUNK_WIDTH = (CHUNK_SIZE * NUM_CHUNKS) - REF_COUNT_WIDTH;

  // need overflow bit
  typedef logic [CHUNK_SIZE:0] chunk_count_t;

  ref_count_t gray_count, gray_count_sync;
  ref_count_t bin_count, bin_count_next;

  chunk_count_t [NUM_CHUNKS-1:0] bin_count_chunk;
  logic [NUM_CHUNKS-1:0] chunk_overflow;

  ref_count_t ref_count_sync_gray;
  logic ref_cnt_en;

  prim_sync3 #(
    .WIDTH(1)
  ) sync_cnt_en_count (
    .i_clk(refclk_i),
    .i_d  (cnt_en_i),
    .o_q  (ref_cnt_en)
  );

  logic prstb_synced_write;
  logic prstb_synced_rd;

  prim_sync_reset #(
    .WIDTH(16)
  ) prst_wr_clk_domain_sync (
    .clk(out_clk_i),
    .rst_n(prst_ni),
    .test_mode(1'b0),
    .scan_rst_n(1'b0),
    .sync_rst_n(prstb_synced_write)
  );
  prim_sync_reset #(
    .WIDTH(16)
  ) prst_rd_clk_domain_sync (
    .clk(refclk_i),
    .rst_n(prst_ni),
    .test_mode(1'b0),
    .scan_rst_n(1'b0),
    .sync_rst_n(prstb_synced_rd)
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
  ) cnt_update_async_fifo (
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
  // This constrains the critical path of this counter to be CHUNK_SIZE
  //  number of ADDERs + the delay of a (NUM_CHUNKS-1) input AND gate
  for (genvar i = 0; i < NUM_CHUNKS; i++) begin : gen_gray_code_counter
    assign chunk_overflow[i] = bin_count_chunk[i][CHUNK_SIZE];
    // first chunk and not last chunk, no previous chunks to check, just assign directly
    if ((i == 0) && (i != (NUM_CHUNKS - 1))) begin : gen_first_chunk
      always_comb begin
        bin_count_chunk[i] = {1'b0, bin_count[CHUNK_SIZE-1:0]};
        if (cnt_update_value_valid) begin
          bin_count_next[CHUNK_SIZE-1:0] = cnt_update_value_sync[CHUNK_SIZE-1:0];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[CHUNK_SIZE-1:0] = bin_count[CHUNK_SIZE-1:0];
          end else begin
            bin_count_chunk[i] = bin_count[CHUNK_SIZE-1:0] + chunk_count_t'(1);

            bin_count_next[CHUNK_SIZE-1:0] = bin_count_chunk[i][CHUNK_SIZE-1:0];
          end
        end
      end
      // middle chunks, need to check if prev chunks all overflowed to know what to assign
    end else if (i != (NUM_CHUNKS - 1)) begin : gen_middle_chunk
      always_comb begin
        bin_count_chunk[i] = {1'b0, bin_count[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)]};
        if (cnt_update_value_valid) begin
          bin_count_next[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)] = cnt_update_value_sync[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)] = bin_count[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)];
          end else begin
            bin_count_chunk[i] = bin_count[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)] + chunk_count_t'(1);

            bin_count_next[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)] = &(chunk_overflow[i-1:0]) ? bin_count_chunk[i][CHUNK_SIZE-1:0] : bin_count[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)];
          end
        end
      end
      // last chunk, same as middle chunks but also change assignment width for lint
    end else begin : gen_last_chunk
      always_comb begin
        bin_count_chunk[i] = {
          1'b0, {FINAL_CHUNK_WIDTH{1'b0}}, bin_count[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)]
        };
        if (cnt_update_value_valid) begin
          bin_count_next[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)] = cnt_update_value_sync[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)];
        end else begin
          if (!ref_cnt_en) begin
            bin_count_next[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)] = bin_count[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)];
          end else begin
            bin_count_chunk[i] = {{FINAL_CHUNK_WIDTH{1'b0}},bin_count[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)]} + chunk_count_t'(1);

            bin_count_next[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)]  = &(chunk_overflow[i-1:0]) ? bin_count_chunk[i][REF_COUNT_WIDTH-(i*CHUNK_SIZE)-1:0] : bin_count[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)];
          end
        end
      end
    end
  end

  prim_bin2gray #(
    .N(REF_COUNT_WIDTH)
  ) prim_bin2gray (
    .a_i(bin_count),
    .z_o(gray_count)
  );

  always_ff @(posedge refclk_i or negedge prstb_synced_rd) begin
    if (!prstb_synced_rd) begin
      gray_count_sync <= ref_count_t'(0);
    end else begin
      gray_count_sync <= gray_count;
    end
  end

  prim_sync3 #(
    .WIDTH(REF_COUNT_WIDTH)
  ) sync_ref_count (
    .i_clk(out_clk_i),
    .i_d  (gray_count_sync),
    .o_q  (ref_count_sync_gray)
  );

  prim_gray2bin #(
    .N(REF_COUNT_WIDTH)
  ) prim_gray2bin (
    .a_i(ref_count_sync_gray),
    .z_o(count_o)
  );

endmodule
