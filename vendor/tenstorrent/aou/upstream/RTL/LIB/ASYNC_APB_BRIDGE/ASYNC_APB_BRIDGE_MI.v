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
//  Module     : ASYNC_APB_BRIDGE_MI
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module ASYNC_APB_BRIDGE_MI
#(
    parameter APB_ADDR_WD = 32
)
(
    //APB slave
    input                           I_M_PCLK,
    input                           I_M_PRESETN,

    output wire                     O_M_PSEL,
    output wire                     O_M_PENABLE,
    output wire  [APB_ADDR_WD-1:0]  O_M_PADDR,
    output wire                     O_M_PWRITE,
    output wire  [31:0]             O_M_PWDATA,

    input        [31:0]             I_M_PRDATA,
    input                           I_M_PREADY,
    input                           I_M_PSLVERR,
    //CROSS domain
    input        [APB_ADDR_WD-1:0]  I_S_PADDR,
    input                           I_S_PWRITE,
    input        [31:0]             I_S_PWDATA,

    input                           I_S_REQ_CLKS,
    output wire                     O_M_DONE,
    output wire  [31:0]             O_M_RDATA,
    output wire                     O_M_SLVERR
);

    reg                 r_mi_done_clkm;
    wire                w_si_req_clkm;

//cross domain

AOU_SOC_SYNCHSR #(
    .DW         ( 1                 ),
    .RST_VAL    ( 1'b0              ),
    .DEPTH      ( 2                 )
) u_bos_soc_synchsr(
    .I_CLK       ( I_M_PCLK          ),
    .I_RESETN    ( I_M_PRESETN       ),
    .I_D         ( I_S_REQ_CLKS      ),
    .O_Q         ( w_si_req_clkm     )
);

//master domain

    localparam          ST_M_IDLE   = 2'b00;
    localparam          ST_M_SETUP  = 2'b01;
    localparam          ST_M_ACCESS = 2'b10;
    localparam          ST_M_DONE   = 2'b11;

    reg           [1:0]  r_mi_crt_st;
    reg           [1:0]  mi_nxt_st;

    reg           [31:0] r_rdata;
    reg                  r_slverr;

    always @(posedge I_M_PCLK or negedge I_M_PRESETN) begin //FSM
        if (!I_M_PRESETN) begin
            r_mi_crt_st <= ST_M_IDLE;
        end else begin
            r_mi_crt_st <= mi_nxt_st;
        end
    end

    always @(*) begin //State define
        case (r_mi_crt_st)
            ST_M_IDLE :
                if (w_si_req_clkm) begin
                    mi_nxt_st = ST_M_SETUP;
                end else begin
                    mi_nxt_st = r_mi_crt_st;
                end
            ST_M_SETUP :
                mi_nxt_st = ST_M_ACCESS;
            ST_M_ACCESS :
                if (I_M_PREADY) begin
                    mi_nxt_st = ST_M_DONE;
                end else begin
                    mi_nxt_st = r_mi_crt_st;
                end
            ST_M_DONE :
                if (!w_si_req_clkm) begin
                    mi_nxt_st = ST_M_IDLE;
                end else begin
                    mi_nxt_st = r_mi_crt_st;
                end
            default:
                mi_nxt_st = ST_M_IDLE;
        endcase
    end

    always @(posedge I_M_PCLK or negedge I_M_PRESETN) begin //done send
        if (!I_M_PRESETN) begin
            r_mi_done_clkm <= 1'b0;
        end else begin
            if ((r_mi_crt_st==ST_M_ACCESS)&I_M_PREADY) begin
                r_mi_done_clkm <= 1'b1;
            end else if ((r_mi_crt_st==ST_M_DONE)&~w_si_req_clkm) begin
                r_mi_done_clkm <= 1'b0;
            end
        end
    end

    always @(posedge I_M_PCLK or negedge I_M_PRESETN) begin //rdata,slverr send
        if (!I_M_PRESETN) begin
            r_rdata <= 32'b0;
            r_slverr <= 1'b0;
        end else begin
            if (r_mi_crt_st == ST_M_ACCESS) begin
                r_slverr <= I_M_PSLVERR;
            end

            if ((r_mi_crt_st == ST_M_ACCESS) & I_M_PREADY) begin
                r_rdata <= I_M_PRDATA;
            end
        end
    end

    assign O_M_PSEL = (r_mi_crt_st==ST_M_SETUP|r_mi_crt_st==ST_M_ACCESS);
    assign O_M_PENABLE = r_mi_crt_st==ST_M_ACCESS;
    assign O_M_PADDR = I_S_PADDR;
    assign O_M_PWRITE = I_S_PWRITE;
    assign O_M_PWDATA = I_S_PWDATA;

    assign O_M_DONE = r_mi_done_clkm;
    assign O_M_RDATA = r_rdata;
    assign O_M_SLVERR = r_slverr;

endmodule
    
