// *****************************************************************************
// SPDX-License-Identifier: Apache-2.0
// *****************************************************************************
//  Copyright (c) 2026 BOS Semiconductors
//  Copyright (c) 2026 Tenstorrent USA Inc
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
//
// Integrate FDI bringup with the AXI-over-UCIe core.
//
// Drive the core from the bringup controller. Forward FDI_CONFIG unchanged.
// Expose PHY1 only when TWO_PHY is defined.

`timescale 1ns/1ps

module AOU_TOP
import packet_def_pkg::*;
#(
    parameter   RP_COUNT                    = 1,  // Number of AXI ports.

    parameter int FDI_CONFIG                = FDI_CFG_SP_32B,  // FDI width pair. Forwarded to the core.

    localparam int FDI_IF_WD0 = (FDI_CONFIG == FDI_CFG_SP_32B     ) ? 256  :
                                (FDI_CONFIG == FDI_CFG_SP_64B     ) ? 512  :
                                (FDI_CONFIG == FDI_CFG_SP_128B    ) ? 1024 :
                                (FDI_CONFIG == FDI_CFG_TP_32B_64B ) ? 256  :
                                (FDI_CONFIG == FDI_CFG_TP_64B_128B) ? 512  : 256,  // PHY0 FDI width, in bits.
    localparam int FDI_IF_WD1 = (FDI_CONFIG == FDI_CFG_SP_32B     ) ? 512  :
                                (FDI_CONFIG == FDI_CFG_SP_64B     ) ? 512  :
                                (FDI_CONFIG == FDI_CFG_SP_128B    ) ? 1024 :
                                (FDI_CONFIG == FDI_CFG_TP_32B_64B ) ? 512  :
                                (FDI_CONFIG == FDI_CFG_TP_64B_128B) ? 1024 : 512,  // PHY1 FDI width, in bits.

    parameter   RP0_RX_AW_FIFO_DEPTH        = 44,  // RP0 write-address FIFO depth.
    parameter   RP0_RX_AR_FIFO_DEPTH        = 44,  // RP0 read-address FIFO depth.
    parameter   RP0_RX_W_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP0 write-data FIFO depth.
    parameter   RP0_RX_R_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP0 read-data FIFO depth.
    parameter   RP0_RX_B_FIFO_DEPTH         = 44,  // RP0 write-response FIFO depth.

    parameter   RP1_RX_AW_FIFO_DEPTH        = 44,  // RP1 write-address FIFO depth.
    parameter   RP1_RX_AR_FIFO_DEPTH        = 44,  // RP1 read-address FIFO depth.
    parameter   RP1_RX_W_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP1 write-data FIFO depth.
    parameter   RP1_RX_R_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP1 read-data FIFO depth.
    parameter   RP1_RX_B_FIFO_DEPTH         = 44,  // RP1 write-response FIFO depth.

    parameter   RP2_RX_AW_FIFO_DEPTH        = 44,  // RP2 write-address FIFO depth.
    parameter   RP2_RX_AR_FIFO_DEPTH        = 44,  // RP2 read-address FIFO depth.
    parameter   RP2_RX_W_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP2 write-data FIFO depth.
    parameter   RP2_RX_R_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP2 read-data FIFO depth.
    parameter   RP2_RX_B_FIFO_DEPTH         = 44,  // RP2 write-response FIFO depth.

    parameter   RP3_RX_AW_FIFO_DEPTH        = 44,  // RP3 write-address FIFO depth.
    parameter   RP3_RX_AR_FIFO_DEPTH        = 44,  // RP3 read-address FIFO depth.
    parameter   RP3_RX_W_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP3 write-data FIFO depth.
    parameter   RP3_RX_R_FIFO_DEPTH         = ((FDI_IF_WD0 == 1024) || (FDI_IF_WD1 == 1024)) ? 140 : 88,  // RP3 read-data FIFO depth.
    parameter   RP3_RX_B_FIFO_DEPTH         = 44,  // RP3 write-response FIFO depth.

    parameter   RX_AW_FIFO_RS_EN            = 1,  // Register-slice the write-address FIFO.
    parameter   RX_AR_FIFO_RS_EN            = 1,  // Register-slice the read-address FIFO.
    parameter   RX_W_FIFO_RS_EN             = 1,  // Register-slice the write-data FIFO.
    parameter   RX_R_FIFO_RS_EN             = 1,  // Register-slice the read-data FIFO.
    parameter   RX_B_FIFO_RS_EN             = 1,  // Register-slice the write-response FIFO.

    parameter   RP0_AXI_DATA_WD             = 512,  // RP0 AXI data width.
    parameter   RP1_AXI_DATA_WD             = 512,  // RP1 AXI data width.
    parameter   RP2_AXI_DATA_WD             = 512,  // RP2 AXI data width.
    parameter   RP3_AXI_DATA_WD             = 512,  // RP3 AXI data width.

    parameter   AXI_PEER_DIE_MAX_DATA_WD    = 1024,  // Widest peer-die data path.

    parameter   APB_ADDR_WD                 = 32,  // APB address width.
    parameter   APB_DATA_WD                 = 32,  // APB data width.

    parameter   S_RD_MO_CNT                 = 32,  // Slave read outstanding count.
    parameter   S_WR_MO_CNT                 = 32,  // Slave write outstanding count.

    parameter   M_RD_MO_CNT                 = 32,  // Master read outstanding count.
    parameter   M_WR_MO_CNT                 = 32,  // Master write outstanding count.

    localparam  RP_AXI_DATA_WD_MAX          = max4(RP0_AXI_DATA_WD, RP1_AXI_DATA_WD, RP2_AXI_DATA_WD, RP3_AXI_DATA_WD),  // Widest root-port data width.
    localparam  RP_AXI_STRB_WD_MAX          = RP_AXI_DATA_WD_MAX / 8,  // Strobe width of that data path.

    localparam  AXI_ADDR_WD                 = 64,  // AXI address width.
    localparam  AXI_ID_WD                   = 10,  // AXI ID width.
    localparam  AXI_LEN_WD                  = 8  // AXI length width.
)
(
    input  logic                                        I_CLK,  // Clock the core.
    input  logic                                        I_RESETN,  // Reset the core. Active-low.

    input  logic                                        I_PCLK,  // Clock the APB slave.
    input  logic                                        I_PRESETN,  // Reset the APB slave. Active-low.

    input  logic                                        I_AOU_APB_SI0_PSEL,  // APB slave select.
    input  logic                                        I_AOU_APB_SI0_PENABLE,  // APB enable.
    input  logic [APB_ADDR_WD-1:0]                      I_AOU_APB_SI0_PADDR,  // APB address.
    input  logic                                        I_AOU_APB_SI0_PWRITE,  // APB write strobe.
    input  logic [APB_DATA_WD-1:0]                      I_AOU_APB_SI0_PWDATA,  // APB write data.

    output logic [APB_DATA_WD-1:0]                      O_AOU_APB_SI0_PRDATA,  // APB read data.
    output logic                                        O_AOU_APB_SI0_PREADY,  // APB ready.
    output logic                                        O_AOU_APB_SI0_PSLVERR,  // APB slave error.

    output logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          O_AOU_RX_AXI_M_ARID,  // Downstream master read-address ID.
    output logic [RP_COUNT-1:0][AXI_ADDR_WD-1:0]        O_AOU_RX_AXI_M_ARADDR,  // Downstream master read address.
    output logic [RP_COUNT-1:0][AXI_LEN_WD-1:0]         O_AOU_RX_AXI_M_ARLEN,  // Downstream master read burst length.
    output logic [RP_COUNT-1:0][2:0]                    O_AOU_RX_AXI_M_ARSIZE,  // Downstream master read size.
    output logic [RP_COUNT-1:0][1:0]                    O_AOU_RX_AXI_M_ARBURST,  // Downstream master read burst type.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_ARLOCK,  // Downstream master read lock.
    output logic [RP_COUNT-1:0][3:0]                    O_AOU_RX_AXI_M_ARCACHE,  // Downstream master read cache.
    output logic [RP_COUNT-1:0][2:0]                    O_AOU_RX_AXI_M_ARPROT,  // Downstream master read protection.
    output logic [RP_COUNT-1:0][3:0]                    O_AOU_RX_AXI_M_ARQOS,  // Downstream master read QoS.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_ARVALID,  // Downstream master read-address valid.
    input  logic [RP_COUNT-1:0]                         I_AOU_RX_AXI_M_ARREADY,  // Downstream master read-address ready.

    input  logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          I_AOU_TX_AXI_M_RID,  // Downstream master read ID.
    input  logic [RP_COUNT-1:0][RP_AXI_DATA_WD_MAX-1:0] I_AOU_TX_AXI_M_RDATA,  // Downstream master read data.
    input  logic [RP_COUNT-1:0][1:0]                    I_AOU_TX_AXI_M_RRESP,  // Downstream master read response.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_M_RLAST,  // Downstream master read last.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_M_RVALID,  // Downstream master read valid.
    output logic [RP_COUNT-1:0]                         O_AOU_TX_AXI_M_RREADY,  // Downstream master read ready.

    output logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          O_AOU_RX_AXI_M_AWID,  // Downstream master write-address ID.
    output logic [RP_COUNT-1:0][AXI_ADDR_WD-1:0]        O_AOU_RX_AXI_M_AWADDR,  // Downstream master write address.
    output logic [RP_COUNT-1:0][AXI_LEN_WD-1:0]         O_AOU_RX_AXI_M_AWLEN,  // Downstream master write burst length.
    output logic [RP_COUNT-1:0][2:0]                    O_AOU_RX_AXI_M_AWSIZE,  // Downstream master write size.
    output logic [RP_COUNT-1:0][1:0]                    O_AOU_RX_AXI_M_AWBURST,  // Downstream master write burst type.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_AWLOCK,  // Downstream master write lock.
    output logic [RP_COUNT-1:0][3:0]                    O_AOU_RX_AXI_M_AWCACHE,  // Downstream master write cache.
    output logic [RP_COUNT-1:0][2:0]                    O_AOU_RX_AXI_M_AWPROT,  // Downstream master write protection.
    output logic [RP_COUNT-1:0][3:0]                    O_AOU_RX_AXI_M_AWQOS,  // Downstream master write QoS.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_AWVALID,  // Downstream master write-address valid.
    input  logic [RP_COUNT-1:0]                         I_AOU_RX_AXI_M_AWREADY,  // Downstream master write-address ready.

    output logic [RP_COUNT-1:0][RP_AXI_DATA_WD_MAX-1:0] O_AOU_RX_AXI_M_WDATA,  // Downstream master write data.
    output logic [RP_COUNT-1:0][RP_AXI_STRB_WD_MAX-1:0] O_AOU_RX_AXI_M_WSTRB,  // Downstream master write strobe.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_WLAST,  // Downstream master write last.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_M_WVALID,  // Downstream master write valid.
    input  logic [RP_COUNT-1:0]                         I_AOU_RX_AXI_M_WREADY,  // Downstream master write ready.

    input  logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          I_AOU_TX_AXI_M_BID,  // Downstream master write-response ID.
    input  logic [RP_COUNT-1:0][1:0]                    I_AOU_TX_AXI_M_BRESP,  // Downstream master write response.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_M_BVALID,  // Downstream master write-response valid.
    output logic [RP_COUNT-1:0]                         O_AOU_TX_AXI_M_BREADY,  // Downstream master write-response ready.

    input  logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          I_AOU_TX_AXI_S_ARID,  // Upstream slave read-address ID.
    input  logic [RP_COUNT-1:0][AXI_ADDR_WD-1:0]        I_AOU_TX_AXI_S_ARADDR,  // Upstream slave read address.
    input  logic [RP_COUNT-1:0][AXI_LEN_WD-1:0]         I_AOU_TX_AXI_S_ARLEN,  // Upstream slave read burst length.
    input  logic [RP_COUNT-1:0][2:0]                    I_AOU_TX_AXI_S_ARSIZE,  // Upstream slave read size.
    input  logic [RP_COUNT-1:0][1:0]                    I_AOU_TX_AXI_S_ARBURST,  // Upstream slave read burst type.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_ARLOCK,  // Upstream slave read lock.
    input  logic [RP_COUNT-1:0][3:0]                    I_AOU_TX_AXI_S_ARCACHE,  // Upstream slave read cache.
    input  logic [RP_COUNT-1:0][2:0]                    I_AOU_TX_AXI_S_ARPROT,  // Upstream slave read protection.
    input  logic [RP_COUNT-1:0][3:0]                    I_AOU_TX_AXI_S_ARQOS,  // Upstream slave read QoS.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_ARVALID,  // Upstream slave read-address valid.
    output logic [RP_COUNT-1:0]                         O_AOU_TX_AXI_S_ARREADY,  // Upstream slave read-address ready.

    output logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          O_AOU_RX_AXI_S_RID,  // Upstream slave read ID.
    output logic [RP_COUNT-1:0][RP_AXI_DATA_WD_MAX-1:0] O_AOU_RX_AXI_S_RDATA,  // Upstream slave read data.
    output logic [RP_COUNT-1:0][1:0]                    O_AOU_RX_AXI_S_RRESP,  // Upstream slave read response.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_S_RLAST,  // Upstream slave read last.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_S_RVALID,  // Upstream slave read valid.
    input  logic [RP_COUNT-1:0]                         I_AOU_RX_AXI_S_RREADY,  // Upstream slave read ready.

    input  logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          I_AOU_TX_AXI_S_AWID,  // Upstream slave write-address ID.
    input  logic [RP_COUNT-1:0][AXI_ADDR_WD-1:0]        I_AOU_TX_AXI_S_AWADDR,  // Upstream slave write address.
    input  logic [RP_COUNT-1:0][AXI_LEN_WD-1:0]         I_AOU_TX_AXI_S_AWLEN,  // Upstream slave write burst length.
    input  logic [RP_COUNT-1:0][2:0]                    I_AOU_TX_AXI_S_AWSIZE,  // Upstream slave write size.
    input  logic [RP_COUNT-1:0][1:0]                    I_AOU_TX_AXI_S_AWBURST,  // Upstream slave write burst type.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_AWLOCK,  // Upstream slave write lock.
    input  logic [RP_COUNT-1:0][3:0]                    I_AOU_TX_AXI_S_AWCACHE,  // Upstream slave write cache.
    input  logic [RP_COUNT-1:0][2:0]                    I_AOU_TX_AXI_S_AWPROT,  // Upstream slave write protection.
    input  logic [RP_COUNT-1:0][3:0]                    I_AOU_TX_AXI_S_AWQOS,  // Upstream slave write QoS.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_AWVALID,  // Upstream slave write-address valid.
    output logic [RP_COUNT-1:0]                         O_AOU_TX_AXI_S_AWREADY,  // Upstream slave write-address ready.

    input  logic [RP_COUNT-1:0][RP_AXI_DATA_WD_MAX-1:0] I_AOU_TX_AXI_S_WDATA,  // Upstream slave write data.
    input  logic [RP_COUNT-1:0][RP_AXI_STRB_WD_MAX-1:0] I_AOU_TX_AXI_S_WSTRB,  // Upstream slave write strobe.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_WLAST,  // Upstream slave write last.
    input  logic [RP_COUNT-1:0]                         I_AOU_TX_AXI_S_WVALID,  // Upstream slave write valid.
    output logic [RP_COUNT-1:0]                         O_AOU_TX_AXI_S_WREADY,  // Upstream slave write ready.

    output logic [RP_COUNT-1:0][AXI_ID_WD-1:0]          O_AOU_RX_AXI_S_BID,  // Upstream slave write-response ID.
    output logic [RP_COUNT-1:0][1:0]                    O_AOU_RX_AXI_S_BRESP,  // Upstream slave write response.
    output logic [RP_COUNT-1:0]                         O_AOU_RX_AXI_S_BVALID,  // Upstream slave write-response valid.
    input  logic [RP_COUNT-1:0]                         I_AOU_RX_AXI_S_BREADY,  // Upstream slave write-response ready.

`ifdef TWO_PHY
    input  logic                                        I_PHY_TYPE,  // Select PHY1 when set.
