// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// AVSBus Async FIFO
//
//-----------------------------------------------------------------------------

module avsbus_async_fifo #(
  parameter int unsigned DEPTH = 8,
  parameter int unsigned WIDTH = 32
) (
  input logic i_scan_rst_n,
  input logic i_test_mode,

  input logic i_reset_n_wr_clk_syncd,
  input logic i_wr_clk,
  input logic i_wr_en,
  input logic [WIDTH-1:0] i_wr_data,
  output logic o_wr_full,
  output logic o_wr_empty,

  input logic i_reset_n_rd_clk_syncd,
  input logic i_rd_clk,
  input logic i_rd_en,
  output logic [WIDTH-1:0] o_rd_data,
  output logic o_rd_empty,
  output logic [$clog2(DEPTH):0] o_vacant_slots,
  output logic [$clog2(DEPTH):0] o_full_slots
);

  //NOTE: DEPTH must be a power of 2 for this fifo to work (otherwise gray code counter will not work).
  localparam int unsigned PointerWidth = $clog2(DEPTH) + 1;
  typedef logic [PointerWidth-1:0] pointer_t;

  pointer_t wr_ptr_bin, wr_ptr_gray, wr_ptr_bin_rd_clk, wr_ptr_gray_rd_clk;
  pointer_t rd_ptr_bin, rd_ptr_gray, rd_ptr_bin_wr_clk, rd_ptr_gray_wr_clk;

  logic [WIDTH-1:0] fifo_array[DEPTH];
  logic wr_ptr_wrapped;
  logic [$clog2(DEPTH)+1:0] full_slots;


  assign wr_ptr_bin = gray_to_bin(wr_ptr_gray);
  assign rd_ptr_bin = gray_to_bin(rd_ptr_gray);

  assign wr_ptr_bin_rd_clk = gray_to_bin(wr_ptr_gray_rd_clk);
  assign rd_ptr_bin_wr_clk = gray_to_bin(rd_ptr_gray_wr_clk);


  always_ff @(posedge i_wr_clk) begin
    if (~i_reset_n_wr_clk_syncd) begin
      wr_ptr_gray <= '0;
    end else begin
      wr_ptr_gray <= i_wr_en & ~o_wr_full ? bin_to_gray(wr_ptr_bin + 1) : wr_ptr_gray;
    end
  end

  always_ff @(posedge i_rd_clk) begin
    if (~i_reset_n_rd_clk_syncd) begin
      rd_ptr_gray <= '0;
    end else begin
      rd_ptr_gray <= i_rd_en & ~o_rd_empty ? bin_to_gray(rd_ptr_bin + 1) : rd_ptr_gray;
    end
  end

  prim_sync3 wr_ptr_gray_sync_to_rd_clk[PointerWidth-1:0] (
    .i_clk(i_rd_clk),
    .i_d  (wr_ptr_gray),
    .o_q  (wr_ptr_gray_rd_clk)
  );

  prim_sync3 rd_ptr_gray_sync_to_wr_clk[PointerWidth-1:0] (
    .i_clk(i_wr_clk),
    .i_d  (rd_ptr_gray),
    .o_q  (rd_ptr_gray_wr_clk)
  );

  assign o_rd_empty = (wr_ptr_bin_rd_clk == rd_ptr_bin);
  assign o_wr_empty = (wr_ptr_bin == rd_ptr_bin_wr_clk);
  assign o_wr_full = (rd_ptr_bin_wr_clk[PointerWidth-1] != wr_ptr_bin[PointerWidth-1]) &  (rd_ptr_bin_wr_clk[PointerWidth-2:0] == wr_ptr_bin[PointerWidth-2:0]);

  assign wr_ptr_wrapped = rd_ptr_bin_wr_clk[PointerWidth-1] & ~wr_ptr_bin[PointerWidth-1];
  assign full_slots = (PointerWidth+1)'({wr_ptr_wrapped, wr_ptr_bin} - {1'b0, rd_ptr_bin_wr_clk});
  assign o_full_slots = full_slots[PointerWidth-1:0];
  assign o_vacant_slots = DEPTH - full_slots[PointerWidth-1:0];




  always_ff @(posedge i_wr_clk) begin
    if (i_wr_en & ~o_wr_full) begin
      fifo_array[wr_ptr_bin[PointerWidth-2:0]] <= i_wr_data;
    end
  end

  assign o_rd_data = fifo_array[rd_ptr_bin[PointerWidth-2:0]];

  function automatic pointer_t bin_to_gray(input pointer_t bin_val);
    bin_to_gray = bin_val ^ (bin_val >> 1);
  endfunction


  function automatic pointer_t gray_to_bin(input pointer_t gray_val);
    for (int i = 0; i < PointerWidth; i++) gray_to_bin[i] = ^(gray_val >> i);
  endfunction



endmodule
