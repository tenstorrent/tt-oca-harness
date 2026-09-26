// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Cross AVSBus data between the write and read clock domains in an async FIFO.
//
// Each side takes its own synchronized reset.
// vacant_slots_o and full_slots_o report occupancy for flow control.

module avsbus_async_fifo #(
  parameter int unsigned DEPTH = 8,                         // FIFO depth in words.
  parameter int unsigned WIDTH = 32                         // FIFO data width in bits.
) (
  input logic scan_rst_ni,                                  // DFT scan reset, active-low.
  input logic test_mode_i,                                  // DFT test mode.

  input logic rst_wr_clk_syncd_ni,                          // Write-side reset, synchronized to wr_clk_i.
  input logic wr_clk_i,                                     // Write clock.
  input logic wr_en_i,                                      // Write enable.
  input logic [WIDTH-1:0] wr_data_i,                        // Write data.
  output logic wr_full_o,                                   // FIFO full in the write domain.
  output logic wr_empty_o,                                  // FIFO empty in the write domain.

  input logic rst_rd_clk_syncd_ni,                          // Read-side reset, synchronized to rd_clk_i.
  input logic rd_clk_i,                                     // Read clock.
  input logic rd_en_i,                                      // Read enable.
  output logic [WIDTH-1:0] rd_data_o,                       // Read data.
  output logic rd_empty_o,                                  // FIFO empty in the read domain.
  output logic [$clog2(DEPTH):0] vacant_slots_o,            // Free entries visible to the reader.
  output logic [$clog2(DEPTH):0] full_slots_o               // Occupied entries visible to the reader.
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


  always_ff @(posedge wr_clk_i) begin
    if (~rst_wr_clk_syncd_ni) begin
      wr_ptr_gray <= '0;
    end else begin
      wr_ptr_gray <= wr_en_i & ~wr_full_o ? bin_to_gray(wr_ptr_bin + 1) : wr_ptr_gray;
    end
  end

  always_ff @(posedge rd_clk_i) begin
    if (~rst_rd_clk_syncd_ni) begin
      rd_ptr_gray <= '0;
    end else begin
      rd_ptr_gray <= rd_en_i & ~rd_empty_o ? bin_to_gray(rd_ptr_bin + 1) : rd_ptr_gray;
    end
  end

  prim_sync3 u_wr_ptr_gray_sync_to_rd_clk[PointerWidth-1:0] (
    .clk_i(rd_clk_i),
    .d_i  (wr_ptr_gray),
    .q_o  (wr_ptr_gray_rd_clk)
  );

  prim_sync3 u_rd_ptr_gray_sync_to_wr_clk[PointerWidth-1:0] (
    .clk_i(wr_clk_i),
    .d_i  (rd_ptr_gray),
    .q_o  (rd_ptr_gray_wr_clk)
  );

  assign rd_empty_o = (wr_ptr_bin_rd_clk == rd_ptr_bin);
  assign wr_empty_o = (wr_ptr_bin == rd_ptr_bin_wr_clk);
  assign wr_full_o = (rd_ptr_bin_wr_clk[PointerWidth-1] != wr_ptr_bin[PointerWidth-1]) &  (rd_ptr_bin_wr_clk[PointerWidth-2:0] == wr_ptr_bin[PointerWidth-2:0]);

  assign wr_ptr_wrapped = rd_ptr_bin_wr_clk[PointerWidth-1] & ~wr_ptr_bin[PointerWidth-1];
  assign full_slots = (PointerWidth+1)'({wr_ptr_wrapped, wr_ptr_bin} - {1'b0, rd_ptr_bin_wr_clk});
  assign full_slots_o = full_slots[PointerWidth-1:0];
  assign vacant_slots_o = DEPTH - full_slots[PointerWidth-1:0];




  always_ff @(posedge wr_clk_i) begin
    if (wr_en_i & ~wr_full_o) begin
      fifo_array[wr_ptr_bin[PointerWidth-2:0]] <= wr_data_i;
    end
  end

  assign rd_data_o = fifo_array[rd_ptr_bin[PointerWidth-2:0]];

  function automatic pointer_t bin_to_gray(input pointer_t bin_val);
    bin_to_gray = bin_val ^ (bin_val >> 1);
  endfunction


  function automatic pointer_t gray_to_bin(input pointer_t gray_val);
    for (int i = 0; i < PointerWidth; i++) gray_to_bin[i] = ^(gray_val >> i);
  endfunction



endmodule