`endif

    input  logic                                        I_FDI_PL_0_VALID,  // PHY0 PHY payload valid.
    input  logic [FDI_IF_WD0-1:0]                       I_FDI_PL_0_DATA,  // PHY0 PHY payload.
    input  logic                                        I_FDI_PL_0_FLIT_CANCEL,  // PHY0 PHY flit cancel.

    input  logic                                        I_FDI_PL_0_TRDY,  // PHY0 PHY target ready.
    input  logic                                        I_FDI_PL_0_STALLREQ,  // PHY0 PHY stall request.
    input  logic [3:0]                                  I_FDI_PL_0_STATE_STS,  // PHY0 PHY link state.
    output logic [FDI_IF_WD0-1:0]                       O_FDI_LP_0_DATA,  // PHY0 link partner payload.
    output logic                                        O_FDI_LP_0_VALID,  // PHY0 link partner payload valid.
    output logic                                        O_FDI_LP_0_IRDY,  // PHY0 link partner initiator ready.
    output logic                                        O_FDI_LP_0_STALLACK,  // PHY0 link partner stall acknowledge.

`ifdef TWO_PHY
    input  logic                                        I_FDI_PL_1_VALID,  // PHY1 PHY payload valid.
    input  logic [FDI_IF_WD1-1:0]                       I_FDI_PL_1_DATA,  // PHY1 PHY payload.
    input  logic                                        I_FDI_PL_1_FLIT_CANCEL,  // PHY1 PHY flit cancel.

    input  logic                                        I_FDI_PL_1_TRDY,  // PHY1 PHY target ready.
    input  logic                                        I_FDI_PL_1_STALLREQ,  // PHY1 PHY stall request.
    input  logic [3:0]                                  I_FDI_PL_1_STATE_STS,  // PHY1 PHY link state.
    output logic [FDI_IF_WD1-1:0]                       O_FDI_LP_1_DATA,  // PHY1 link partner payload.
    output logic                                        O_FDI_LP_1_VALID,  // PHY1 link partner payload valid.
    output logic                                        O_FDI_LP_1_IRDY,  // PHY1 link partner initiator ready.
    output logic                                        O_FDI_LP_1_STALLACK,  // PHY1 link partner stall acknowledge.
