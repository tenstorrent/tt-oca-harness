// *****************************************************************************
// SPDX-License-Identifier: Apache-2.0
// *****************************************************************************
//  Copyright (c) 2026 BOS Semiconductors
//
//  Licensed under the Apache License, Version 2.0 (the "License");
//  you may not use this file except in compliance with the License.
//  You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
//  Unless required by applicable law or agreed to in writing, software
//  distributed under the License is distributed on an "AS IS" BASIS,
//  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
//  See the License for the specific language governing permissions and
//  limitations under the License.
// *****************************************************************************
//
//  Module     : AOU_AW_W_ALIGNER
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module AOU_AW_W_ALIGNER #(
    parameter   AXI_SLV_NUM  = 2,
    localparam  RP_SEL_WD = ( AXI_SLV_NUM == 1) ? 1: $clog2(AXI_SLV_NUM),  
    parameter   AXI_DATA_WD   = 512,
    parameter   AXI_ADDR_WD   = 64,
    parameter   AXI_ID_WD     = 2,
    parameter   AXI_QOS_WD    = 4,
    localparam  AXI_STRB_WD   = AXI_DATA_WD / 8,
    parameter   AXI_LEN_WD    = 8
)
(
    input                                               I_CLK,
    input                                               I_RESETN,

    input       [1:0]                                   I_S_AW_RP_SEL,
    input       [AXI_ID_WD-1: 0]                        I_S_AWID,
    input       [AXI_ADDR_WD-1: 0]                      I_S_AWADDR,
    input       [AXI_LEN_WD-1: 0]                       I_S_AWLEN,
    input       [2: 0]                                  I_S_AWSIZE,
    input                                               I_S_AWLOCK,
    input       [3: 0]                                  I_S_AWCACHE,
    input       [2: 0]                                  I_S_AWPROT,
    input       [AXI_QOS_WD-1: 0]                       I_S_AWQOS,
    input                                               I_S_AWVALID,
    output wire                                         O_S_AWREADY,

    input       [AXI_SLV_NUM-1:0][AXI_DATA_WD-1: 0]     I_S_WDATA,
    input       [AXI_SLV_NUM-1:0][AXI_STRB_WD-1: 0]     I_S_WSTRB,
    input       [AXI_SLV_NUM-1:0]                       I_S_WSTRB_FULL,
    input       [AXI_SLV_NUM-1:0]                       I_S_WLAST,
    input       [AXI_SLV_NUM-1:0]                       I_S_WVALID,
    output      [AXI_SLV_NUM-1:0]                       O_S_WREADY,

    output      [1:0]                                   O_M_AW_RP_SEL,
    output wire [AXI_ID_WD-1:0]                         O_M_AWID,
    output wire [AXI_ADDR_WD-1: 0]                      O_M_AWADDR,
    output wire [AXI_LEN_WD-1: 0]                       O_M_AWLEN,
    output wire [2: 0]                                  O_M_AWSIZE,
    output wire                                         O_M_AWLOCK,
    output wire [3: 0]                                  O_M_AWCACHE,
    output wire [2: 0]                                  O_M_AWPROT,
    output wire [AXI_QOS_WD-1: 0]                       O_M_AWQOS,
    output wire                                         O_M_AWVALID,
    input                                               I_M_AWREADY,      

    output wire [AXI_DATA_WD-1: 0]                      O_M_WDATA,
    output wire [AXI_STRB_WD-1: 0]                      O_M_WSTRB,
    output wire                                         O_M_WSTRB_FULL,
    output wire                                         O_M_WLAST,
    output wire                                         O_M_WVALID,
    input                                               I_M_WREADY

);

reg  [RP_SEL_WD-1: 0]                           r_aw_arb_grt    ;
wire [RP_SEL_WD-1: 0]                           w_aw_arb_grt_mux;

reg                                             r_s_wbusy_tt    ; 

wire                                            w_no_awvalid    ;

//--------------------------------------------------------------
assign w_aw_arb_grt_mux = r_s_wbusy_tt ? r_aw_arb_grt : I_S_AW_RP_SEL[RP_SEL_WD-1:0];

genvar p;
//==============================================================
//                          AW, W, B
//==============================================================

always_ff @(posedge I_CLK or negedge I_RESETN) begin
    if (~I_RESETN) begin
        r_s_wbusy_tt <= 'd0;
        r_aw_arb_grt <= 'd0;   
    end else begin
        if ((I_S_AWVALID & O_S_AWREADY)) begin
            if (I_S_WVALID[w_aw_arb_grt_mux] & O_S_WREADY[w_aw_arb_grt_mux] & I_S_WLAST[w_aw_arb_grt_mux])
                r_s_wbusy_tt <= 1'b0;
            else begin
                r_s_wbusy_tt <= 1'b1;
                r_aw_arb_grt <= I_S_AW_RP_SEL[RP_SEL_WD-1:0];
            end

        end else begin
            if (r_s_wbusy_tt & I_S_WVALID[w_aw_arb_grt_mux] & O_S_WREADY[w_aw_arb_grt_mux] & I_S_WLAST[w_aw_arb_grt_mux])
                r_s_wbusy_tt <=1'b0;
        end
    end
end

generate
if(RP_SEL_WD==1) 
    assign O_M_AW_RP_SEL   = {1'b0, w_aw_arb_grt_mux};
else
    assign O_M_AW_RP_SEL   = w_aw_arb_grt_mux;    
endgenerate
assign O_M_AWID        = I_S_AWID    ;
assign O_M_AWADDR      = I_S_AWADDR  ;
assign O_M_AWLEN       = I_S_AWLEN   ;
assign O_M_AWSIZE      = I_S_AWSIZE  ;
assign O_M_AWLOCK      = I_S_AWLOCK  ;
assign O_M_AWCACHE     = I_S_AWCACHE ;
assign O_M_AWPROT      = I_S_AWPROT  ;
assign O_M_AWQOS       = I_S_AWQOS   ;

assign O_M_WDATA       = I_S_WDATA[w_aw_arb_grt_mux ] ;
assign O_M_WSTRB       = I_S_WSTRB[w_aw_arb_grt_mux] ;
assign O_M_WLAST       = I_S_WLAST[w_aw_arb_grt_mux] ;
assign O_M_WSTRB_FULL  = I_S_WSTRB_FULL[w_aw_arb_grt_mux] ;

assign O_M_AWVALID     = ~r_s_wbusy_tt & I_S_AWVALID;

assign O_M_WVALID      = ((~r_s_wbusy_tt & I_S_AWVALID & O_S_AWREADY) | r_s_wbusy_tt) & I_S_WVALID[w_aw_arb_grt_mux];

assign  w_no_awvalid    = ~I_S_AWVALID;

assign O_S_AWREADY = ~r_s_wbusy_tt & (( I_M_AWREADY) | w_no_awvalid) ;

generate
    for(p = 0; p < AXI_SLV_NUM; p = p + 1) begin
        assign O_S_WREADY[p]  = ((~r_s_wbusy_tt & ((w_aw_arb_grt_mux == p) & I_S_AWVALID & O_S_AWREADY) ) |
                                (r_s_wbusy_tt & ((w_aw_arb_grt_mux == p) ))) & I_M_WREADY;

    end
endgenerate

endmodule

