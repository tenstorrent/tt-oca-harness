// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

module apb2mmr
import ntr_sink_mmr_pkg::*;
import dst_sink_mmr_pkg::*;
import dfd_pkg::*;
#(
    parameter DATA_WIDTH = 64, // Must be multiple of 32
    parameter ADDR_WIDTH = 17,
    parameter [ADDR_WIDTH-1:0] BASE_ADDR = 0,
    localparam APB_STRB_WIDTH = DATA_WIDTH / 8, // APB byte strobe (pstrb)
    localparam STRB_WIDTH = 2,                  // MMR 4-byte-lane strobe (MmrWrStrb/MmrWrStrb8B)
    parameter INST_WIDTH = 2,
    parameter NUM_MMR_BLOCKS = 1,
    parameter DST_SUPPORT = 1,
    parameter NTRACE_SUPPORT = 1
) (
    input  logic clk,
    input  logic reset_n,

    // APB
    input  logic [ADDR_WIDTH-1:0]  paddr,
    input  logic                   psel,
    input  logic                   penable,
    input  logic [APB_STRB_WIDTH -1:0] pstrb,
    input  logic                   pwrite,
    input  logic [DATA_WIDTH-1:0]  pwdata,
    output logic                   pready,
    output logic [DATA_WIDTH-1:0]  prdata,
    output logic                   pslverr,

    // MMR
    output  logic                   MmrCs, // Single-bit request valid; one-hot block select decoded externally
    output  logic                   MmrWrEn,
    output  logic  [STRB_WIDTH-1:0] MmrWrStrb,
    output  logic  [STRB_WIDTH-1:0] MmrWrStrb8B, // For 8B Mmrs
    output  logic                   MmrRegSel,
    output  logic  [12-1:0]         MmrAddr,
    output  logic  [DATA_WIDTH-1:0] MmrWrData,
    output  logic  [INST_WIDTH-1:0] MmrWrInstrType,
    input   logic                   MmrHit,
    input   logic  [DATA_WIDTH-1:0] MmrRdData,
    input   logic                   MmrError
);

    localparam [ADDR_WIDTH-1:0] MMR_END_ADDR = (ADDR_WIDTH)'(BASE_ADDR) + ((ADDR_WIDTH)'(NUM_MMR_BLOCKS) << 12);

    logic [ADDR_WIDTH-1:0]                paddr_base;
    logic APB_Setup;
    logic int_MmrCs;
    logic int_MmrWrEn,  int_MmrRegSel;
    logic [12-1:0] int_MmrAddr;
    logic [INST_WIDTH-1:0] int_MmrWrInstrType;
    logic [DATA_WIDTH-1:0] int_MmrWrData;
    logic [STRB_WIDTH-1:0] int_MmrWrStrb;
    logic [STRB_WIDTH-1:0] int_MmrWrStrb8B;

    assign APB_Setup = psel && ~penable;


    //APB <<--> MMR interface
    assign int_MmrWrInstrType = {INST_WIDTH{1'b0}};
    assign int_MmrAddr = paddr[12-1:0];
    assign int_MmrRegSel = APB_Setup && pwrite;
    assign int_MmrWrEn = pwrite;
    assign int_MmrWrData = pwdata;
    assign prdata = MmrRdData;
    assign paddr_base = paddr & {{(ADDR_WIDTH-12){1'b1}}, 12'h0};

    // Decode miss: a valid access targeting an address outside the mapped MMR
    // region [BASE_ADDR, MMR_END_ADDR) selects no block, so it must be
    // completed with a slave error rather than left to hang.
    logic decode_miss;
    assign decode_miss = psel && penable
                       && ~((paddr_base >= (ADDR_WIDTH)'(BASE_ADDR))
                         &&  (paddr_base <  (ADDR_WIDTH)'(MMR_END_ADDR)));

    assign pready = (psel && penable && (MmrHit || MmrError || decode_miss));

    // Single-cycle request valid (setup phase). The one-hot block select is
    // decoded externally in mmrs.sv, shared with the AXI path.
    assign int_MmrCs = APB_Setup;

    assign pslverr = psel && penable && (MmrError || decode_miss);

    always_comb begin
        int_MmrWrStrb = '0;
        for (int ii = 0; ii < DATA_WIDTH / 32; ii++) begin
            int_MmrWrStrb[ii] = &(pstrb[ii*4+:4]);
        end
    end

    if (DATA_WIDTH <= 32) begin : gen_wstrb_8b_d32
        assign int_MmrWrStrb8B = (int_MmrAddr[2] == 1'b0) ? {1'b0, int_MmrWrStrb[0]}: {int_MmrWrStrb[0], 1'b0} ;
    end else begin : gen_wstrb_8b_d64
        assign int_MmrWrStrb8B = int_MmrWrStrb;
    end


    always_comb begin
        if (~reset_n) begin
            MmrCs = '0;
            MmrWrEn = '0;
            MmrWrStrb = '0;
            MmrWrStrb8B = '0;
            MmrRegSel = '0;
            MmrAddr = '0;
            MmrWrData = '0;
            MmrWrInstrType = '0;
        end else begin
            MmrCs = int_MmrCs;
            MmrWrEn = int_MmrWrEn;
            MmrWrStrb = int_MmrWrStrb;
            MmrWrStrb8B = int_MmrWrStrb8B;
            MmrRegSel = int_MmrRegSel;
            MmrAddr = int_MmrAddr;
            MmrWrData = int_MmrWrData;
            MmrWrInstrType = int_MmrWrInstrType;
        end
    end

endmodule
