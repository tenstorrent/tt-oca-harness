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
//  Module     : AOU_AXI_INST_SPLITTER
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module AOU_AXI_INST_SPLITTER #(
    parameter   ID_WD = 4,
                ADDR_WD = 32,
                LEN_WD = 4,
                SIZE_WD = 3,
                BURST_WD = 2,
                CACHE_WD = 4,
                PROT_WD = 3,
                I_DATA_WD = 256,
                O_DATA_WD = 128,
                INST_WD = 32
)
(
    input        [INST_WD-1:0]                             I_AW_INST,

    output       [ID_WD-1:0]                               O_SPLIT_AWID,        
    output       [ADDR_WD-1:0]                             O_SPLIT_AWADDR,      
    output       [LEN_WD-1:0]                              O_SPLIT_AWLEN,
    output       [SIZE_WD-1:0]                             O_SPLIT_AWSIZE,
    output       [BURST_WD-1:0]                            O_SPLIT_AWBURST,
    output                                                 O_SPLIT_AWLOCK,
    output       [CACHE_WD-1:0]                            O_SPLIT_AWCACHE,
    output       [PROT_WD-1:0]                             O_SPLIT_AWPROT,
    output       [3:0]                                     O_SPLIT_AWQOS
);
localparam INST_AxSIZE = $clog2(O_DATA_WD/8);
localparam ADDR_OFFSET = $clog2(I_DATA_WD/8);  

wire    [ADDR_WD-1:0]  w_origin_addr;
reg     [ADDR_WD-1:0]  w_modified_addr;

generate
    if($clog2(I_DATA_WD/8)==0) begin
        assign w_modified_addr = w_origin_addr[ADDR_WD-1:0];
    end else begin
        assign w_modified_addr = {w_origin_addr[ADDR_WD-1:$clog2(I_DATA_WD/8)], {$clog2(I_DATA_WD/8){1'b0}}};
    end
endgenerate

assign O_SPLIT_AWID     = I_AW_INST[INST_WD-1 :INST_WD-ID_WD];

assign w_origin_addr   = I_AW_INST[INST_WD-ID_WD-1 :INST_WD-ID_WD-ADDR_WD];
assign O_SPLIT_AWADDR  = w_modified_addr;

assign O_SPLIT_AWLEN    = ((I_AW_INST[INST_WD-ID_WD-ADDR_WD-1 :INST_WD-ID_WD-ADDR_WD-LEN_WD]+1) << ($clog2(I_DATA_WD/O_DATA_WD))) -1;
assign O_SPLIT_AWSIZE   = INST_AxSIZE;
assign O_SPLIT_AWBURST  = I_AW_INST[INST_WD-ID_WD-ADDR_WD-LEN_WD-SIZE_WD-1 :INST_WD-ID_WD-ADDR_WD-LEN_WD-SIZE_WD-BURST_WD];
assign O_SPLIT_AWLOCK   = I_AW_INST[CACHE_WD+PROT_WD+4+1-1:CACHE_WD+PROT_WD+4];
assign O_SPLIT_AWCACHE  = I_AW_INST[CACHE_WD+PROT_WD+4-1:PROT_WD+4];
assign O_SPLIT_AWPROT   = I_AW_INST[PROT_WD+4-1:4];
assign O_SPLIT_AWQOS    = I_AW_INST[3:0];


endmodule
