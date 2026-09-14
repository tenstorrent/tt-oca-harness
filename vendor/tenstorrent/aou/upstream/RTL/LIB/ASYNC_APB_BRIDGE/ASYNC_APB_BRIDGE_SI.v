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
//  Module     : ASYNC_APB_BRIDGE_SI
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module ASYNC_APB_BRIDGE_SI 
#(
    parameter APB_ADDR_WD = 32
)
(
    //APB slave
    input                           I_S_PCLK,
    input                           I_S_PRESETN,

    input                           I_S_PSEL,
    input                           I_S_PENABLE,
    input        [APB_ADDR_WD-1:0]  I_S_PADDR,
    input                           I_S_PWRITE,
    input        [31:0]             I_S_PWDATA,

    output wire  [31:0]             O_S_PRDATA,
    output wire                     O_S_PREADY,
    output wire                     O_S_PSLVERR,
    //CROSS domain
    output wire  [APB_ADDR_WD-1:0]  O_M_PADDR,
    output wire                     O_M_PWRITE,
    output wire  [31:0]             O_M_PWDATA,

    output wire                     O_S_REQ,
    input                           I_M_DONE_CLKM,
    input        [31:0]             I_M_RDATA_CLKM,
    input                           I_M_SLVERR_CLKM
);

    reg                 r_si_req_clks;
    wire                w_mi_done_clks;

//cross domain

AOU_SOC_SYNCHSR #(
    .DW         ( 1                 ),
    .RST_VAL    ( 1'b0              ),
    .DEPTH      ( 2                 )
) u_bos_soc_synchsr(
    .I_CLK       ( I_S_PCLK          ),
    .I_RESETN    ( I_S_PRESETN       ),
    .I_D         ( I_M_DONE_CLKM     ),
    .O_Q         ( w_mi_done_clks    )
);

//slave domain

    localparam           ST_S_IDLE    = 2'b00;
    localparam           ST_S_SETUP   = 2'b01;
    localparam           ST_S_ACCESS  = 2'b10;
    localparam           ST_S_DONE    = 2'b11;

    reg          [1:0]  r_si_crt_st;
    reg          [1:0]  si_nxt_st;

    always @(posedge I_S_PCLK or negedge I_S_PRESETN) begin //FSM
        if (!I_S_PRESETN) begin
            r_si_crt_st <= ST_S_IDLE;
        end else begin
            r_si_crt_st <= si_nxt_st;
        end
    end

    always @(*) begin //State define
        case (r_si_crt_st)
            ST_S_IDLE : 
                if (I_S_PSEL & ~I_S_PENABLE) begin
                    si_nxt_st = ST_S_SETUP;
                end else begin
                    si_nxt_st = r_si_crt_st;
                end
            ST_S_SETUP :
                if (w_mi_done_clks) begin
                    si_nxt_st = r_si_crt_st;
                end else begin
                    si_nxt_st = ST_S_ACCESS;
                end
            ST_S_ACCESS :
                if (w_mi_done_clks) begin
                    si_nxt_st = ST_S_DONE;
                end else begin
                    si_nxt_st = r_si_crt_st;
                end
            ST_S_DONE :
                    if(I_S_PSEL) begin
                        si_nxt_st = ST_S_SETUP;
                    end else begin
                        si_nxt_st = ST_S_IDLE;
                    end
            default :
                si_nxt_st = ST_S_IDLE;
        endcase
    end

    always @(posedge I_S_PCLK or negedge I_S_PRESETN) begin //req send
        if (!I_S_PRESETN) begin
            r_si_req_clks <= 1'b0;
        end else begin
            if (r_si_req_clks == 1'b0) begin
                r_si_req_clks <= (((r_si_crt_st == ST_S_IDLE|r_si_crt_st == ST_S_SETUP)|(r_si_crt_st == ST_S_ACCESS)) & ~w_mi_done_clks & I_S_PSEL);
            end else if ((r_si_crt_st == ST_S_ACCESS) & w_mi_done_clks) begin
                r_si_req_clks <= 1'b0;
            end
        end
    end

    assign O_S_PREADY = ~((r_si_crt_st==ST_S_SETUP)|((r_si_crt_st==ST_S_ACCESS) & ~w_mi_done_clks));
    assign O_S_PRDATA = I_M_RDATA_CLKM;
    assign O_S_PSLVERR= I_M_SLVERR_CLKM;

    assign O_M_PADDR  = I_S_PADDR;
    assign O_M_PWRITE = I_S_PWRITE;
    assign O_M_PWDATA = I_S_PWDATA;

    assign O_S_REQ    = r_si_req_clks;
    
endmodule
