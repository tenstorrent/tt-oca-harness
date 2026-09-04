// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//-----------------------------------------------------------------------------
// Simple Scrambler Unit Test
//-----------------------------------------------------------------------------

`timescale 1ns / 1ps

module tb_scrambler_simple;

  localparam int unsigned ADDR_WIDTH = 9;
  localparam int unsigned DATA_WIDTH = 32;
  localparam logic [31:0] SCRAMBLER_KEY = 32'hDEADBEEF;

  reg [ADDR_WIDTH-1:0] addr;
  reg [DATA_WIDTH-1:0] write_data;
  wire [ADDR_WIDTH-1:0] scrambled_addr;
  wire [DATA_WIDTH-1:0] read_data;
  wire [DATA_WIDTH-1:0] scrambled_data;

  scrambler #(
    .ADDR_WIDTH(ADDR_WIDTH),
    .DATA_WIDTH(DATA_WIDTH)
  ) u_scrambler (
    .addr_i(addr),
    .scrambler_key_i(SCRAMBLER_KEY),
    .scrambled_addr_o(scrambled_addr),
    .write_data_i(write_data),
    .scrambled_write_data_o(scrambled_data),
    .scrambled_read_data_i(scrambled_data),
    .read_data_o(read_data)
  );

  initial begin
    $dumpfile("tb_scrambler_simple.vcd");
    $dumpvars(0, tb_scrambler_simple);

    $display("Simple Scrambler Round-Trip Test");
    $display("=================================");

    // Test 1: addr=0, data=0x12345678
    addr = 9'h000;
    write_data = 32'h12345678;
    #10;
    $display("Test 1: addr=0x%03h data=0x%08h", addr, write_data);
    $display("        scrambled=0x%08h descrambled=0x%08h %s", scrambled_data, read_data,
             (read_data == write_data) ? "PASS" : "FAIL");

    // Test 2: addr=1, data=0xDEADBEEF
    addr = 9'h001;
    write_data = 32'hDEADBEEF;
    #10;
    $display("Test 2: addr=0x%03h data=0x%08h", addr, write_data);
    $display("        scrambled=0x%08h descrambled=0x%08h %s", scrambled_data, read_data,
             (read_data == write_data) ? "PASS" : "FAIL");

    // Test 3: addr=0x1FF, data=0xA5A5A5A5
    addr = 9'h1FF;
    write_data = 32'hA5A5A5A5;
    #10;
    $display("Test 3: addr=0x%03h data=0x%08h", addr, write_data);
    $display("        scrambled=0x%08h descrambled=0x%08h %s", scrambled_data, read_data,
             (read_data == write_data) ? "PASS" : "FAIL");

    #10;
    $display("\nTest complete");
    $finish;
  end

endmodule
