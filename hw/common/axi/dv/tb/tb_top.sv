// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// axi_lite_to_ahb IP-level testbench top for the cocotb flow.
//
// Three converter instances elaborate side by side so one build covers the
// parameter sets:
//
//   u_dut_a  AHB_DATA_WIDTH = 64, AllowSubWordWrite = 0, AckZeroStrobeWrite = 1
//            (the SEP Adams Bridge control path)
//   u_dut_b  AHB_DATA_WIDTH = 32, AllowSubWordWrite = 1, AckZeroStrobeWrite = 0
//   u_dut_c  AHB_DATA_WIDTH = 64, AllowSubWordWrite = 1, AckZeroStrobeWrite = 0
//            (sub-word writes on either half of the 64-bit bus)
//
// Every connection is an ANSI port: the <x>_axil_* ports carry the AXI4-Lite
// slave side under the signal names cocotbext-axi resolves from a prefix, and
// the <x>_ahb_* ports carry the AHB-Lite master side for the cocotb slave
// model. The instances share the clock and reset, which are driven from
// cocotb.

`timescale 1ns / 1ps

`include "axi/typedef.svh"

module axi_lite_to_ahb_tb_top (
  input  logic        clk,
  input  logic        rst_n,

  // Instance A: AXI4-Lite slave port
  input  logic [31:0] a_axil_awaddr,
  input  logic [2:0]  a_axil_awprot,
  input  logic        a_axil_awvalid,
  output logic        a_axil_awready,
  input  logic [31:0] a_axil_wdata,
  input  logic [3:0]  a_axil_wstrb,
  input  logic        a_axil_wvalid,
  output logic        a_axil_wready,
  output logic [1:0]  a_axil_bresp,
  output logic        a_axil_bvalid,
  input  logic        a_axil_bready,
  input  logic [31:0] a_axil_araddr,
  input  logic [2:0]  a_axil_arprot,
  input  logic        a_axil_arvalid,
  output logic        a_axil_arready,
  output logic [31:0] a_axil_rdata,
  output logic [1:0]  a_axil_rresp,
  output logic        a_axil_rvalid,
  input  logic        a_axil_rready,

  // Instance A: AHB-Lite master port, 64-bit data
  output logic [31:0] a_ahb_haddr,
  output logic [2:0]  a_ahb_hburst,
  output logic        a_ahb_hmastlock,
  output logic [3:0]  a_ahb_hprot,
  output logic [2:0]  a_ahb_hsize,
  output logic [1:0]  a_ahb_htrans,
  output logic        a_ahb_hwrite,
  output logic [63:0] a_ahb_hwdata,
  input  logic [63:0] a_ahb_hrdata,
  input  logic        a_ahb_hready,
  input  logic        a_ahb_hresp,

  // Instance B: AXI4-Lite slave port
  input  logic [31:0] b_axil_awaddr,
  input  logic [2:0]  b_axil_awprot,
  input  logic        b_axil_awvalid,
  output logic        b_axil_awready,
  input  logic [31:0] b_axil_wdata,
  input  logic [3:0]  b_axil_wstrb,
  input  logic        b_axil_wvalid,
  output logic        b_axil_wready,
  output logic [1:0]  b_axil_bresp,
  output logic        b_axil_bvalid,
  input  logic        b_axil_bready,
  input  logic [31:0] b_axil_araddr,
  input  logic [2:0]  b_axil_arprot,
  input  logic        b_axil_arvalid,
  output logic        b_axil_arready,
  output logic [31:0] b_axil_rdata,
  output logic [1:0]  b_axil_rresp,
  output logic        b_axil_rvalid,
  input  logic        b_axil_rready,

  // Instance B: AHB-Lite master port, 32-bit data
  output logic [31:0] b_ahb_haddr,
  output logic [2:0]  b_ahb_hburst,
  output logic        b_ahb_hmastlock,
  output logic [3:0]  b_ahb_hprot,
  output logic [2:0]  b_ahb_hsize,
  output logic [1:0]  b_ahb_htrans,
  output logic        b_ahb_hwrite,
  output logic [31:0] b_ahb_hwdata,
  input  logic [31:0] b_ahb_hrdata,
  input  logic        b_ahb_hready,
  input  logic        b_ahb_hresp,

  // Instance C: AXI4-Lite slave port
  input  logic [31:0] c_axil_awaddr,
  input  logic [2:0]  c_axil_awprot,
  input  logic        c_axil_awvalid,
  output logic        c_axil_awready,
  input  logic [31:0] c_axil_wdata,
  input  logic [3:0]  c_axil_wstrb,
  input  logic        c_axil_wvalid,
  output logic        c_axil_wready,
  output logic [1:0]  c_axil_bresp,
  output logic        c_axil_bvalid,
  input  logic        c_axil_bready,
  input  logic [31:0] c_axil_araddr,
  input  logic [2:0]  c_axil_arprot,
  input  logic        c_axil_arvalid,
  output logic        c_axil_arready,
  output logic [31:0] c_axil_rdata,
  output logic [1:0]  c_axil_rresp,
  output logic        c_axil_rvalid,
  input  logic        c_axil_rready,

  // Instance C: AHB-Lite master port, 64-bit data
  output logic [31:0] c_ahb_haddr,
  output logic [2:0]  c_ahb_hburst,
  output logic        c_ahb_hmastlock,
  output logic [3:0]  c_ahb_hprot,
  output logic [2:0]  c_ahb_hsize,
  output logic [1:0]  c_ahb_htrans,
  output logic        c_ahb_hwrite,
  output logic [63:0] c_ahb_hwdata,
  input  logic [63:0] c_ahb_hrdata,
  input  logic        c_ahb_hready,
  input  logic        c_ahb_hresp
);

  typedef logic [31:0] axil_addr_t;
  typedef logic [31:0] axil_data_t;
  typedef logic [3:0] axil_strb_t;

  `AXI_LITE_TYPEDEF_ALL_CT(tb_axil, tb_axil_req_t, tb_axil_rsp_t, axil_addr_t, axil_data_t,
                           axil_strb_t)

  // ---------------------------------------------------------------------------
  // Instance A: ABR parameter set
  // ---------------------------------------------------------------------------
  tb_axil_req_t a_axil_req;
  tb_axil_rsp_t a_axil_rsp;

  assign a_axil_req.aw.addr = a_axil_awaddr;
  assign a_axil_req.aw.prot = a_axil_awprot;
  assign a_axil_req.aw_valid = a_axil_awvalid;
  assign a_axil_req.w.data = a_axil_wdata;
  assign a_axil_req.w.strb = a_axil_wstrb;
  assign a_axil_req.w_valid = a_axil_wvalid;
  assign a_axil_req.b_ready = a_axil_bready;
  assign a_axil_req.ar.addr = a_axil_araddr;
  assign a_axil_req.ar.prot = a_axil_arprot;
  assign a_axil_req.ar_valid = a_axil_arvalid;
  assign a_axil_req.r_ready = a_axil_rready;

  assign a_axil_awready = a_axil_rsp.aw_ready;
  assign a_axil_wready  = a_axil_rsp.w_ready;
  assign a_axil_bresp   = a_axil_rsp.b.resp;
  assign a_axil_bvalid  = a_axil_rsp.b_valid;
  assign a_axil_arready = a_axil_rsp.ar_ready;
  assign a_axil_rdata   = a_axil_rsp.r.data;
  assign a_axil_rresp   = a_axil_rsp.r.resp;
  assign a_axil_rvalid  = a_axil_rsp.r_valid;

  axi_lite_to_ahb #(
    .AXI_ADDR_WIDTH     (32),
    .AXI_DATA_WIDTH     (32),
    .AHB_DATA_WIDTH     (64),
    .axi_lite_req_t     (tb_axil_req_t),
    .axi_lite_rsp_t     (tb_axil_rsp_t),
    .AllowSubWordWrite  (1'b0),
    .AckZeroStrobeWrite (1'b1)
  ) u_dut_a (
    .clk_i           (clk),
    .rst_ni          (rst_n),

    .axi_lite_req_i  (a_axil_req),
    .axi_lite_rsp_o  (a_axil_rsp),

    .ahb_haddr_o     (a_ahb_haddr),
    .ahb_hburst_o    (a_ahb_hburst),
    .ahb_hmastlock_o (a_ahb_hmastlock),
    .ahb_hprot_o     (a_ahb_hprot),
    .ahb_hsize_o     (a_ahb_hsize),
    .ahb_htrans_o    (a_ahb_htrans),
    .ahb_hwrite_o    (a_ahb_hwrite),
    .ahb_hwdata_o    (a_ahb_hwdata),
    .ahb_hrdata_i    (a_ahb_hrdata),
    .ahb_hready_i    (a_ahb_hready),
    .ahb_hresp_i     (a_ahb_hresp)
  );

  // ---------------------------------------------------------------------------
  // Instance B: 32-bit AHB, sub-word writes admitted, zero-strobe writes refused
  // ---------------------------------------------------------------------------
  tb_axil_req_t b_axil_req;
  tb_axil_rsp_t b_axil_rsp;

  assign b_axil_req.aw.addr = b_axil_awaddr;
  assign b_axil_req.aw.prot = b_axil_awprot;
  assign b_axil_req.aw_valid = b_axil_awvalid;
  assign b_axil_req.w.data = b_axil_wdata;
  assign b_axil_req.w.strb = b_axil_wstrb;
  assign b_axil_req.w_valid = b_axil_wvalid;
  assign b_axil_req.b_ready = b_axil_bready;
  assign b_axil_req.ar.addr = b_axil_araddr;
  assign b_axil_req.ar.prot = b_axil_arprot;
  assign b_axil_req.ar_valid = b_axil_arvalid;
  assign b_axil_req.r_ready = b_axil_rready;

  assign b_axil_awready = b_axil_rsp.aw_ready;
  assign b_axil_wready  = b_axil_rsp.w_ready;
  assign b_axil_bresp   = b_axil_rsp.b.resp;
  assign b_axil_bvalid  = b_axil_rsp.b_valid;
  assign b_axil_arready = b_axil_rsp.ar_ready;
  assign b_axil_rdata   = b_axil_rsp.r.data;
  assign b_axil_rresp   = b_axil_rsp.r.resp;
  assign b_axil_rvalid  = b_axil_rsp.r_valid;

  axi_lite_to_ahb #(
    .AXI_ADDR_WIDTH     (32),
    .AXI_DATA_WIDTH     (32),
    .AHB_DATA_WIDTH     (32),
    .axi_lite_req_t     (tb_axil_req_t),
    .axi_lite_rsp_t     (tb_axil_rsp_t),
    .AllowSubWordWrite  (1'b1),
    .AckZeroStrobeWrite (1'b0)
  ) u_dut_b (
    .clk_i           (clk),
    .rst_ni          (rst_n),

    .axi_lite_req_i  (b_axil_req),
    .axi_lite_rsp_o  (b_axil_rsp),

    .ahb_haddr_o     (b_ahb_haddr),
    .ahb_hburst_o    (b_ahb_hburst),
    .ahb_hmastlock_o (b_ahb_hmastlock),
    .ahb_hprot_o     (b_ahb_hprot),
    .ahb_hsize_o     (b_ahb_hsize),
    .ahb_htrans_o    (b_ahb_htrans),
    .ahb_hwrite_o    (b_ahb_hwrite),
    .ahb_hwdata_o    (b_ahb_hwdata),
    .ahb_hrdata_i    (b_ahb_hrdata),
    .ahb_hready_i    (b_ahb_hready),
    .ahb_hresp_i     (b_ahb_hresp)
  );

  // ---------------------------------------------------------------------------
  // Instance C: 64-bit AHB, sub-word writes admitted, zero-strobe writes refused
  // ---------------------------------------------------------------------------
  tb_axil_req_t c_axil_req;
  tb_axil_rsp_t c_axil_rsp;

  assign c_axil_req.aw.addr = c_axil_awaddr;
  assign c_axil_req.aw.prot = c_axil_awprot;
  assign c_axil_req.aw_valid = c_axil_awvalid;
  assign c_axil_req.w.data = c_axil_wdata;
  assign c_axil_req.w.strb = c_axil_wstrb;
  assign c_axil_req.w_valid = c_axil_wvalid;
  assign c_axil_req.b_ready = c_axil_bready;
  assign c_axil_req.ar.addr = c_axil_araddr;
  assign c_axil_req.ar.prot = c_axil_arprot;
  assign c_axil_req.ar_valid = c_axil_arvalid;
  assign c_axil_req.r_ready = c_axil_rready;

  assign c_axil_awready = c_axil_rsp.aw_ready;
  assign c_axil_wready  = c_axil_rsp.w_ready;
  assign c_axil_bresp   = c_axil_rsp.b.resp;
  assign c_axil_bvalid  = c_axil_rsp.b_valid;
  assign c_axil_arready = c_axil_rsp.ar_ready;
  assign c_axil_rdata   = c_axil_rsp.r.data;
  assign c_axil_rresp   = c_axil_rsp.r.resp;
  assign c_axil_rvalid  = c_axil_rsp.r_valid;

  axi_lite_to_ahb #(
    .AXI_ADDR_WIDTH     (32),
    .AXI_DATA_WIDTH     (32),
    .AHB_DATA_WIDTH     (64),
    .axi_lite_req_t     (tb_axil_req_t),
    .axi_lite_rsp_t     (tb_axil_rsp_t),
    .AllowSubWordWrite  (1'b1),
    .AckZeroStrobeWrite (1'b0)
  ) u_dut_c (
    .clk_i           (clk),
    .rst_ni          (rst_n),

    .axi_lite_req_i  (c_axil_req),
    .axi_lite_rsp_o  (c_axil_rsp),

    .ahb_haddr_o     (c_ahb_haddr),
    .ahb_hburst_o    (c_ahb_hburst),
    .ahb_hmastlock_o (c_ahb_hmastlock),
    .ahb_hprot_o     (c_ahb_hprot),
    .ahb_hsize_o     (c_ahb_hsize),
    .ahb_htrans_o    (c_ahb_htrans),
    .ahb_hwrite_o    (c_ahb_hwrite),
    .ahb_hwdata_o    (c_ahb_hwdata),
    .ahb_hrdata_i    (c_ahb_hrdata),
    .ahb_hready_i    (c_ahb_hready),
    .ahb_hresp_i     (c_ahb_hresp)
  );

endmodule
