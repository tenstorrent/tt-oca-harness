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
		input logic i_refclk,
		input logic i_prstb,
		input logic i_out_clk,

		input logic i_cnt_en,
		input logic i_cnt_update,
		input ref_count_t i_cnt_update_value,

		output ref_count_t o_count
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

	ref_count_t ref_count_sync_gray, ref_count_sync;
	logic ref_cnt_en;

	prim_sync3 #(
		.WIDTH(1)
	) sync_cnt_en_count (
		.i_clk(i_refclk),
		.i_d  (i_cnt_en),
		.o_q  (ref_cnt_en)
	);

	logic prstb_synced_write;
	logic prstb_synced_rd;

	prim_sync_reset #(
		.WIDTH(16)
	) prst_wr_clk_domain_sync (
		.clk(i_out_clk),
		.rst_n(i_prstb),
		.test_mode(1'b0),
		.scan_rst_n(1'b0),
		.sync_rst_n(prstb_synced_write)
	);
	prim_sync_reset #(
		.WIDTH(16)
	) prst_rd_clk_domain_sync (
		.clk(i_refclk),
		.rst_n(i_prstb),
		.test_mode(1'b0),
		.scan_rst_n(1'b0),
		.sync_rst_n(prstb_synced_rd)
	);

	ref_count_t cnt_update_value_sync;
	logic       cnt_update_value_valid;

	prim_fifo_async #(
		.Width(REF_COUNT_WIDTH),
		.Depth(1),
		.OutputZeroIfEmpty(0)
	) cnt_update_async_fifo (
		.clk_wr_i(i_out_clk),
		.rst_wr_ni(prstb_synced_write), // async reset, should be okay to use same reset
		.wvalid_i(i_cnt_update),
		.wready_o(), // unused
		.wdata_i(i_cnt_update_value),
		.wdepth_o(), // unused

		.clk_rd_i(i_refclk),
		.rst_rd_ni(prstb_synced_rd),
		.rvalid_o(cnt_update_value_valid),
		.rready_i(1'b1), // always ready
		.rdata_o(cnt_update_value_sync),
		.rdepth_o() // unused
	);

	always_ff @(posedge i_refclk or negedge prstb_synced_rd) begin
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
		if ((i == 0) && (i != (NUM_CHUNKS-1))) begin
			always_comb begin
				bin_count_chunk[i] = {1'b0,bin_count[CHUNK_SIZE-1:0]};
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
		end else if (i != (NUM_CHUNKS-1)) begin
			always_comb begin
				bin_count_chunk[i] = {1'b0,bin_count[((i+1)*CHUNK_SIZE-1):(i*CHUNK_SIZE)]};
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
		end else begin
			always_comb begin
				bin_count_chunk[i] = {1'b0,{FINAL_CHUNK_WIDTH{1'b0}},bin_count[(REF_COUNT_WIDTH-1):(i*CHUNK_SIZE)]};
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
		.A(bin_count),
		.Z(gray_count)
	);

	always_ff @(posedge i_refclk or negedge prstb_synced_rd) begin
		if (!prstb_synced_rd) begin
			gray_count_sync <= ref_count_t'(0);
		end else begin
			gray_count_sync <= gray_count;
		end
	end

	prim_sync3 #(
		.WIDTH(REF_COUNT_WIDTH)
	) sync_ref_count (
		.i_clk(i_out_clk),
		.i_d  (gray_count_sync),
		.o_q  (ref_count_sync_gray)
	);

	prim_gray2bin #(
		.N(REF_COUNT_WIDTH)
	) prim_gray2bin (
		.A(ref_count_sync_gray),
		.Z(o_count)
	);

endmodule
