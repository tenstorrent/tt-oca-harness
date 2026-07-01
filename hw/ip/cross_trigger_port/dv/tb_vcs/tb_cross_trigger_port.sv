// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

//------------------------------------------------------------------------------
// Cross Trigger Port Testbench
//
// Description:
// Top-level testbench for Cross Trigger Port IP verification
//------------------------------------------------------------------------------

`timescale 1ns/1ps

`include "axi/typedef.svh"
import cross_trigger_port_pkg::*;

module tb_cross_trigger_port;

    // Clock and reset
    logic clk;
    logic rst_n;

    // AXI-Lite interface signals (structs for DUT connection)
    ctp_axil_req_t  axil_req;
    ctp_axil_resp_t axil_resp;

    // Flattened AXI-Lite signals for cocotb access
    // Write address channel
    logic axil_awvalid;
    logic [31:0] axil_awaddr;
    logic [2:0] axil_awprot;
    logic axil_awready;

    // Write data channel
    logic axil_wvalid;
    logic [31:0] axil_wdata;
    logic [3:0] axil_wstrb;
    logic axil_wready;

    // Write response channel
    logic axil_bready;
    logic axil_bvalid;
    logic [1:0] axil_bresp;

    // Read address channel
    logic axil_arvalid;
    logic [31:0] axil_araddr;
    logic [2:0] axil_arprot;
    logic axil_arready;

    // Read data channel
    logic axil_rready;
    logic axil_rvalid;
    logic [31:0] axil_rdata;
    logic [1:0] axil_rresp;

    // Connect structs to flattened signals
    assign axil_req.aw_valid = axil_awvalid;
    assign axil_req.aw.addr = axil_awaddr;
    assign axil_req.aw.prot = axil_awprot;
    assign axil_awready = axil_resp.aw_ready;

    assign axil_req.w_valid = axil_wvalid;
    assign axil_req.w.data = axil_wdata;
    assign axil_req.w.strb = axil_wstrb;
    assign axil_wready = axil_resp.w_ready;

    assign axil_req.b_ready = axil_bready;
    assign axil_bvalid = axil_resp.b_valid;
    assign axil_bresp = axil_resp.b.resp;

    assign axil_req.ar_valid = axil_arvalid;
    assign axil_req.ar.addr = axil_araddr;
    assign axil_req.ar.prot = axil_arprot;
    assign axil_arready = axil_resp.ar_ready;

    assign axil_req.r_ready = axil_rready;
    assign axil_rvalid = axil_resp.r_valid;
    assign axil_rdata = axil_resp.r.data;
    assign axil_rresp = axil_resp.r.resp;

    // Core-side signals
    logic ct_src;
    logic ct_dst;
    logic busy;

    // GPIO pad interface - CT_Req_out
    logic ct_req_out_dout_en;
    logic ct_req_out_din_en;
    logic ct_req_out_dout;
    logic ct_req_out_din;

    // GPIO pad interface - CT_Req_in
    logic ct_req_in_din_en;
    logic ct_req_in_din;

    // GPIO pad interface - CT_Ack_in
    logic ct_ack_in_din_en;
    logic ct_ack_in_din;

    // GPIO pad interface - CT_Ack_out
    logic ct_ack_out_dout_en;
    logic ct_ack_out_dout;

    // DUT instantiation
    cross_trigger_port u_dut (
        .clk_i                  (clk),
        .rst_ni                 (rst_n),

        // AXI-Lite interface
        .axil_req_i             (axil_req),
        .axil_resp_o            (axil_resp),

        // Core-side interface
        .ct_src_i               (ct_src),
        .ct_dst_o               (ct_dst),
        .busy_o                 (busy),

        // GPIO pad interface
        .ct_req_out_dout_en_o   (ct_req_out_dout_en),
        .ct_req_out_din_en_o    (ct_req_out_din_en),
        .ct_req_out_dout_o      (ct_req_out_dout),
        .ct_req_out_din_i       (ct_req_out_din),

        .ct_req_in_din_en_o     (ct_req_in_din_en),
        .ct_req_in_din_i        (ct_req_in_din),

        .ct_ack_in_din_en_o     (ct_ack_in_din_en),
        .ct_ack_in_din_i        (ct_ack_in_din),

        .ct_ack_out_dout_en_o   (ct_ack_out_dout_en),
        .ct_ack_out_dout_o      (ct_ack_out_dout)
    );

    // Clock generation
    initial begin
        clk = 0;
        forever #5 clk = ~clk;  // 100 MHz
    end

    // Reset generation
    initial begin
        rst_n = 0;
        #100;
        rst_n = 1;
    end

    // Initialize signals
    initial begin
        axil_awvalid = 0;
        axil_awaddr = 0;
        axil_awprot = 0;
        axil_wvalid = 0;
        axil_wdata = 0;
        axil_wstrb = 0;
        axil_bready = 0;
        axil_arvalid = 0;
        axil_araddr = 0;
        axil_arprot = 0;
        axil_rready = 0;
        ct_src = 0;
        ct_req_out_din = 0;
        ct_req_in_din = 0;
        ct_ack_in_din = 0;
    end

    // Test stimulus (to be driven by Python/cocotb)
    // This is a placeholder - actual tests are in Python files

endmodule : tb_cross_trigger_port
