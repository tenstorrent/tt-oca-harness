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
//  Module     : AOU_2X1_ARBITER
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module AOU_2X1_ARBITER (
    input           I_CLK,
    input           I_RESETN,

    input   [1:0]   I_REQ,
    input           I_ARB_EN,
    
    output  [1:0]   O_GRANTED_AGENT
);

reg     [1:0]   r_grant;
reg     [1:0]   r_prev_req;
reg             r_keep_prev_req;
wire    [1:0]   w_grant_next;

AOU_2X1_RR_ARBITER u_rr_arbiter(
    .I_REQUEST      (r_keep_prev_req ? r_prev_req : I_REQ),
    .I_GRANT        (r_grant        ),
    .O_GRANT_NEXT   (w_grant_next   )
);

wire    w_any_request = |I_REQ;

always @(posedge I_CLK or negedge I_RESETN) begin
    if (~I_RESETN) begin
        r_grant <=  2'b10;
    end else if (w_any_request & I_ARB_EN) begin
        r_grant <= w_grant_next;
    end
end

always @(posedge I_CLK or negedge I_RESETN) begin
    if (~I_RESETN) begin
        r_prev_req <= 2'd0;
    end else if (~r_keep_prev_req & ~I_ARB_EN) begin
        r_prev_req <= I_REQ;
    end
end

always @(posedge I_CLK or negedge I_RESETN) begin
    if (~I_RESETN) begin
        r_keep_prev_req <= 1'b0;
    end else if (w_any_request & ~I_ARB_EN) begin
        r_keep_prev_req <= 1'b1;
    end else if(I_ARB_EN) begin 
        r_keep_prev_req <= 1'b0;
    end
end


assign O_GRANTED_AGENT = w_grant_next;

endmodule

module AOU_2X1_RR_ARBITER (
    input       [1:0]   I_REQUEST,
    input       [1:0]   I_GRANT,

    output reg  [1:0]   O_GRANT_NEXT
);

always @(*) begin
    O_GRANT_NEXT = I_GRANT;
    case(1) 
        I_GRANT[0]:
            if      (I_REQUEST[1])  O_GRANT_NEXT = 2'b10;
            else if (I_REQUEST[0])  O_GRANT_NEXT = 2'b01;
        I_GRANT[1]:
            if      (I_REQUEST[0])  O_GRANT_NEXT = 2'b01;
            else if (I_REQUEST[1])  O_GRANT_NEXT = 2'b10;
    endcase
end

endmodule
