// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// System Timer OCTS IP-level testbench top for the cocotb flow.
//
// Two timer instances form the smallest synchronization system: a primary
// that generates the sync-load and count-credit pulses and a secondary that
// consumes them, each on its own clock so the bench can skew the two domains.
// Pin-level shape: every DUT connection is an ANSI port so cocotb drives the
// inputs and samples the outputs directly. Each instance's AXI4-Lite register
// port is exposed flattened (primary_axil_*, secondary_axil_*) for the shared
// AXI VIP's master; the adapters below repack the pins into the pulp-platform
// req/resp structs the DUT uses. The two synchronization wires between the
// instances, both counters, and the GPIO-enable and credit debug outputs are
// pin-exposed for observation. Clocks and reset are driven from cocotb.

`timescale 1ns / 1ps

module system_timer_octs_tb_top
  import system_timer_octs_pkg::*;
(
  input  wire        clk_primary,
  input  wire        clk_secondary,
  input  wire        rst_n,

  // Runtime mode select of each instance
  input  wire        primary_is_primary,
  input  wire        secondary_is_primary,

  // Primary AXI4-Lite register port (flattened, VIP master side)
  input  wire        primary_axil_awvalid,
  input  wire [31:0] primary_axil_awaddr,
  input  wire [2:0]  primary_axil_awprot,
  output wire        primary_axil_awready,

  input  wire        primary_axil_wvalid,
  input  wire [31:0] primary_axil_wdata,
  input  wire [3:0]  primary_axil_wstrb,
  output wire        primary_axil_wready,

  input  wire        primary_axil_bready,
  output wire        primary_axil_bvalid,
  output wire [1:0]  primary_axil_bresp,

  input  wire        primary_axil_arvalid,
  input  wire [31:0] primary_axil_araddr,
  input  wire [2:0]  primary_axil_arprot,
  output wire        primary_axil_arready,

  input  wire        primary_axil_rready,
  output wire        primary_axil_rvalid,
  output wire [31:0] primary_axil_rdata,
  output wire [1:0]  primary_axil_rresp,

  // Secondary AXI4-Lite register port (flattened, VIP master side)
  input  wire        secondary_axil_awvalid,
  input  wire [31:0] secondary_axil_awaddr,
  input  wire [2:0]  secondary_axil_awprot,
  output wire        secondary_axil_awready,

  input  wire        secondary_axil_wvalid,
  input  wire [31:0] secondary_axil_wdata,
  input  wire [3:0]  secondary_axil_wstrb,
  output wire        secondary_axil_wready,

  input  wire        secondary_axil_bready,
  output wire        secondary_axil_bvalid,
  output wire [1:0]  secondary_axil_bresp,

  input  wire        secondary_axil_arvalid,
  input  wire [31:0] secondary_axil_araddr,
  input  wire [2:0]  secondary_axil_arprot,
  output wire        secondary_axil_arready,

  input  wire        secondary_axil_rready,
  output wire        secondary_axil_rvalid,
  output wire [31:0] secondary_axil_rdata,
  output wire [1:0]  secondary_axil_rresp,

  // Synchronization wires from the primary to the secondary
  output wire        sync_load,
  output wire        cnt_credit,

  // Counters, GPIO enables and credit debug outputs
  output wire [63:0] primary_count,
  output wire [63:0] secondary_count,
  output wire        primary_gpio_enable,
  output wire        secondary_gpio_enable,
  output wire [8:0]  primary_cur_credits,
  output wire        primary_credits_left,
  output wire [8:0]  secondary_cur_credits,
  output wire        secondary_credits_left
);

  system_timer_octs_axil_req_t  primary_axil_req;
  system_timer_octs_axil_resp_t primary_axil_resp;

  assign primary_axil_req.aw_valid = primary_axil_awvalid;
  assign primary_axil_req.aw.addr  = primary_axil_awaddr;
  assign primary_axil_req.aw.prot  = primary_axil_awprot;
  assign primary_axil_awready      = primary_axil_resp.aw_ready;

  assign primary_axil_req.w_valid  = primary_axil_wvalid;
  assign primary_axil_req.w.data   = primary_axil_wdata;
  assign primary_axil_req.w.strb   = primary_axil_wstrb;
  assign primary_axil_wready       = primary_axil_resp.w_ready;

  assign primary_axil_req.b_ready  = primary_axil_bready;
  assign primary_axil_bvalid       = primary_axil_resp.b_valid;
  assign primary_axil_bresp        = primary_axil_resp.b.resp;

  assign primary_axil_req.ar_valid = primary_axil_arvalid;
  assign primary_axil_req.ar.addr  = primary_axil_araddr;
  assign primary_axil_req.ar.prot  = primary_axil_arprot;
  assign primary_axil_arready      = primary_axil_resp.ar_ready;

  assign primary_axil_req.r_ready  = primary_axil_rready;
  assign primary_axil_rvalid       = primary_axil_resp.r_valid;
  assign primary_axil_rdata        = primary_axil_resp.r.data;
  assign primary_axil_rresp        = primary_axil_resp.r.resp;

  system_timer_octs_axil_req_t  secondary_axil_req;
  system_timer_octs_axil_resp_t secondary_axil_resp;

  assign secondary_axil_req.aw_valid = secondary_axil_awvalid;
  assign secondary_axil_req.aw.addr  = secondary_axil_awaddr;
  assign secondary_axil_req.aw.prot  = secondary_axil_awprot;
  assign secondary_axil_awready      = secondary_axil_resp.aw_ready;

  assign secondary_axil_req.w_valid  = secondary_axil_wvalid;
  assign secondary_axil_req.w.data   = secondary_axil_wdata;
  assign secondary_axil_req.w.strb   = secondary_axil_wstrb;
  assign secondary_axil_wready       = secondary_axil_resp.w_ready;

  assign secondary_axil_req.b_ready  = secondary_axil_bready;
  assign secondary_axil_bvalid       = secondary_axil_resp.b_valid;
  assign secondary_axil_bresp        = secondary_axil_resp.b.resp;

  assign secondary_axil_req.ar_valid = secondary_axil_arvalid;
  assign secondary_axil_req.ar.addr  = secondary_axil_araddr;
  assign secondary_axil_req.ar.prot  = secondary_axil_arprot;
  assign secondary_axil_arready      = secondary_axil_resp.ar_ready;

  assign secondary_axil_req.r_ready  = secondary_axil_rready;
  assign secondary_axil_rvalid       = secondary_axil_resp.r_valid;
  assign secondary_axil_rdata        = secondary_axil_resp.r.data;
  assign secondary_axil_rresp        = secondary_axil_resp.r.resp;

  system_timer_octs u_primary (
    .clk_i                (clk_primary),
    .rst_ni               (rst_n),
    .is_primary_i         (primary_is_primary),

    .axil_req_i           (primary_axil_req),
    .axil_resp_o          (primary_axil_resp),

    .timer_sync_load_i    (1'b0),
    .timer_cnt_credit_i   (1'b0),
    .timer_sync_load_o    (sync_load),
    .timer_cnt_credit_o   (cnt_credit),

    .timer_count_o        (primary_count),

    .timer_gpio_enable_o  (primary_gpio_enable),

    .cur_credits_debug_o  (primary_cur_credits),
    .credits_left_debug_o (primary_credits_left)
  );

  system_timer_octs u_secondary (
    .clk_i                (clk_secondary),
    .rst_ni               (rst_n),
    .is_primary_i         (secondary_is_primary),

    .axil_req_i           (secondary_axil_req),
    .axil_resp_o          (secondary_axil_resp),

    .timer_sync_load_i    (sync_load),
    .timer_cnt_credit_i   (cnt_credit),
    .timer_sync_load_o    (),
    .timer_cnt_credit_o   (),

    .timer_count_o        (secondary_count),

    .timer_gpio_enable_o  (secondary_gpio_enable),

    .cur_credits_debug_o  (secondary_cur_credits),
    .credits_left_debug_o (secondary_credits_left)
  );

endmodule : system_timer_octs_tb_top
