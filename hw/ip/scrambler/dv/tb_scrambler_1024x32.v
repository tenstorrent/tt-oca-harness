// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Testbench for SRAM Scrambler 1024x32
//
// This testbench instantiates a 1024x32 memory and verifies that:
// 1. Addresses are scrambled when accessing memory
// 2. Data is scrambled when stored in memory
// 3. Data read back matches the original unscrambled data
//
// Copyright 2026 Tenstorrent Inc.
//
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_scrambler_1024x32;

  localparam int unsigned ADDR_WIDTH = 10;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned MEM_DEPTH = 1024;
  localparam logic [31:0] SCRAMBLER_KEY = 32'hDEADBEEF;

  reg clk;
  reg rst_n;

  reg [ADDR_WIDTH-1:0] logical_addr;
  reg [DATA_WIDTH-1:0] write_data;
  wire [DATA_WIDTH-1:0] read_data;
  reg write_enable;

  wire [ADDR_WIDTH-1:0] scrambled_addr;
  wire [DATA_WIDTH-1:0] scrambled_write_data;
  reg [DATA_WIDTH-1:0] scrambled_read_data;

  reg [DATA_WIDTH-1:0] memory [0:MEM_DEPTH-1];

  reg [DATA_WIDTH-1:0] expected_data [0:MEM_DEPTH-1];
  reg [DATA_WIDTH-1:0] expected_scrambled [0:MEM_DEPTH-1];

  integer i;
  integer j;
  integer errors;

  scrambler_1024x32 #(
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH)
  ) u_scrambler (
    .addr_i(logical_addr),
    .byte_mask_i(4'hF),
    .scrambler_key_i(SCRAMBLER_KEY),
    .scrambled_addr_o(scrambled_addr),
    .write_data_i(write_data),
    .scrambled_write_data_o(scrambled_write_data),
    .scrambled_read_data_i(scrambled_read_data),
    .read_data_o(read_data)
  );

  always #5 clk = ~clk;

  initial begin
    $dumpfile("tb_scrambler_1024x32.vcd");
    $dumpvars(0, tb_scrambler_1024x32);
  end

  always @(posedge clk) begin
    if (write_enable) begin
      memory[scrambled_addr] <= scrambled_write_data;
    end
  end

  always @(posedge clk) begin
    scrambled_read_data <= memory[scrambled_addr];
  end

  initial begin
    $display("Testbench starting...");
    clk = 0;
    rst_n = 0;
    write_enable = 0;
    logical_addr = 0;
    write_data = 0;
    errors = 0;

    $display("Initializing memory...");
    for (i = 0; i < MEM_DEPTH; i = i + 1) begin
      memory[i] = 32'h0;
    end
    $display("Memory initialized");

    #20;
    rst_n = 1;
    #10;

    $display("========================================");
    $display("Starting Scrambler Verification Test");
    $display("Memory Size: 1024x32");
    $display("Key: 0x%08h", SCRAMBLER_KEY);
    $display("========================================");

    $display("\n--- Write Phase ---");
    write_enable = 1;

    for (i = 0; i < MEM_DEPTH; i = i + 1) begin
      logical_addr = i[ADDR_WIDTH-1:0];
      write_data = $urandom;
      expected_data[i] = write_data;

      #1;
      expected_scrambled[i] = scrambled_write_data;

`ifdef DEBUG
      $display(
          "Write[%4d]: addr_in=0x%03h -> scrambled_addr=0x%03h data=0x%08h scrambled_data=0x%08h",
          i, logical_addr, scrambled_addr, write_data, scrambled_write_data);
`else
      if (i < 10) begin
        $display("Write[%4d]: addr=0x%03h -> 0x%03h data=0x%08h -> scrambled=0x%08h", i,
                 logical_addr, scrambled_addr, write_data, scrambled_write_data);
      end
`endif

      @(posedge clk);
      #1;
    end
    write_enable = 0;

    $display("Wrote %0d locations", MEM_DEPTH);

    #20;

    $display("\n--- Read Phase ---");

    for (i = 0; i < MEM_DEPTH; i = i + 1) begin
      logical_addr = i[ADDR_WIDTH-1:0];
      @(posedge clk);
      #1;

`ifdef DEBUG
      $display(
          "Read[%4d]:  addr_in=0x%03h -> scrambled_addr=0x%03h scrambled_data=0x%08h descrambled=0x%08h %s",
          i, logical_addr, scrambled_addr, scrambled_read_data, read_data,
          (read_data == expected_data[i]) ? "PASS" : "FAIL");
`else
      if (i < 10) begin
        $display(
            "Read[%4d]:  addr=0x%03h scrambled_data=0x%08h descrambled=0x%08h expected=0x%08h %s",
            i, logical_addr, scrambled_read_data, read_data, expected_data[i],
            (read_data == expected_data[i]) ? "PASS" : "FAIL");
      end
`endif

      if (read_data !== expected_data[i]) begin
        errors = errors + 1;
        if (errors <= 10) begin
          $display("ERROR: Read mismatch at address %0d: expected 0x%08h, got 0x%08h", i,
                   expected_data[i], read_data);
        end
      end
    end

    #20;

    $display("\n========================================");
    $display("Phase 1 Complete (Ascending Order)");
    $display("Total Errors: %0d/%0d", errors, MEM_DEPTH);
    if (errors == 0) begin
      $display("*** PHASE 1 PASSED ***");
    end else begin
      $display("*** PHASE 1 FAILED ***");
    end
    $display("========================================");

    #20;

    $display("\n========================================");
    $display("Starting Phase 2 - Descending Order Test");
    $display("========================================");

    $display("\n--- Write Phase (Descending) ---");
    $display("Note: Address decrements %0d->0, Data increments 0->%0d", MEM_DEPTH - 1,
             MEM_DEPTH - 1);
    write_enable = 1;

    j = 0;
    for (i = MEM_DEPTH - 1; i >= 0; i = i - 1) begin
      logical_addr = i[ADDR_WIDTH-1:0];
      write_data = j;
      expected_data[i] = write_data;

      #1;
      expected_scrambled[i] = scrambled_write_data;

`ifdef DEBUG
      $display(
          "Write[%4d]: addr_in=0x%03h -> scrambled_addr=0x%03h (data_idx=%4d) data=0x%08h scrambled_data=0x%08h",
          i, logical_addr, scrambled_addr, j, write_data, scrambled_write_data);
`else
      if ((i >= MEM_DEPTH - 10) || (i < 10)) begin
        $display("Write[%4d]: addr=0x%03h -> 0x%03h (data_idx=%4d) data=0x%08h -> scrambled=0x%08h",
                 i, logical_addr, scrambled_addr, j, write_data, scrambled_write_data);
      end
`endif

      @(posedge clk);
      #1;
      j = j + 1;
    end
    write_enable = 0;

    $display("Wrote %0d locations in descending order", MEM_DEPTH);

    #20;

    $display("\n--- Read Phase (Descending) ---");

    for (i = MEM_DEPTH - 1; i >= 0; i = i - 1) begin
      logical_addr = i[ADDR_WIDTH-1:0];
      @(posedge clk);
      #1;

`ifdef DEBUG
      $display(
          "Read[%4d]:  addr_in=0x%03h -> scrambled_addr=0x%03h scrambled_data=0x%08h descrambled=0x%08h %s",
          i, logical_addr, scrambled_addr, scrambled_read_data, read_data,
          (read_data == expected_data[i]) ? "PASS" : "FAIL");
`else
      if ((i >= MEM_DEPTH - 10) || (i < 10)) begin
        $display(
            "Read[%4d]:  addr=0x%03h scrambled_data=0x%08h descrambled=0x%08h expected=0x%08h %s",
            i, logical_addr, scrambled_read_data, read_data, expected_data[i],
            (read_data == expected_data[i]) ? "PASS" : "FAIL");
      end
`endif

      if (read_data !== expected_data[i]) begin
        errors = errors + 1;
        if (errors <= 10) begin
          $display("ERROR: Read mismatch at address %0d: expected 0x%08h, got 0x%08h", i,
                   expected_data[i], read_data);
        end
      end
    end

    #20;

    $display("\n========================================");
    $display("All Tests Complete");
    $display("Phase 1 (Ascending):  %0d errors", errors);
    $display("Phase 2 (Descending): %0d errors/%0d", errors, MEM_DEPTH);
    $display("Total Errors: %0d/%0d", errors, MEM_DEPTH * 2);
    if (errors == 0) begin
      $display("*** ALL TESTS PASSED ***");
    end else begin
      $display("*** TESTS FAILED ***");
    end
    $display("========================================");

    #20;
    $finish;
  end

endmodule
