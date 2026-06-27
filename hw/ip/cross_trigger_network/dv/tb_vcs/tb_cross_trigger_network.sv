// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Cross Trigger Network Testbench
//
// Description:
// Top-level testbench for Cross Trigger Network verification
//------------------------------------------------------------------------------

`timescale 1ns/1ps

`include "axi/typedef.svh"
import cross_trigger_network_pkg::*;
import cross_trigger_port_pkg::*;
import cross_trigger_matrix_pkg::*;

module tb_cross_trigger_network;

    // Test configuration parameters (from cross_trigger_network_pkg)
    localparam int unsigned NUM_CTP          = DEFAULT_NUM_CTP;
    localparam int unsigned NUM_INT_CT       = DEFAULT_NUM_INT_CT;
    localparam int unsigned NUM_CLK_STOP_REQ = DEFAULT_NUM_CLK_STOP_REQ;
    localparam int unsigned NUM_CTM_PORTS    = NUM_CTP + NUM_INT_CT;

    // Internal CTP mode configuration:
    // Lower half (indices 0 to NUM_INT_CT/2-1) = Wire-OR mode (0)
    // Upper half (indices NUM_INT_CT/2 to NUM_INT_CT-1) = P2P mode (1)
    // This allows testing both modes in the same simulation
    localparam int unsigned NUM_INT_CT_WIRE_OR = NUM_INT_CT / 2;
    localparam int unsigned NUM_INT_CT_P2P     = NUM_INT_CT - NUM_INT_CT_WIRE_OR;
    localparam logic [NUM_INT_CT-1:0] INT_CT_MODE = {{NUM_INT_CT_P2P{1'b1}}, {NUM_INT_CT_WIRE_OR{1'b0}}};

    // Clock and reset
    logic clk;
    logic rst_n;

    // AXI-Lite interface signals (structs for DUT connection)
    ctn_axil_req_t  axil_req;
    ctn_axil_resp_t axil_resp;

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

    // Clock stop interface
    logic [NUM_CLK_STOP_REQ-1:0] clk_stop_req;
    logic                        jtag_clock_stop;
    logic stop_clks;
    logic cla_clock_stop;

    // Internal cross trigger interface
    logic [NUM_INT_CT-1:0] ctm_src_req;
    logic [NUM_INT_CT-1:0] ctm_src_ack;
    logic [NUM_INT_CT-1:0] ctm_dst_req;
    logic [NUM_INT_CT-1:0] ctm_dst_ack;

    // External CTP GPIO interface
    logic [NUM_CTP-1:0] ctp_req_out_dout;
    logic [NUM_CTP-1:0] ctp_req_out_dout_en;
    logic [NUM_CTP-1:0] ctp_req_out_din;
    logic [NUM_CTP-1:0] ctp_req_out_din_en;

    logic [NUM_CTP-1:0] ctp_req_in_dout;
    logic [NUM_CTP-1:0] ctp_req_in_dout_en;
    logic [NUM_CTP-1:0] ctp_req_in_din;
    logic [NUM_CTP-1:0] ctp_req_in_din_en;

    logic [NUM_CTP-1:0] ctp_ack_in_dout;
    logic [NUM_CTP-1:0] ctp_ack_in_dout_en;
    logic [NUM_CTP-1:0] ctp_ack_in_din;
    logic [NUM_CTP-1:0] ctp_ack_in_din_en;

    logic [NUM_CTP-1:0] ctp_ack_out_dout;
    logic [NUM_CTP-1:0] ctp_ack_out_dout_en;
    logic [NUM_CTP-1:0] ctp_ack_out_din;
    logic [NUM_CTP-1:0] ctp_ack_out_din_en;

    // DUT instantiation
    cross_trigger_network #(
        .INT_CT_MODE      (INT_CT_MODE),  // Mixed modes: lower=Wire-OR, upper=P2P
        .axil_req_t       (ctn_axil_req_t),
        .axil_resp_t      (ctn_axil_resp_t)
    ) u_dut (
        .clk_i               (clk),
        .rst_ni              (rst_n),

        // AXI-Lite interface
        .axil_req_i          (axil_req),
        .axil_resp_o         (axil_resp),

        // Clock stop interface
        .clk_stop_req_i      (clk_stop_req),
        .jtag_clock_stop_i   (jtag_clock_stop),
        .stop_clks_o         (stop_clks),
        .cla_clock_stop_o    (cla_clock_stop),

        // Internal cross trigger interface
        .ctm_src_req_o       (ctm_src_req),
        .ctm_src_ack_i       (ctm_src_ack),
        .ctm_dst_req_i       (ctm_dst_req),
        .ctm_dst_ack_o       (ctm_dst_ack),

        // External CTP GPIO interface
        .ctp_req_out_dout_o    (ctp_req_out_dout),
        .ctp_req_out_dout_en_o (ctp_req_out_dout_en),
        .ctp_req_out_din_i     (ctp_req_out_din),
        .ctp_req_out_din_en_o  (ctp_req_out_din_en),

        .ctp_req_in_dout_o     (ctp_req_in_dout),
        .ctp_req_in_dout_en_o  (ctp_req_in_dout_en),
        .ctp_req_in_din_i      (ctp_req_in_din),
        .ctp_req_in_din_en_o   (ctp_req_in_din_en),

        .ctp_ack_in_dout_o     (ctp_ack_in_dout),
        .ctp_ack_in_dout_en_o  (ctp_ack_in_dout_en),
        .ctp_ack_in_din_i      (ctp_ack_in_din),
        .ctp_ack_in_din_en_o   (ctp_ack_in_din_en),

        .ctp_ack_out_dout_o    (ctp_ack_out_dout),
        .ctp_ack_out_dout_en_o (ctp_ack_out_dout_en),
        .ctp_ack_out_din_i     (ctp_ack_out_din),
        .ctp_ack_out_din_en_o  (ctp_ack_out_din_en)
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
        // AXI-Lite
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

        // Clock stop
        clk_stop_req = 0;
        jtag_clock_stop = 0;

        // Internal cross triggers
        ctm_src_ack = 0;
        ctm_dst_req = 0;

        // External CTP GPIO inputs
        ctp_req_out_din = 0;
        ctp_req_in_din = 0;
        ctp_ack_in_din = 0;
        ctp_ack_out_din = 0;
    end

endmodule : tb_cross_trigger_network
