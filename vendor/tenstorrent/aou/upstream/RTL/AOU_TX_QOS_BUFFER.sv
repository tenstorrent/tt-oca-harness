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
//  Module     : AOU_TX_QOS_BUFFER
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

 /*
Module : QoS Buffer
Description : 
Receive 2 bit QoS field
00 : Low Priority
01 : Real_time
10 : High Priority
 */
 
 `timescale 1ns / 1ps

module AOU_TX_QOS_BUFFER #(
    parameter   FIFO_WIDTH = 16,
    parameter   FIFO_DEPTH = 8,
    parameter   AW = $clog2(FIFO_DEPTH),
    parameter   CNT_WD      = $clog2(FIFO_DEPTH+1),
    parameter   AXI_ID_WD   = 10
)
(
    input                       I_CLK           ,
    input                       I_RESETN        ,
    // write transaction
    input   [FIFO_WIDTH-1 : 0]  I_SDATA         ,
    input   [1:0]               I_TRANS_QOS     ,
    input                       I_SVALID        ,
    output                      O_SREADY        ,
    // read transaction
    output  [FIFO_WIDTH-1 : 0]  O_MDATA         ,
    output  [1:0]               O_TRANS_QOS     ,
    input                       I_MREADY        ,
    output                      O_MVALID        ,

    input  logic    [15:0]      I_PRIOR_TIMER_TIMER_RESOLUTION  ,    
    input  logic    [15:0]      I_PRIOR_TIMER_TIMER_THRESHOLD       

);

localparam INV  = 2'b00;
localparam LP   = 2'b01;
localparam NP   = 2'b10;
localparam HP   = 2'b11;

logic [15:0] timeout_threshold;
logic [15:0] timer_resolution;

assign timer_resolution  = I_PRIOR_TIMER_TIMER_RESOLUTION;
assign timeout_threshold = I_PRIOR_TIMER_TIMER_THRESHOLD;

//-------------------------------------------------------------------

reg  [AW-1 : 0]             r_cnt           ;
reg  [AW-1 : 0]             w_cnt           ;
wire [AW-1 : 0]             nxt_r_cnt       ;
wire [AW-1 : 0]             nxt_w_cnt       ;

reg                         r_ex_cnt        ;
reg                         w_ex_cnt        ;
wire                        nxt_r_ex_cnt    ;
wire                        nxt_w_ex_cnt    ;

typedef struct packed {
    logic [FIFO_WIDTH-1:0]  payload;
    logic [1:0]             qos;
    logic [15:0]            timeout_cnt;
} st_qos_table;

st_qos_table    [FIFO_DEPTH-1:0] mem;
//-------------------------------------------------------------------
assign nxt_r_cnt = (r_cnt == FIFO_DEPTH-1) ? ({AW{1'b0}}) : (r_cnt + 1'b1);
assign nxt_w_cnt = (w_cnt == FIFO_DEPTH-1) ? ({AW{1'b0}}) : (w_cnt + 1'b1);     

assign nxt_r_ex_cnt = (r_cnt == FIFO_DEPTH-1) ? ~r_ex_cnt : r_ex_cnt;
assign nxt_w_ex_cnt = (w_cnt == FIFO_DEPTH-1) ? ~w_ex_cnt : w_ex_cnt;     
//-------------------------------------------------------------------

//internal counter 
logic [15:0] r_internal_counter;
logic w_internal_count_tic;

always_ff @(posedge I_CLK or negedge I_RESETN) begin
    if (!I_RESETN) begin
        r_internal_counter <= 'b0;
    end else if (O_MVALID) begin
        r_internal_counter <= w_internal_count_tic ? 0 : r_internal_counter + 1;
    end
end

always_comb begin
    w_internal_count_tic = (r_internal_counter == timer_resolution);
end

integer i;
always @(posedge I_CLK or negedge I_RESETN) begin
    if (!I_RESETN) begin
        w_cnt <= {AW{1'b0}};
        w_ex_cnt <= 1'b0;

        r_cnt <= {AW{1'b0}};
        r_ex_cnt <= 1'b0;
        
        for(i = 0; i < FIFO_DEPTH; i = i + 1)
            mem[i] <= 0;

    end else begin
        // write transaction here
        if ( I_SVALID && O_SREADY) begin
            w_cnt       <= nxt_w_cnt;
            w_ex_cnt    <= nxt_w_ex_cnt;
            mem[w_cnt].payload  <= I_SDATA;
            mem[w_cnt].qos      <= I_TRANS_QOS;
            mem[w_cnt].timeout_cnt <= 'b0;
        end

        // read transaction here
        if (I_MREADY && O_MVALID) begin
            r_cnt       <= nxt_r_cnt;
            r_ex_cnt    <= nxt_r_ex_cnt;
            mem[r_cnt].qos <= 2'b00;
            mem[r_cnt].timeout_cnt <= 'b0;
        end

        if (w_internal_count_tic) begin
            for (int unsigned i = 0 ; i < FIFO_DEPTH ; i++) begin
                if ((mem[i].qos == NP) || (mem[i].qos == LP)) begin
                    mem[i].timeout_cnt <= (mem[i].timeout_cnt == timeout_threshold) ? mem[i].timeout_cnt : mem[i].timeout_cnt + 1;
                end
            end
        end
    end
end



logic w_expired_trans;

assign w_expired_trans = (mem[r_cnt].timeout_cnt == timeout_threshold);

//-------------------------------------------------------------------
assign O_SREADY     = ~((w_cnt == r_cnt) & (r_ex_cnt != w_ex_cnt)) ;
assign O_MVALID     = ~((w_cnt == r_cnt) & (r_ex_cnt == w_ex_cnt));
assign O_MDATA      = mem[r_cnt].payload;
assign O_TRANS_QOS  = w_expired_trans ? 2'b11 : mem[r_cnt].qos;

endmodule