`endif

    input  logic                                        I_PL_INBAND_PRES,  // In-band presence from the PHY.
    input  logic                                        I_PL_CLK_REQ,  // PHY clock request.
    input  logic                                        I_PL_WAKE_ACK,  // PHY wake acknowledge.
    input  logic                                        I_PL_RX_ACTIVE_REQ,  // PHY receive-active request.

    output logic [3:0]                                  O_LP_STATE_REQ,  // Requested link state.
    output logic                                        O_LP_WAKE_REQ,  // Wake the PHY.
    output logic                                        O_LP_CLK_ACK,  // Acknowledge the PHY clock.
    output logic                                        O_LP_RX_ACTIVE_STS,  // Receive-active status to the PHY.

    input  logic                                        I_SW_ACTIVATE_START,  // Start link activation.
    input  logic                                        I_SW_DEACTIVATE_START,  // Start link deactivation.
    input  logic                                        I_SW_RETRAIN_REQ,  // Request a retrain.
    input  logic                                        I_SW_LINKERROR_INJECT,  // Inject a link error.

    output logic [3:0]                                  O_FDI_FSM_STATE,  // Bringup state.
    output logic                                        O_FDI_LINK_UP,  // Link is up.

    output logic                                        INT_REQ_LINKRESET,  // Request a link reset.
    output logic                                        INT_SI0_ID_MISMATCH,  // Slave-port ID mismatch.
    output logic                                        INT_MI0_ID_MISMATCH,  // Master-port ID mismatch.
    output logic                                        INT_EARLY_RESP_ERR,  // Early-response error.
    output logic                                        INT_ACTIVATE_START,  // Activation started.
    output logic                                        INT_DEACTIVATE_START,  // Deactivation started.

    input  logic                                        I_MST_BUS_CLEANY_COMPLETE,  // Downstream bus is quiescent.
    input  logic                                        I_SLV_BUS_CLEANY_COMPLETE,  // Upstream bus is quiescent.

    input  logic                                        TIEL_DFT_MODESCAN  // Scan-mode tie-off.
);

    // ================================================================
    // Internal wires between bringup ctrl and core
    // ================================================================
    logic        w_int_fsm_in_active;
    logic        w_aou_activate_st_disabled;
    logic        w_aou_activate_st_enabled;
    logic        w_aou_req_linkreset;
    logic        w_int_activate_start;
    logic        w_int_deactivate_start;

    // Mux pl_state_sts / stallreq based on active PHY. Under TWO_PHY both PHYs
    // are valid and I_PHY_TYPE selects which one drives the bringup
    // controller; in single-PHY builds only PHY0 is present so its signals
    // are wired through directly.
    logic [3:0]  w_pl_state_sts_muxed;
    logic        w_pl_stallreq_muxed;

`ifdef TWO_PHY
    assign w_pl_state_sts_muxed = I_PHY_TYPE ? I_FDI_PL_1_STATE_STS
                                             : I_FDI_PL_0_STATE_STS;

    assign w_pl_stallreq_muxed  = I_PHY_TYPE ? I_FDI_PL_1_STALLREQ
                                             : I_FDI_PL_0_STALLREQ;
