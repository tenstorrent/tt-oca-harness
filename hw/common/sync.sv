// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

// Copyright 2018 ETH Zurich and University of Bologna.
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 0.51 (the "License"); you may not use this file except in
// compliance with the License. You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.

// Antonio Pullini <pullinia@iis.ee.ethz.ch>

// Synchronize WIDTH bits into clk_i through a configurable 2-, 3-, or 4-flop chain.
//
// Derived from the PULP synchronizer and built from prim synchronizer cells. STAGES selects
// the chain length, and the reset parameters select the cell:
//
// - USE_NON_RST_FF set: a non-reset chain.
// - USE_ASYNC_RST_FF clear: a non-reset chain whose input is forced to RESET_VALUE while
//   rst_ni is low, which gives a synchronous reset that reaches serial_o after STAGES
//   clk_i cycles.
// - USE_ASYNC_RST_FF set and RESET_VALUE 0: an asynchronous-clear chain.
// - USE_ASYNC_RST_FF set and RESET_VALUE nonzero: an asynchronous-set chain. With STAGES 2
//   the chain resets to RESET_VALUE; with STAGES 3 or 4 every bit sets to 1.
//
// Any other STAGES value falls back to a 2-flop chain with the synchronous reset.

module sync #(
    parameter int unsigned WIDTH = 1,        // Number of independent bits synchronized.
    parameter int unsigned STAGES = 3,       // Chain length: 2, 3, or 4 flops.
    parameter int unsigned RESET_VALUE = 0,  // Reset value of serial_o; nonzero selects the
                                             // set cells under asynchronous reset.
    parameter bit USE_ASYNC_RST_FF = 1'b1,   // 0: synchronous reset, 1: asynchronous reset.
    parameter bit USE_NON_RST_FF = 1'b0      // 1: non-reset FF; overrides USE_ASYNC_RST_FF.
                                             // 0: reset FF per the other parameters.
) (
    input  logic clk_i,                     // Destination clock.
    input  logic rst_ni,                    // Active-low reset; see USE_ASYNC_RST_FF. Unused
                                            // when USE_NON_RST_FF is set and STAGES is 2 to 4.
    input  logic [WIDTH-1:0] serial_i,      // Asynchronous input bits.
    output logic [WIDTH-1:0] serial_o       // Synchronized bits in the clk_i domain.
);

   (* dont_touch = "true" *)
   (* async_reg = "true" *)

  logic  [WIDTH-1:0] din;

  //////////////////////////////////////////////////////////////////
  // Two stage synchronizer
  //////////////////////////////////////////////////////////////////

  // Two stage synchronizer: Non reset
  if ((STAGES == 2) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync2_non_rst
    prim_flop_2sync #(
      .Width(WIDTH)
    ) u_prim_sync2 (
      .clk_i(clk_i),
      .rst_ni(1'b1),
      .d_i(serial_i),
      .q_o(serial_o)
    );
  end

  // Two stage synchronizer: Sync reset
  else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync2_sync_rst
    assign din = rst_ni ? serial_i : WIDTH'(RESET_VALUE);
    prim_flop_2sync #(
      .Width(WIDTH)
    ) u_prim_sync2 (
      .clk_i(clk_i),
      .rst_ni(1'b1),
      .d_i(din),
      .q_o(serial_o)
    );
  end

  // Two stage synchronizer: Async clear
  else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE == 0)) begin:gen_tt_sync2_async_clr
    prim_flop_2sync #(
      .Width(WIDTH)
    ) u_prim_sync2r (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .d_i(serial_i),
      .q_o(serial_o)
    );
  end

  // Two stage synchronizer: Async set
  else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE != 0)) begin:gen_tt_sync2_async_set
    prim_flop_2sync #(
      .Width(WIDTH),
      .ResetValue(WIDTH'(RESET_VALUE))
    ) u_prim_sync2s (
      .clk_i(clk_i),
      .rst_ni(rst_ni),
      .d_i(serial_i),
      .q_o(serial_o)
    );
  end

  //////////////////////////////////////////////////////////////////
  // Three stage synchronizer
  //////////////////////////////////////////////////////////////////

  // Three stage synchronizer: Non Reset
  else if ((STAGES == 3) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync3_non_rst
    prim_sync3 #(
      .WIDTH(WIDTH)
    ) u_prim_sync3 (
      .clk_i(clk_i),
      .d_i(serial_i),
      .q_o(serial_o)
    );
  end

  // Three stage synchronizer: Sync reset
  else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync3_sync_rst
    assign din = rst_ni ? serial_i : WIDTH'(RESET_VALUE);
    prim_sync3 #(
      .WIDTH(WIDTH)
    ) u_prim_sync3 (
      .clk_i(clk_i),
      .d_i(din),
      .q_o(serial_o)
    );
  end

  // Three stage synchronizer: Async clr
  else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE == 0)) begin:gen_tt_sync3_async_clr
    prim_sync3r #(
      .WIDTH(WIDTH)
    ) u_prim_sync3r (
      .clk_i(clk_i),
      .d_i(serial_i),
      .rst_ni(rst_ni),
      .q_o(serial_o)
    );
  end

  // Three stage synchronizer: Async set
  else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE != 0)) begin:gen_tt_sync3_async_set
    for (genvar i = 0; i < WIDTH; i++) begin : gen_sync3s
      prim_flop_3sync_s u_sync3s (
        .clk_i (clk_i),
        .d_i   (serial_i[i]),
        .set_ni(rst_ni),
        .q_o   (serial_o[i])
      );
    end
  end

  //////////////////////////////////////////////////////////////////
  // Four stage synchronizer
  //////////////////////////////////////////////////////////////////

  // Four stage synchronizer: Non Reset
  else if ((STAGES == 4) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync4_non_rst
    prim_sync4 #(
      .WIDTH(WIDTH)
    ) u_prim_sync4 (
      .clk_i(clk_i),
      .d_i(serial_i),
      .q_o(serial_o)
    );
  end

  // Four stage synchronizer: Sync reset
  else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync4_sync_rst
    assign din = rst_ni ? serial_i : WIDTH'(RESET_VALUE);
    prim_sync4 #(
      .WIDTH(WIDTH)
    ) u_prim_sync4 (
      .clk_i(clk_i),
      .d_i(din),
      .q_o(serial_o)
    );
  end

  // Four stage synchronizer: Async clr
  else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE == 0)) begin:gen_tt_sync4_async_clr
    prim_sync4r #(
      .WIDTH(WIDTH)
    ) u_prim_sync4r (
      .clk_i(clk_i),
      .d_i(serial_i),
      .rst_ni(rst_ni),
      .q_o(serial_o)
    );
  end

  // Four stage synchronizer: Async set
  else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 1) && (RESET_VALUE != 0)) begin:gen_tt_sync4_async_set
    for (genvar i = 0; i < WIDTH; i++) begin : gen_sync4s
      prim_flop_4sync_s u_sync4s (
        .clk_i (clk_i),
        .d_i   (serial_i[i]),
        .set_ni(rst_ni),
        .q_o   (serial_o[i])
      );
    end
  end

  else begin: gen_default
    // Two stage synchronizer: Sync reset
    assign din = rst_ni ? serial_i : WIDTH'(RESET_VALUE);
    prim_flop_2sync #(
      .Width(WIDTH)
    ) u_prim_sync2 (
      .clk_i(clk_i),
      .rst_ni(1'b1),
      .d_i(din),
      .q_o(serial_o)
    );
  end

endmodule
