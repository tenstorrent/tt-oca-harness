// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// AXI4-Lite SystemVerilog interface with master and slave modports, adapted from
// the PeakRDL regblock AXI4-Lite CPUIF (https://peakrdl-regblock.readthedocs.io/en/latest/cpuif/axi4lite.html).

interface axi4lite_intf #(
  parameter int unsigned DATA_WIDTH = 32,
  parameter int unsigned ADDR_WIDTH = 32
);
  logic AWREADY;
  logic AWVALID;
  logic [ADDR_WIDTH-1:0] AWADDR;
  logic [2:0] AWPROT;

  logic WREADY;
  logic WVALID;
  logic [DATA_WIDTH-1:0] WDATA;
  logic [DATA_WIDTH/8-1:0] WSTRB;

  logic BREADY;
  logic BVALID;
  logic [1:0] BRESP;

  logic ARREADY;
  logic ARVALID;
  logic [ADDR_WIDTH-1:0] ARADDR;
  logic [2:0] ARPROT;

  logic RREADY;
  logic RVALID;
  logic [DATA_WIDTH-1:0] RDATA;
  logic [1:0] RRESP;

  modport master(
      input AWREADY,
      output AWVALID,
      output AWADDR,
      output AWPROT,

      input WREADY,
      output WVALID,
      output WDATA,
      output WSTRB,

      output BREADY,
      input BVALID,
      input BRESP,

      input ARREADY,
      output ARVALID,
      output ARADDR,
      output ARPROT,

      output RREADY,
      input RVALID,
      input RDATA,
      input RRESP
  );

  modport slave(
      output AWREADY,
      input AWVALID,
      input AWADDR,
      input AWPROT,

      output WREADY,
      input WVALID,
      input WDATA,
      input WSTRB,

      input BREADY,
      output BVALID,
      output BRESP,

      output ARREADY,
      input ARVALID,
      input ARADDR,
      input ARPROT,

      input RREADY,
      output RVALID,
      output RDATA,
      output RRESP
  );
endinterface