`else
    assign w_pl_state_sts_muxed = I_FDI_PL_0_STATE_STS;
    assign w_pl_stallreq_muxed  = I_FDI_PL_0_STALLREQ;
`endif

    // ================================================================
    // FDI Bringup Controller
    // ================================================================
    AOU_FDI_BRINGUP_CTRL u_fdi_bringup_ctrl (
        .I_CLK                      ( I_CLK                         ),
        .I_RESETN                   ( I_RESETN                      ),

        .I_PL_STATE_STS             ( w_pl_state_sts_muxed          ),
        .I_PL_INBAND_PRES           ( I_PL_INBAND_PRES              ),
        .I_PL_CLK_REQ               ( I_PL_CLK_REQ                  ),
        .I_PL_WAKE_ACK              ( I_PL_WAKE_ACK                 ),
        .I_PL_RX_ACTIVE_REQ         ( I_PL_RX_ACTIVE_REQ            ),
        .I_PL_STALLREQ              ( w_pl_stallreq_muxed            ),

        .O_LP_STATE_REQ             ( O_LP_STATE_REQ                ),
        .O_LP_WAKE_REQ              ( O_LP_WAKE_REQ                 ),
        .O_LP_CLK_ACK               ( O_LP_CLK_ACK                  ),
        .O_LP_RX_ACTIVE_STS         ( O_LP_RX_ACTIVE_STS            ),

        .O_INT_FSM_IN_ACTIVE        ( w_int_fsm_in_active           ),
        .I_AOU_ACTIVATE_ST_DISABLED ( w_aou_activate_st_disabled    ),
        .I_AOU_ACTIVATE_ST_ENABLED  ( w_aou_activate_st_enabled     ),
        .I_AOU_REQ_LINKRESET        ( w_aou_req_linkreset           ),
        .I_INT_ACTIVATE_START       ( w_int_activate_start          ),
        .I_INT_DEACTIVATE_START     ( w_int_deactivate_start        ),

        .I_SW_ACTIVATE_START        ( I_SW_ACTIVATE_START           ),
        .I_SW_DEACTIVATE_START      ( I_SW_DEACTIVATE_START         ),
        .I_SW_RETRAIN_REQ           ( I_SW_RETRAIN_REQ              ),
        .I_SW_LINKERROR_INJECT      ( I_SW_LINKERROR_INJECT         ),

        .O_FSM_STATE                ( O_FDI_FSM_STATE               ),
        .O_LINK_UP                  ( O_FDI_LINK_UP                 )
    );

    // ================================================================
    // AOU Core Top (protocol engine + FIFOs + AXI interfaces)
    // ================================================================
    AOU_CORE_TOP #(
        .RP_COUNT                   ( RP_COUNT                      ),

        .FDI_CONFIG                ( FDI_CONFIG                   ),

        .RP0_RX_AW_FIFO_DEPTH      ( RP0_RX_AW_FIFO_DEPTH         ),
        .RP0_RX_AR_FIFO_DEPTH      ( RP0_RX_AR_FIFO_DEPTH         ),
        .RP0_RX_W_FIFO_DEPTH       ( RP0_RX_W_FIFO_DEPTH          ),
        .RP0_RX_R_FIFO_DEPTH       ( RP0_RX_R_FIFO_DEPTH          ),
        .RP0_RX_B_FIFO_DEPTH       ( RP0_RX_B_FIFO_DEPTH          ),

        .RP1_RX_AW_FIFO_DEPTH      ( RP1_RX_AW_FIFO_DEPTH         ),
        .RP1_RX_AR_FIFO_DEPTH      ( RP1_RX_AR_FIFO_DEPTH         ),
        .RP1_RX_W_FIFO_DEPTH       ( RP1_RX_W_FIFO_DEPTH          ),
        .RP1_RX_R_FIFO_DEPTH       ( RP1_RX_R_FIFO_DEPTH          ),
        .RP1_RX_B_FIFO_DEPTH       ( RP1_RX_B_FIFO_DEPTH          ),

        .RP2_RX_AW_FIFO_DEPTH      ( RP2_RX_AW_FIFO_DEPTH         ),
        .RP2_RX_AR_FIFO_DEPTH      ( RP2_RX_AR_FIFO_DEPTH         ),
        .RP2_RX_W_FIFO_DEPTH       ( RP2_RX_W_FIFO_DEPTH          ),
        .RP2_RX_R_FIFO_DEPTH       ( RP2_RX_R_FIFO_DEPTH          ),
        .RP2_RX_B_FIFO_DEPTH       ( RP2_RX_B_FIFO_DEPTH          ),

        .RP3_RX_AW_FIFO_DEPTH      ( RP3_RX_AW_FIFO_DEPTH         ),
        .RP3_RX_AR_FIFO_DEPTH      ( RP3_RX_AR_FIFO_DEPTH         ),
        .RP3_RX_W_FIFO_DEPTH       ( RP3_RX_W_FIFO_DEPTH          ),
        .RP3_RX_R_FIFO_DEPTH       ( RP3_RX_R_FIFO_DEPTH          ),
        .RP3_RX_B_FIFO_DEPTH       ( RP3_RX_B_FIFO_DEPTH          ),

        .RX_AW_FIFO_RS_EN          ( RX_AW_FIFO_RS_EN             ),
        .RX_AR_FIFO_RS_EN          ( RX_AR_FIFO_RS_EN             ),
        .RX_W_FIFO_RS_EN           ( RX_W_FIFO_RS_EN              ),
        .RX_R_FIFO_RS_EN           ( RX_R_FIFO_RS_EN              ),
        .RX_B_FIFO_RS_EN           ( RX_B_FIFO_RS_EN              ),

        .RP0_AXI_DATA_WD           ( RP0_AXI_DATA_WD              ),
        .RP1_AXI_DATA_WD           ( RP1_AXI_DATA_WD              ),
        .RP2_AXI_DATA_WD           ( RP2_AXI_DATA_WD              ),
        .RP3_AXI_DATA_WD           ( RP3_AXI_DATA_WD              ),

        .AXI_PEER_DIE_MAX_DATA_WD  ( AXI_PEER_DIE_MAX_DATA_WD     ),

        .APB_ADDR_WD               ( APB_ADDR_WD                  ),
        .APB_DATA_WD               ( APB_DATA_WD                  ),

        .S_RD_MO_CNT               ( S_RD_MO_CNT                  ),
        .S_WR_MO_CNT               ( S_WR_MO_CNT                  ),

        .M_RD_MO_CNT               ( M_RD_MO_CNT                  ),
        .M_WR_MO_CNT               ( M_WR_MO_CNT                  )
    ) u_aou_core_top (
        .I_CLK                      ( I_CLK                         ),
        .I_RESETN                   ( I_RESETN                      ),

        .I_PCLK                     ( I_PCLK                        ),
        .I_PRESETN                  ( I_PRESETN                     ),

        .I_AOU_APB_SI0_PSEL         ( I_AOU_APB_SI0_PSEL            ),
        .I_AOU_APB_SI0_PENABLE      ( I_AOU_APB_SI0_PENABLE         ),
        .I_AOU_APB_SI0_PADDR        ( I_AOU_APB_SI0_PADDR           ),
        .I_AOU_APB_SI0_PWRITE       ( I_AOU_APB_SI0_PWRITE          ),
        .I_AOU_APB_SI0_PWDATA       ( I_AOU_APB_SI0_PWDATA          ),

        .O_AOU_APB_SI0_PRDATA       ( O_AOU_APB_SI0_PRDATA          ),
        .O_AOU_APB_SI0_PREADY       ( O_AOU_APB_SI0_PREADY          ),
        .O_AOU_APB_SI0_PSLVERR      ( O_AOU_APB_SI0_PSLVERR         ),

        .O_AOU_RX_AXI_M_ARID        ( O_AOU_RX_AXI_M_ARID           ),
        .O_AOU_RX_AXI_M_ARADDR      ( O_AOU_RX_AXI_M_ARADDR         ),
        .O_AOU_RX_AXI_M_ARLEN       ( O_AOU_RX_AXI_M_ARLEN          ),
        .O_AOU_RX_AXI_M_ARSIZE      ( O_AOU_RX_AXI_M_ARSIZE         ),
        .O_AOU_RX_AXI_M_ARBURST     ( O_AOU_RX_AXI_M_ARBURST        ),
        .O_AOU_RX_AXI_M_ARLOCK      ( O_AOU_RX_AXI_M_ARLOCK         ),
        .O_AOU_RX_AXI_M_ARCACHE     ( O_AOU_RX_AXI_M_ARCACHE        ),
        .O_AOU_RX_AXI_M_ARPROT      ( O_AOU_RX_AXI_M_ARPROT         ),
        .O_AOU_RX_AXI_M_ARQOS       ( O_AOU_RX_AXI_M_ARQOS          ),
        .O_AOU_RX_AXI_M_ARVALID     ( O_AOU_RX_AXI_M_ARVALID        ),
        .I_AOU_RX_AXI_M_ARREADY     ( I_AOU_RX_AXI_M_ARREADY        ),

        .I_AOU_TX_AXI_M_RID         ( I_AOU_TX_AXI_M_RID            ),
        .I_AOU_TX_AXI_M_RDATA       ( I_AOU_TX_AXI_M_RDATA          ),
        .I_AOU_TX_AXI_M_RRESP       ( I_AOU_TX_AXI_M_RRESP          ),
        .I_AOU_TX_AXI_M_RLAST       ( I_AOU_TX_AXI_M_RLAST          ),
        .I_AOU_TX_AXI_M_RVALID      ( I_AOU_TX_AXI_M_RVALID         ),
        .O_AOU_TX_AXI_M_RREADY      ( O_AOU_TX_AXI_M_RREADY         ),

        .O_AOU_RX_AXI_M_AWID        ( O_AOU_RX_AXI_M_AWID           ),
        .O_AOU_RX_AXI_M_AWADDR      ( O_AOU_RX_AXI_M_AWADDR         ),
        .O_AOU_RX_AXI_M_AWLEN       ( O_AOU_RX_AXI_M_AWLEN          ),
        .O_AOU_RX_AXI_M_AWSIZE      ( O_AOU_RX_AXI_M_AWSIZE         ),
        .O_AOU_RX_AXI_M_AWBURST     ( O_AOU_RX_AXI_M_AWBURST        ),
        .O_AOU_RX_AXI_M_AWLOCK      ( O_AOU_RX_AXI_M_AWLOCK         ),
        .O_AOU_RX_AXI_M_AWCACHE     ( O_AOU_RX_AXI_M_AWCACHE        ),
        .O_AOU_RX_AXI_M_AWPROT      ( O_AOU_RX_AXI_M_AWPROT         ),
        .O_AOU_RX_AXI_M_AWQOS       ( O_AOU_RX_AXI_M_AWQOS          ),
        .O_AOU_RX_AXI_M_AWVALID     ( O_AOU_RX_AXI_M_AWVALID        ),
        .I_AOU_RX_AXI_M_AWREADY     ( I_AOU_RX_AXI_M_AWREADY        ),

        .O_AOU_RX_AXI_M_WDATA       ( O_AOU_RX_AXI_M_WDATA          ),
        .O_AOU_RX_AXI_M_WSTRB       ( O_AOU_RX_AXI_M_WSTRB          ),
        .O_AOU_RX_AXI_M_WLAST       ( O_AOU_RX_AXI_M_WLAST          ),
        .O_AOU_RX_AXI_M_WVALID      ( O_AOU_RX_AXI_M_WVALID         ),
        .I_AOU_RX_AXI_M_WREADY      ( I_AOU_RX_AXI_M_WREADY         ),

        .I_AOU_TX_AXI_M_BID         ( I_AOU_TX_AXI_M_BID            ),
        .I_AOU_TX_AXI_M_BRESP       ( I_AOU_TX_AXI_M_BRESP          ),
        .I_AOU_TX_AXI_M_BVALID      ( I_AOU_TX_AXI_M_BVALID         ),
        .O_AOU_TX_AXI_M_BREADY      ( O_AOU_TX_AXI_M_BREADY         ),

        .I_AOU_TX_AXI_S_ARID        ( I_AOU_TX_AXI_S_ARID           ),
        .I_AOU_TX_AXI_S_ARADDR      ( I_AOU_TX_AXI_S_ARADDR         ),
        .I_AOU_TX_AXI_S_ARLEN       ( I_AOU_TX_AXI_S_ARLEN          ),
        .I_AOU_TX_AXI_S_ARSIZE      ( I_AOU_TX_AXI_S_ARSIZE         ),
        .I_AOU_TX_AXI_S_ARBURST     ( I_AOU_TX_AXI_S_ARBURST        ),
        .I_AOU_TX_AXI_S_ARLOCK      ( I_AOU_TX_AXI_S_ARLOCK         ),
        .I_AOU_TX_AXI_S_ARCACHE     ( I_AOU_TX_AXI_S_ARCACHE        ),
        .I_AOU_TX_AXI_S_ARPROT      ( I_AOU_TX_AXI_S_ARPROT         ),
        .I_AOU_TX_AXI_S_ARQOS       ( I_AOU_TX_AXI_S_ARQOS          ),
        .I_AOU_TX_AXI_S_ARVALID     ( I_AOU_TX_AXI_S_ARVALID        ),
        .O_AOU_TX_AXI_S_ARREADY     ( O_AOU_TX_AXI_S_ARREADY        ),

        .O_AOU_RX_AXI_S_RID         ( O_AOU_RX_AXI_S_RID            ),
        .O_AOU_RX_AXI_S_RDATA       ( O_AOU_RX_AXI_S_RDATA          ),
        .O_AOU_RX_AXI_S_RRESP       ( O_AOU_RX_AXI_S_RRESP          ),
        .O_AOU_RX_AXI_S_RLAST       ( O_AOU_RX_AXI_S_RLAST          ),
        .O_AOU_RX_AXI_S_RVALID      ( O_AOU_RX_AXI_S_RVALID         ),
        .I_AOU_RX_AXI_S_RREADY      ( I_AOU_RX_AXI_S_RREADY         ),

        .I_AOU_TX_AXI_S_AWID        ( I_AOU_TX_AXI_S_AWID           ),
        .I_AOU_TX_AXI_S_AWADDR      ( I_AOU_TX_AXI_S_AWADDR         ),
        .I_AOU_TX_AXI_S_AWLEN       ( I_AOU_TX_AXI_S_AWLEN          ),
        .I_AOU_TX_AXI_S_AWSIZE      ( I_AOU_TX_AXI_S_AWSIZE         ),
        .I_AOU_TX_AXI_S_AWBURST     ( I_AOU_TX_AXI_S_AWBURST        ),
        .I_AOU_TX_AXI_S_AWLOCK      ( I_AOU_TX_AXI_S_AWLOCK         ),
        .I_AOU_TX_AXI_S_AWCACHE     ( I_AOU_TX_AXI_S_AWCACHE        ),
        .I_AOU_TX_AXI_S_AWPROT      ( I_AOU_TX_AXI_S_AWPROT         ),
        .I_AOU_TX_AXI_S_AWQOS       ( I_AOU_TX_AXI_S_AWQOS          ),
        .I_AOU_TX_AXI_S_AWVALID     ( I_AOU_TX_AXI_S_AWVALID        ),
        .O_AOU_TX_AXI_S_AWREADY     ( O_AOU_TX_AXI_S_AWREADY        ),

        .I_AOU_TX_AXI_S_WDATA       ( I_AOU_TX_AXI_S_WDATA          ),
        .I_AOU_TX_AXI_S_WSTRB       ( I_AOU_TX_AXI_S_WSTRB          ),
        .I_AOU_TX_AXI_S_WLAST       ( I_AOU_TX_AXI_S_WLAST          ),
        .I_AOU_TX_AXI_S_WVALID      ( I_AOU_TX_AXI_S_WVALID         ),
        .O_AOU_TX_AXI_S_WREADY      ( O_AOU_TX_AXI_S_WREADY         ),

        .O_AOU_RX_AXI_S_BID         ( O_AOU_RX_AXI_S_BID            ),
        .O_AOU_RX_AXI_S_BRESP       ( O_AOU_RX_AXI_S_BRESP          ),
        .O_AOU_RX_AXI_S_BVALID      ( O_AOU_RX_AXI_S_BVALID         ),
        .I_AOU_RX_AXI_S_BREADY      ( I_AOU_RX_AXI_S_BREADY         ),

        .I_FDI_PL_0_VALID            ( I_FDI_PL_0_VALID              ),
        .I_FDI_PL_0_DATA             ( I_FDI_PL_0_DATA               ),
        .I_FDI_PL_0_FLIT_CANCEL      ( I_FDI_PL_0_FLIT_CANCEL        ),

        .I_FDI_PL_0_TRDY             ( I_FDI_PL_0_TRDY               ),
        .I_FDI_PL_0_STALLREQ         ( I_FDI_PL_0_STALLREQ           ),
        .I_FDI_PL_0_STATE_STS        ( I_FDI_PL_0_STATE_STS          ),
        .O_FDI_LP_0_DATA             ( O_FDI_LP_0_DATA               ),
        .O_FDI_LP_0_VALID            ( O_FDI_LP_0_VALID              ),
        .O_FDI_LP_0_IRDY             ( O_FDI_LP_0_IRDY               ),
        .O_FDI_LP_0_STALLACK         ( O_FDI_LP_0_STALLACK           ),

`ifdef TWO_PHY
        .I_PHY_TYPE                  ( I_PHY_TYPE                    ),

        .I_FDI_PL_1_VALID            ( I_FDI_PL_1_VALID              ),
        .I_FDI_PL_1_DATA             ( I_FDI_PL_1_DATA               ),
        .I_FDI_PL_1_FLIT_CANCEL      ( I_FDI_PL_1_FLIT_CANCEL        ),

        .I_FDI_PL_1_TRDY             ( I_FDI_PL_1_TRDY               ),
        .I_FDI_PL_1_STALLREQ         ( I_FDI_PL_1_STALLREQ           ),
        .I_FDI_PL_1_STATE_STS        ( I_FDI_PL_1_STATE_STS          ),
        .O_FDI_LP_1_DATA             ( O_FDI_LP_1_DATA               ),
        .O_FDI_LP_1_VALID            ( O_FDI_LP_1_VALID              ),
        .O_FDI_LP_1_IRDY             ( O_FDI_LP_1_IRDY               ),
        .O_FDI_LP_1_STALLACK         ( O_FDI_LP_1_STALLACK           ),
`endif

        .INT_REQ_LINKRESET           ( INT_REQ_LINKRESET             ),
        .INT_SI0_ID_MISMATCH         ( INT_SI0_ID_MISMATCH           ),
        .INT_MI0_ID_MISMATCH         ( INT_MI0_ID_MISMATCH           ),
        .INT_EARLY_RESP_ERR          ( INT_EARLY_RESP_ERR            ),
        .INT_ACTIVATE_START          ( w_int_activate_start          ),
        .INT_DEACTIVATE_START        ( w_int_deactivate_start        ),

        .I_INT_FSM_IN_ACTIVE         ( w_int_fsm_in_active           ),
        .I_MST_BUS_CLEANY_COMPLETE   ( I_MST_BUS_CLEANY_COMPLETE     ),
        .I_SLV_BUS_CLEANY_COMPLETE   ( I_SLV_BUS_CLEANY_COMPLETE     ),
        .O_AOU_ACTIVATE_ST_DISABLED  ( w_aou_activate_st_disabled    ),
        .O_AOU_ACTIVATE_ST_ENABLED   ( w_aou_activate_st_enabled     ),
        .O_AOU_REQ_LINKRESET         ( w_aou_req_linkreset           ),

        .TIEL_DFT_MODESCAN           ( TIEL_DFT_MODESCAN             )
    );

    // ================================================================
    // Interrupt pass-through
    // ================================================================
    assign INT_ACTIVATE_START   = w_int_activate_start;
    assign INT_DEACTIVATE_START = w_int_deactivate_start;

endmodule
