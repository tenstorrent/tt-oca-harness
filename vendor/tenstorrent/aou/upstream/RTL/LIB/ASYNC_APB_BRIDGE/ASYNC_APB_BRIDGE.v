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
//  Module     : ASYNC_APB_BRIDGE
//  Version    : 1.00
//  Date       : 26-02-26
//  Author     : Soyoung Min, Jaeyun Lee, Hojun Lee, Kwanho Kim
//
// *****************************************************************************

`timescale 1ns/1ps

module ASYNC_APB_BRIDGE
#(
    parameter APB_ADDR_WD = 32
)
(
    //APB slave
    input                           I_S_PCLK,
    input                           I_S_PRESETN,

    input                           I_S_PSEL,
    input                           I_S_PENABLE,
    input [APB_ADDR_WD-1:0]         I_S_PADDR,
    input                           I_S_PWRITE,
    input        [31:0]             I_S_PWDATA,
    output wire  [31:0]             O_S_PRDATA,
    output wire                     O_S_PREADY,
    output wire                     O_S_PSLVERR,

    //APB master
    input                           I_M_PCLK,
    input                           I_M_PRESETN,

    output wire                     O_M_PSEL,
    output wire                     O_M_PENABLE,
    output wire [APB_ADDR_WD-1:0]   O_M_PADDR,
    output wire                     O_M_PWRITE,
    output wire  [31:0]             O_M_PWDATA,
    input        [31:0]             I_M_PRDATA,
    input                           I_M_PREADY,
    input                           I_M_PSLVERR
);

    wire                    w_si_req_clks;   
    wire                    w_mi_done_clkm;
    
    wire         [31:0]     w_rdata_clkm;
    wire                    w_slverr_clkm;

    wire [APB_ADDR_WD-1:0]  w_si_paddr_clks;
    wire                    w_si_pwrite_clks;
    wire         [31:0]     w_si_pwdata_clks;

ASYNC_APB_BRIDGE_SI #(
    .APB_ADDR_WD (APB_ADDR_WD)
) u_async_apb_bridge_si
(
    .I_S_PCLK         (I_S_PCLK        ),   
    .I_S_PRESETN      (I_S_PRESETN     ),
 
    .I_S_PSEL         (I_S_PSEL        ),
    .I_S_PENABLE      (I_S_PENABLE     ),    
    .I_S_PADDR        (I_S_PADDR       ),
    .I_S_PWRITE       (I_S_PWRITE      ),
    .I_S_PWDATA       (I_S_PWDATA      ),

    .O_S_PRDATA       (O_S_PRDATA      ),
    .O_S_PREADY       (O_S_PREADY      ),
    .O_S_PSLVERR      (O_S_PSLVERR     ),

    .O_M_PADDR        (w_si_paddr_clks ),
    .O_M_PWRITE       (w_si_pwrite_clks),
    .O_M_PWDATA       (w_si_pwdata_clks),

    .O_S_REQ          (w_si_req_clks   ),
    .I_M_DONE_CLKM    (w_mi_done_clkm  ),
    .I_M_RDATA_CLKM   (w_rdata_clkm    ),
    .I_M_SLVERR_CLKM  (w_slverr_clkm   )
);

ASYNC_APB_BRIDGE_MI #(
    .APB_ADDR_WD (APB_ADDR_WD)
) u_async_apb_bridge_mi
(
    .I_M_PCLK         (I_M_PCLK        ),   
    .I_M_PRESETN      (I_M_PRESETN     ),
 
    .O_M_PSEL         (O_M_PSEL        ),
    .O_M_PENABLE      (O_M_PENABLE     ),    
    .O_M_PADDR        (O_M_PADDR       ),
    .O_M_PWRITE       (O_M_PWRITE      ),
    .O_M_PWDATA       (O_M_PWDATA      ),

    .I_M_PRDATA       (I_M_PRDATA      ),
    .I_M_PREADY       (I_M_PREADY      ),
    .I_M_PSLVERR      (I_M_PSLVERR     ),

    .I_S_PADDR        (w_si_paddr_clks ),
    .I_S_PWRITE       (w_si_pwrite_clks),
    .I_S_PWDATA       (w_si_pwdata_clks),

    .I_S_REQ_CLKS     (w_si_req_clks   ),
    .O_M_DONE         (w_mi_done_clkm  ),
    .O_M_RDATA        (w_rdata_clkm    ),
    .O_M_SLVERR       (w_slverr_clkm   )
);

endmodule
