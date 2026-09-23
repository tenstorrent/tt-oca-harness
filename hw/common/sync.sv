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

// -------------------------------------------------------------
// This is a multi-width multi-stage configurable synchronizer
// - This has been modified from pulp to use prim cells
// -------------------------------------------------------------

module sync #(
    parameter int unsigned WIDTH = 1,
    parameter int unsigned STAGES = 3,
    parameter int unsigned ResetValue = 0,
    parameter bit RANDOM_DELAY_GRAY_CODE = 1'b0,
    parameter bit USE_ASYNC_RST_FF = 1'b1,  // 0: Synchronous reset FF, 1: Asynchronous reset FF
    parameter bit USE_NON_RST_FF = 1'b0     // 0: Non Reset FF, 1:Set/Clr FF based on ResetValue
) (
    input  logic clk_i,
    input  logic rst_ni,
    input  logic [WIDTH-1:0] serial_i,
    output logic [WIDTH-1:0] serial_o
);

   (* dont_touch = "true" *)
   (* async_reg = "true" *)

  logic  [WIDTH-1:0] din;

  generate

    //////////////////////////////////////////////////////////////////
    // Two stage synchronizer
    //////////////////////////////////////////////////////////////////

    // Two stage synchronizer: Non reset
    if ((STAGES == 2) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync2_non_rst
      prim_sync2 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync2 (
        .clk_i(clk_i),
        .d_i(serial_i),
        .q_o(serial_o)
      );
    end

    // Two stage synchronizer: Sync reset
    else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync2_sync_rst
      assign din = rst_ni ? serial_i : WIDTH'(ResetValue);
      prim_sync2 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync2 (
        .clk_i(clk_i),
        .d_i(din),
        .q_o(serial_o)
      );
    end

    // Two stage synchronizer: Async clear
    else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 1) && (ResetValue == 0)) begin:gen_tt_sync2_async_clr
      prim_sync2r #(
        .WIDTH(WIDTH)
      ) u_prim_sync2r (
        .clk_i(clk_i),
        .d_i(serial_i),
        .rst_ni(rst_ni),
        .q_o(serial_o)
      );
    end

    // Two stage synchronizer: Async set
    else if ((STAGES == 2) && (USE_ASYNC_RST_FF == 1) && (ResetValue != 0)) begin:gen_tt_sync2_async_set
      prim_sync2s #(
        .WIDTH(WIDTH)
      ) u_prim_sync2s (
        .clk_i(clk_i),
        .d_i(serial_i),
        .set_ni(rst_ni),
        .q_o(serial_o)
      );
    end

    //////////////////////////////////////////////////////////////////
    // Three stage synchronizer
    //////////////////////////////////////////////////////////////////

    // Three stage synchronizer: Non Reset
    else if ((STAGES == 3) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync3_non_rst
      prim_sync3 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync3 (
        .clk_i(clk_i),
        .d_i(serial_i),
        .q_o(serial_o)
      );
    end

    // Three stage synchronizer: Sync reset
    else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync3_sync_rst
      assign din = rst_ni ? serial_i : WIDTH'(ResetValue);
      prim_sync3 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync3 (
        .clk_i(clk_i),
        .d_i(din),
        .q_o(serial_o)
      );
    end

    // Three stage synchronizer: Async clr
    else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 1) && (ResetValue == 0)) begin:gen_tt_sync3_async_clr
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
    else if ((STAGES == 3) && (USE_ASYNC_RST_FF == 1) && (ResetValue != 0)) begin:gen_tt_sync3_async_set
      prim_sync3s #(
        .WIDTH(WIDTH)
      ) u_prim_sync3s (
        .clk_i(clk_i),
        .d_i(serial_i),
        .set_ni(rst_ni),
        .q_o(serial_o)
      );
    end

    //////////////////////////////////////////////////////////////////
    // Four stage synchronizer
    //////////////////////////////////////////////////////////////////

    // Four stage synchronizer: Non Reset
    else if ((STAGES == 4) && (USE_NON_RST_FF == 1)) begin:gen_tt_sync4_non_rst
      prim_sync4 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync4 (
        .clk_i(clk_i),
        .d_i(serial_i),
        .q_o(serial_o)
      );
    end

    // Four stage synchronizer: Sync reset
    else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 0)) begin:gen_tt_sync4_sync_rst
      assign din = rst_ni ? serial_i : WIDTH'(ResetValue);
      prim_sync4 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync4 (
        .clk_i(clk_i),
        .d_i(din),
        .q_o(serial_o)
      );
    end

    // Four stage synchronizer: Async clr
    else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 1) && (ResetValue == 0)) begin:gen_tt_sync4_async_clr
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
    else if ((STAGES == 4) && (USE_ASYNC_RST_FF == 1) && (ResetValue != 0)) begin:gen_tt_sync4_async_set
      prim_sync4s #(
        .WIDTH(WIDTH)
      ) u_prim_sync4s (
        .clk_i(clk_i),
        .d_i(serial_i),
        .set_ni(rst_ni),
        .q_o(serial_o)
      );
    end

    else begin: gen_default
      // Two stage synchronizer: Sync reset
      assign din = rst_ni ? serial_i : WIDTH'(ResetValue);
      prim_sync2 #(
        .WIDTH(WIDTH),
        .RANDOM_DELAY_GRAY_CODE(RANDOM_DELAY_GRAY_CODE)
      ) u_prim_sync2 (
        .clk_i(clk_i),
        .d_i(din),
        .q_o(serial_o)
      );
    end

  endgenerate

endmodule
