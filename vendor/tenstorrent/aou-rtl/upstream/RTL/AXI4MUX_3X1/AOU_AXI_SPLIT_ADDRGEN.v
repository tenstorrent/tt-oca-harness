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
//  Module     : AOU_AXI_SPLIT_ADDRGEN
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns / 1ps

module AOU_AXI_SPLIT_ADDRGEN #(
    parameter AXI_LEN_WD = 4
)
(
  input  [11 : 0]             I_AXI_AXADDR,
  input  [2 : 0]              I_AXI_AXSIZE,
  input  [AXI_LEN_WD-1 : 0]   I_AXI_AXLEN,

  output reg[11 : 0]          O_AXI_AXADDR
);


reg  [11 : 0] r_addr_offset;
wire [11 : 0] w_addr_incr;   


always @ (I_AXI_AXSIZE or I_AXI_AXADDR) begin
    case (I_AXI_AXSIZE)
      3'b000  : r_addr_offset = I_AXI_AXADDR[11:0];
      3'b001  : r_addr_offset = { 1'b0 ,  I_AXI_AXADDR[11:1] };
      3'b010  : r_addr_offset = { 2'b00,  I_AXI_AXADDR[11:2] };
      3'b011  : r_addr_offset = { 3'b000, I_AXI_AXADDR[11:3] };
      3'b100  : r_addr_offset = { 4'b0000, I_AXI_AXADDR[11:4] };
      3'b101  : r_addr_offset = { 5'b00000, I_AXI_AXADDR[11:5] };
      3'b110  : r_addr_offset = { 6'b000000, I_AXI_AXADDR[11:6] };
      3'b111  : r_addr_offset = { 7'b0000000, I_AXI_AXADDR[11:7] };
      default : r_addr_offset = {12{1'bx}}; 
    endcase
end


assign w_addr_incr = r_addr_offset + (I_AXI_AXLEN + 1);

always @ (I_AXI_AXSIZE or w_addr_incr) begin
    case (I_AXI_AXSIZE)
      3'b000  : O_AXI_AXADDR = w_addr_incr;
      3'b001  : O_AXI_AXADDR = {w_addr_incr [10:0], 1'b0 };
      3'b010  : O_AXI_AXADDR = {w_addr_incr [9:0], 2'b00};
      3'b011  : O_AXI_AXADDR = {w_addr_incr [8:0], 3'b000};
      3'b100  : O_AXI_AXADDR = {w_addr_incr [7:0], 4'b0000};
      3'b101  : O_AXI_AXADDR = {w_addr_incr [6:0], 5'b00000};
      3'b110  : O_AXI_AXADDR = {w_addr_incr [5:0], 6'b000000};
      3'b111  : O_AXI_AXADDR = {w_addr_incr [4:0], 7'b0000000};
      default : O_AXI_AXADDR = {12{1'bx}}; 
    endcase
end

endmodule
