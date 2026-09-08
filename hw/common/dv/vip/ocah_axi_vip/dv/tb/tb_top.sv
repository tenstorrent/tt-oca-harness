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
//   l_axi_* — AXI4-Lite bundle: OcahAxiLiteMasterAgent against
//             OcahAxiLiteSlaveAgent, for the lite protocol-control
//             selftests (AW/W launch skew, deferred BREADY/RREADY,
//             partial strobes) with the handshakes observable at the
//             nets.
//
// All nets are driven from cocotb (--public-flat-rw); nothing here has
// drivers, so the lint waivers below cover the whole module.

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

  // ------------------------------------------------------------------
  // l_axi: AXI4-Lite bundle (VIP lite master <-> VIP lite RAM slave)
  // ------------------------------------------------------------------
  logic [31:0] l_axi_awaddr;
  logic [2:0]  l_axi_awprot;
  logic        l_axi_awvalid;
  logic        l_axi_awready;

  logic [31:0] l_axi_wdata;
  logic [3:0]  l_axi_wstrb;
  logic        l_axi_wvalid;
  logic        l_axi_wready;

  logic [1:0]  l_axi_bresp;
  logic        l_axi_bvalid;
  logic        l_axi_bready;

  logic [31:0] l_axi_araddr;
  logic [2:0]  l_axi_arprot;
  logic        l_axi_arvalid;
  logic        l_axi_arready;

  logic [31:0] l_axi_rdata;
  logic [1:0]  l_axi_rresp;
  logic        l_axi_rvalid;
  logic        l_axi_rready;

  /* verilator lint_on UNUSEDSIGNAL */
  /* verilator lint_on UNDRIVEN */

`ifdef UVM
  // ------------------------------------------------------------------
  // SV-UVM harness (`--dut ocah_axi_vip --framework uvm`): clock/reset,
  // the one ocah_axi_if the VIP master, fault slave, and passive monitor
  // all attach to, config_db publication, and run_test(). Compiled only
  // when the native-uvm flow defines UVM; the cocotb flow sees only the
  // passive nets above.
  // ------------------------------------------------------------------
  import uvm_pkg::*;

  // 100 MHz bus clock; reset released after 10 cycles.
  initial clk = 1'b0;
  always #5ns clk = ~clk;

  initial begin
    rst_n = 1'b0;
    repeat (10) @(posedge clk);
    rst_n = 1'b1;
  end

  // One interface instance carries the whole selftest bus: the master
  // driver procedurally drives the initiator-side signals, the slave
  // driver the responder-side signals, and the passive monitor samples
  // both through mon_cb (no DUT in the loop; the s_axi/t_axi flat nets
  // above belong to the cocotb shape and stay idle here).
  ocah_axi_if u_axi_if (
    .aclk(clk),
    .aresetn(rst_n)
  );

  `include "ocah_axi_vip_tests.sv"

  initial begin
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "axi_vif", u_axi_if);
    run_test();
  end
`endif

endmodule
