// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Testbench for SRAM Scrambler 2048x32 — BYTE_WISE=1 mode
//
// Verifies byte-wise scrambling:
//   Phase 1: Full mask (4'hF) — all bytes scrambled, full round-trip check
//   Phase 2: Partial masks (4'h1,3,7,F) — verify masked bytes recover,
//            unmasked bytes pass through unchanged
//   Phase 3: Single-byte masks (4'h1,2,4,8) — each lane in isolation
//
// Copyright 2026 Tenstorrent Inc.
//
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_scrambler_2048x32_bw;

  localparam int unsigned ADDR_WIDTH = 11;
  localparam int unsigned DATA_WIDTH = 32;
  localparam int unsigned MEM_DEPTH = 2048;
  localparam logic [31:0] SCRAMBLER_KEY = 32'hDEADBEEF;

  reg clk;
  reg rst_n;

  reg  [ADDR_WIDTH-1:0] logical_addr;
  reg  [3:0]            byte_mask;
  reg  [DATA_WIDTH-1:0] write_data;
  wire [DATA_WIDTH-1:0] read_data;
  reg                   write_enable;

  wire [ADDR_WIDTH-1:0] scrambled_addr;
  wire [DATA_WIDTH-1:0] scrambled_write_data;
  reg  [DATA_WIDTH-1:0] scrambled_read_data;

  reg [DATA_WIDTH-1:0] memory [0:MEM_DEPTH-1];
  reg [DATA_WIDTH-1:0] expected_data [0:MEM_DEPTH-1];

  integer i, errors, total_errors;

  scrambler_2048x32 #(
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH),
    .BYTE_WISE(1)
  ) u_scrambler (
    .addr_i               (logical_addr),
    .byte_mask_i          (byte_mask),
    .scrambler_key_i      (SCRAMBLER_KEY),
    .scrambled_addr_o     (scrambled_addr),
    .write_data_i         (write_data),
    .scrambled_write_data_o(scrambled_write_data),
    .scrambled_read_data_i (scrambled_read_data),
    .read_data_o          (read_data)
  );

  always #5 clk = ~clk;

  initial begin
    $dumpfile("tb_scrambler_2048x32_bw.vcd");
    $dumpvars(0, tb_scrambler_2048x32_bw);
  end

  always @(posedge clk) begin
    if (write_enable) memory[scrambled_addr] <= scrambled_write_data;
  end

  always @(posedge clk) scrambled_read_data <= memory[scrambled_addr];

  // Task: write all addresses with current byte_mask and write_data pattern,
  // then read back and verify
  task automatic run_phase;
    input [3:0] mask;
    input [63:0] phase_name;  // unused, printed by caller
    begin
      // Write phase
      byte_mask    = mask;
      write_enable = 1;
      for (i = 0; i < MEM_DEPTH; i = i + 1) begin
        logical_addr     = i[ADDR_WIDTH-1:0];
        write_data       = $urandom;
        expected_data[i] = write_data;
        @(posedge clk);
        #1;
      end
      write_enable = 0;
      #20;

      // Read phase
      errors = 0;
      for (i = 0; i < MEM_DEPTH; i = i + 1) begin
        logical_addr = i[ADDR_WIDTH-1:0];
        @(posedge clk);
        #1;
        if (read_data !== expected_data[i]) begin
          errors = errors + 1;
          if (errors <= 5)
            $display(
                "  ERROR addr %0d: expected 0x%08h got 0x%08h", i, expected_data[i], read_data
            );
        end
      end
      total_errors = total_errors + errors;
    end
  endtask

  // Task: write with full mask, then read with partial mask and verify
  // only masked bytes changed; unmasked bytes retain previous memory value
  task automatic run_partial_mask_phase;
    input [3:0] mask;
    integer b;
    begin
      // Pre-fill memory with known pattern (full mask)
      byte_mask    = 4'hF;
      write_enable = 1;
      for (i = 0; i < MEM_DEPTH; i = i + 1) begin
        logical_addr = i[ADDR_WIDTH-1:0];
        write_data   = 32'hAAAAAAAA;
        @(posedge clk);
        #1;
      end
      write_enable = 0;
      #20;

      // Write new data with partial mask; save what we expect each byte to be
      byte_mask    = mask;
      write_enable = 1;
      for (i = 0; i < MEM_DEPTH; i = i + 1) begin
        logical_addr = i[ADDR_WIDTH-1:0];
        write_data   = 32'h55555555;
        // Bytes where mask=1 → new value 0x55, mask=0 → old value 0xAA
        expected_data[i] = 32'h0;
        for (b = 0; b < 4; b = b + 1) begin
          if (mask[b]) expected_data[i] = expected_data[i] | (32'h55 << (b * 8));
          else expected_data[i] = expected_data[i] | (32'hAA << (b * 8));
        end
        @(posedge clk);
        #1;
      end
      write_enable = 0;
      #20;

      // Read back and verify byte lanes
      errors = 0;
      for (i = 0; i < MEM_DEPTH; i = i + 1) begin
        logical_addr = i[ADDR_WIDTH-1:0];
        @(posedge clk);
        #1;
        if (read_data !== expected_data[i]) begin
          errors = errors + 1;
          if (errors <= 5)
            $display(
                "  ERROR mask=4'h%h addr %0d: expected 0x%08h got 0x%08h",
                mask,
                i,
                expected_data[i],
                read_data
            );
        end
      end
      total_errors = total_errors + errors;
    end
  endtask

  initial begin
    clk          = 0;
    rst_n        = 0;
    write_enable = 0;
    logical_addr = 0;
    byte_mask    = 4'hF;
    write_data   = 0;
    total_errors = 0;

    for (i = 0; i < MEM_DEPTH; i = i + 1) memory[i] = 32'h0;

    #20;
    rst_n = 1;
    #10;

    $display("========================================");
    $display("Scrambler 2048x32 BYTE_WISE=1 Tests");
    $display("Key: 0x%08h", SCRAMBLER_KEY);
    $display("========================================");

    // Phase 1: full mask, random data, ascending
    $display("\n--- Phase 1: Full mask (4'hF), ascending ---");
    run_phase(4'hF, "phase1");
    $display("Phase 1 errors: %0d/%0d", errors, MEM_DEPTH);

    // Phase 1b: descending
    $display("\n--- Phase 1b: Full mask (4'hF), descending ---");
    byte_mask    = 4'hF;
    write_enable = 1;
    for (i = MEM_DEPTH - 1; i >= 0; i = i - 1) begin
      logical_addr     = i[ADDR_WIDTH-1:0];
      write_data       = i;
      expected_data[i] = write_data;
      @(posedge clk);
      #1;
    end
    write_enable = 0;
    #20;
    errors = 0;
    for (i = MEM_DEPTH - 1; i >= 0; i = i - 1) begin
      logical_addr = i[ADDR_WIDTH-1:0];
      @(posedge clk);
      #1;
      if (read_data !== expected_data[i]) begin
        errors = errors + 1;
        if (errors <= 5)
          $display("  ERROR addr %0d: expected 0x%08h got 0x%08h", i, expected_data[i], read_data);
      end
    end
    total_errors = total_errors + errors;
    $display("Phase 1b errors: %0d/%0d", errors, MEM_DEPTH);

    // Phase 2: partial masks
    $display("\n--- Phase 2: Partial mask byte-lane isolation ---");
    $display("  mask=4'h1 (byte 0 only):");
    run_partial_mask_phase(4'h1);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("  mask=4'h3 (bytes 0-1):");
    run_partial_mask_phase(4'h3);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("  mask=4'h7 (bytes 0-2):");
    run_partial_mask_phase(4'h7);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    // Phase 3: single-byte masks
    $display("\n--- Phase 3: Single-byte masks ---");
    $display("  mask=4'h1:");
    run_partial_mask_phase(4'h1);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("  mask=4'h2:");
    run_partial_mask_phase(4'h2);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("  mask=4'h4:");
    run_partial_mask_phase(4'h4);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("  mask=4'h8:");
    run_partial_mask_phase(4'h8);
    $display("  errors: %0d/%0d", errors, MEM_DEPTH);

    $display("\n========================================");
    $display("All Tests Complete");
    $display("Total Errors: %0d", total_errors);
    if (total_errors == 0) $display("*** ALL TESTS PASSED ***");
    else $display("*** TESTS FAILED ***");
    $display("========================================");

    #100;
    $finish;
  end

  initial begin
    #5000000;
    $display("ERROR: Testbench timeout!");
    $finish;
  end

endmodule
