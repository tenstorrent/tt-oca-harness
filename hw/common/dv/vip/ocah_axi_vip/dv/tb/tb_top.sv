// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive AXI4 wire harness for the shared AXI VIP selftests. No DUT RTL:
// cocotb attaches VIP components to these nets from both sides.
//
//   s_axi_* — full-stack bundle: OcahAxiMasterAgent (drives AW/W/AR plus
//             R/B ready) against OcahAxiSlaveAgent (drives ready plus B/R).
//   t_axi_* — wire-level bundle: the test drives the request channels
//             directly against OcahAxiSlaveAgent so armed response-ID
//             corruption is observable without a backend master in the
//             loop (the cocotbext master fails by design on a response
//             ID it never issued).
//
// All nets are driven from cocotb (--public-flat-rw); nothing here has
// drivers, so the lint waivers below cover the whole module on purpose.

`timescale 1ns / 1ps

module ocah_axi_vip_tb_top;

    /* verilator lint_off UNDRIVEN */
    /* verilator lint_off UNUSEDSIGNAL */

    logic clk;
    logic rst_n;

    // ------------------------------------------------------------------
    // s_axi: full-stack bundle (VIP master <-> VIP fault slave)
    // ------------------------------------------------------------------
    logic [7:0]  s_axi_awid;
    logic [31:0] s_axi_awaddr;
    logic [7:0]  s_axi_awlen;
    logic [2:0]  s_axi_awsize;
    logic [1:0]  s_axi_awburst;
    logic        s_axi_awlock;
    logic [3:0]  s_axi_awcache;
    logic [2:0]  s_axi_awprot;
    logic [3:0]  s_axi_awqos;
    logic [3:0]  s_axi_awregion;
    logic        s_axi_awvalid;
    logic        s_axi_awready;

    logic [31:0] s_axi_wdata;
    logic [3:0]  s_axi_wstrb;
    logic        s_axi_wlast;
    logic        s_axi_wvalid;
    logic        s_axi_wready;

    logic [7:0]  s_axi_bid;
    logic [1:0]  s_axi_bresp;
    logic        s_axi_bvalid;
    logic        s_axi_bready;

    logic [7:0]  s_axi_arid;
    logic [31:0] s_axi_araddr;
    logic [7:0]  s_axi_arlen;
    logic [2:0]  s_axi_arsize;
    logic [1:0]  s_axi_arburst;
    logic        s_axi_arlock;
    logic [3:0]  s_axi_arcache;
    logic [2:0]  s_axi_arprot;
    logic [3:0]  s_axi_arqos;
    logic [3:0]  s_axi_arregion;
    logic        s_axi_arvalid;
    logic        s_axi_arready;

    logic [7:0]  s_axi_rid;
    logic [31:0] s_axi_rdata;
    logic [1:0]  s_axi_rresp;
    logic        s_axi_rlast;
    logic        s_axi_rvalid;
    logic        s_axi_rready;

    // Optional user sidebands (the master backend rejects its defaulted user
    // arguments when these are absent).
    logic        s_axi_awuser;
    logic        s_axi_wuser;
    logic        s_axi_buser;
    logic        s_axi_aruser;
    logic        s_axi_ruser;

    // ------------------------------------------------------------------
    // t_axi: wire-level bundle (test-driven requests <-> VIP fault slave)
    // ------------------------------------------------------------------
    logic [7:0]  t_axi_awid;
    logic [31:0] t_axi_awaddr;
    logic [7:0]  t_axi_awlen;
    logic [2:0]  t_axi_awsize;
    logic [1:0]  t_axi_awburst;
    logic        t_axi_awlock;
    logic [3:0]  t_axi_awcache;
    logic [2:0]  t_axi_awprot;
    logic [3:0]  t_axi_awqos;
    logic [3:0]  t_axi_awregion;
    logic        t_axi_awvalid;
    logic        t_axi_awready;

    logic [31:0] t_axi_wdata;
    logic [3:0]  t_axi_wstrb;
    logic        t_axi_wlast;
    logic        t_axi_wvalid;
    logic        t_axi_wready;

    logic [7:0]  t_axi_bid;
    logic [1:0]  t_axi_bresp;
    logic        t_axi_bvalid;
    logic        t_axi_bready;

    logic [7:0]  t_axi_arid;
    logic [31:0] t_axi_araddr;
    logic [7:0]  t_axi_arlen;
    logic [2:0]  t_axi_arsize;
    logic [1:0]  t_axi_arburst;
    logic        t_axi_arlock;
    logic [3:0]  t_axi_arcache;
    logic [2:0]  t_axi_arprot;
    logic [3:0]  t_axi_arqos;
    logic [3:0]  t_axi_arregion;
    logic        t_axi_arvalid;
    logic        t_axi_arready;

    logic [7:0]  t_axi_rid;
    logic [31:0] t_axi_rdata;
    logic [1:0]  t_axi_rresp;
    logic        t_axi_rlast;
    logic        t_axi_rvalid;
    logic        t_axi_rready;

    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_on UNDRIVEN */

endmodule
