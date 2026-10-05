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
//  Module     : AOU_SOC_SYNCHSR
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module AOU_SOC_SYNCHSR #(
    parameter          DW       = 1,
    parameter [DW-1:0] RST_VAL  = 0,
    parameter          DEPTH    = 2     // DEPTH 2, 3, 4 only use
)
(
    input           I_CLK     ,
    input           I_RESETN  ,
    input  [DW-1:0] I_D       ,
    output [DW-1:0] O_Q       
);

    genvar i;

        generate 
            for (i = 0; i < DW; i = i + 1) begin: sync_inst
                reg [DEPTH-1:0] r_dff;
                
                always @(posedge I_CLK or negedge I_RESETN) begin
                    if (~I_RESETN) begin
                        r_dff <= {(DEPTH){RST_VAL[i]}};
                    end else begin
                        r_dff <= {r_dff[DEPTH-2:0], I_D[i]};
                    end
                end

                assign O_Q[i] = r_dff[DEPTH-1];
            end
        endgenerate

endmodule


