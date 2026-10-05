// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Flat AXI4 / AXI4-Lite monitor interface for the ocah_axi_vip SV layer.
//
// One interface serves both protocols: AXI4-Lite is a strict signal subset,
// and a single non-parameterized `virtual ocah_axi_if` type keeps the UVM
// class layer simple. UVM instantiations use the DEFAULT (maximum) parameter
// widths; the actual bus geometry (addr/data/id widths, protocol selection)
// lives in ocah_axi_config, which masks sampled values down to the real widths.
//
// AXI4-Lite integrations tie the AXI4-only fields at the TB adapter:
//   awlen='0, awsize=$clog2(data_bytes), awburst=2'b01 (INCR), awid='0,
//   wlast=1'b1, rlast=1'b1, rid='0, lock/cache/qos/region/user='0.
// The monitor never samples AXI4-only signals when cfg selects AXI4-Lite.
//
// This is a PASSIVE observation surface: every signal is expected to be
// driven by TB `assign`s from the DUT-facing nets (see the DTP tb_top
// integration). The VIP's UVM monitor samples through mon_cb only.

interface ocah_axi_if #(
  parameter int unsigned ADDR_WIDTH = 64,
  parameter int unsigned DATA_WIDTH = 64,
  parameter int unsigned ID_WIDTH   = 16,
  parameter int unsigned USER_WIDTH = 16
) (
  input wire logic aclk,
  input wire logic aresetn
);

  localparam int unsigned StrbWidth = DATA_WIDTH / 8;

  // Write address channel.
  logic [ID_WIDTH-1:0]   awid;
  logic [ADDR_WIDTH-1:0] awaddr;
  logic [7:0]            awlen;
  logic [2:0]            awsize;
  logic [1:0]            awburst;
  logic                  awlock;
  logic [3:0]            awcache;
  logic [2:0]            awprot;
  logic [3:0]            awqos;
  logic [3:0]            awregion;
  logic [USER_WIDTH-1:0] awuser;
  logic                  awvalid;
  logic                  awready;

  // Write data channel.
  logic [DATA_WIDTH-1:0] wdata;
  logic [StrbWidth-1:0]  wstrb;
  logic                  wlast;
  logic [USER_WIDTH-1:0] wuser;
  logic                  wvalid;
  logic                  wready;

  // Write response channel.
  logic [ID_WIDTH-1:0]   bid;
  logic [1:0]            bresp;
  logic [USER_WIDTH-1:0] buser;
  logic                  bvalid;
  logic                  bready;

  // Read address channel.
  logic [ID_WIDTH-1:0]   arid;
  logic [ADDR_WIDTH-1:0] araddr;
  logic [7:0]            arlen;
  logic [2:0]            arsize;
  logic [1:0]            arburst;
  logic                  arlock;
  logic [3:0]            arcache;
  logic [2:0]            arprot;
  logic [3:0]            arqos;
  logic [3:0]            arregion;
  logic [USER_WIDTH-1:0] aruser;
  logic                  arvalid;
  logic                  arready;

  // Read data channel.
  logic [ID_WIDTH-1:0]   rid;
  logic [DATA_WIDTH-1:0] rdata;
  logic [1:0]            rresp;
  logic                  rlast;
  logic [USER_WIDTH-1:0] ruser;
  logic                  rvalid;
  logic                  rready;

  // Race-free passive sampling contract for the UVM monitor.
  clocking mon_cb @(posedge aclk);
    default input #1step;
    input awid, awaddr, awlen, awsize, awburst, awlock, awcache, awprot,
              awqos, awregion, awuser, awvalid, awready;
    input wdata, wstrb, wlast, wuser, wvalid, wready;
    input bid, bresp, buser, bvalid, bready;
    input arid, araddr, arlen, arsize, arburst, arlock, arcache, arprot,
              arqos, arregion, aruser, arvalid, arready;
    input rid, rdata, rresp, rlast, ruser, rvalid, rready;
  endclocking

  modport mon(clocking mon_cb, input aclk, aresetn);

`ifdef OCAH_AXI_VENDOR_IF
  // Commercial-VIP nesting hook (mirrors ocah_jtag_if). An adopter overlay
  // (run_dv --overlay) supplies `ocah_axi_vendor_if.svh` on an overlay
  // incdir together with the OCAH_AXI_VENDOR_IF define; the OSS tree ships
  // no copy of that file. It nests the vendor VIP's own SV interface HERE,
  // wired from this interface's boundary signals, so DUT tb_tops never
  // instantiate vendor collateral directly.
  `include "ocah_axi_vendor_if.svh"
`endif

endinterface : ocah_axi_if
