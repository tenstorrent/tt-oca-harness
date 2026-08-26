// Module: mmr_read_delay
// Description:
//   Generates delayed MMR chip-select strobes for multi-cycle read paths and
//   manages JTAG MMR request handshaking.
//
//   Read delay staging:
//     - Regular MMR registers : 1-cycle delay  (conv_MmrCs -> MmrCs_d1)
//     - Trace RAM registers   : 3-cycle delay  (conv_MmrCs -> MmrCs_d3),
//       with a stretch flop to hold the select active while the RAM completes
//       a write before the read can proceed (masked by TraceRamWrEn).
//     - MmrRdCs_d2 is the 2-cycle delayed read-chip-select for data capture.
//
//   JTAG interface (active when HAS_JTAG=1):
//     - jt_wr_rsp_vld  : 1-cycle self-clearing pulse acknowledging a JTAG
//                        write request (set when jt_mmr_req_vld & jt_mmr_req_we,
//                        cleared the following cycle via synchronous self-clear).
//     - jt_rd_req_pend : held high from a JTAG read request until jt_rsp_vld.
//     - jt_rsp_vld     : combined response valid (write ack OR read data ready).
//
// Parameters:
//   HAS_JTAG : 1 = instantiate JTAG interface logic; 0 = tie off JTAG outputs.
module mmr_read_delay #(
    parameter HAS_JTAG = 0
) (
    input  logic clk,
    input  logic reset_n,

    input  logic conv_MmrCs,
    input  logic MmrWrEn,
    input  logic TraceRamWrEn,
    input  logic is_ram_addr,

    // JTAG interface (active when HAS_JTAG=1)
    input  logic jt_mmr_req_vld,
    input  logic jt_mmr_req_we,
    output logic jt_wr_rsp_vld,
    output logic jt_rd_req_pend,
    output logic jt_rsp_vld,

    output logic MmrCs,
    output logic MmrCs_d1,
    output logic MmrCs_d3,
    output logic MmrRdCs_d2
);

    logic int_MmrCs_stretch;
    logic int_MmrCs_level_pulse;
    logic int_MmrRdCs;
    logic int_MmrRamRdCs;
    logic int_MmrRdCs_d1, int_MmrRdCs_d2;
    logic int_MmrCs_d1, int_MmrCs_d2, int_MmrCs_d3;

    logic jt_vld_int, jt_we_int;
    logic jt_wr_rsp_vld_int, jt_rd_req_pend_int, jt_rsp_vld_int;

    if (HAS_JTAG) begin : gen_jtag
        assign jt_vld_int = jt_mmr_req_vld;
        assign jt_we_int  = jt_mmr_req_we;

        generic_dff_clr #(
            .WIDTH       ($bits(logic)),
            .RESET_VALUE ('0)
        ) u_jt_wr_rsp_vld_ff (
            .clk   (clk),
            .rst_n (reset_n),
            .en    (jt_vld_int & jt_we_int),
            .clr   (jt_wr_rsp_vld_int),
            .in    (1'b1),
            .out   (jt_wr_rsp_vld_int)
        );

        generic_dff_clr #(
            .WIDTH       ($bits(logic)),
            .RESET_VALUE ('0)
        ) u_jt_rd_req_pend_ff (
            .clk   (clk),
            .rst_n (reset_n),
            .en    (jt_vld_int & ~jt_we_int),
            .clr   (jt_rsp_vld_int),
            .in    (1'b1),
            .out   (jt_rd_req_pend_int)
        );

        assign jt_rsp_vld_int = jt_wr_rsp_vld_int | (jt_rd_req_pend_int & int_MmrCs_d3);
    end else begin : gen_no_jtag
        assign jt_vld_int        = 1'b0;
        assign jt_we_int         = 1'b0;
        assign jt_wr_rsp_vld_int = 1'b0;
        assign jt_rd_req_pend_int = 1'b0;
        assign jt_rsp_vld_int    = 1'b0;
    end

    assign jt_wr_rsp_vld  = jt_wr_rsp_vld_int;
    assign jt_rd_req_pend = jt_rd_req_pend_int;
    assign jt_rsp_vld     = jt_rsp_vld_int;

    generic_dff_clr #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_stretch_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    (is_ram_addr & conv_MmrCs),
        .clr   (~TraceRamWrEn),
        .in    (conv_MmrCs),
        .out   (int_MmrCs_stretch)
    );

    assign int_MmrCs_level_pulse = conv_MmrCs | int_MmrCs_stretch;

    assign int_MmrRdCs = is_ram_addr ? (~TraceRamWrEn & int_MmrCs_level_pulse & ~MmrWrEn)
                                     : (int_MmrCs_level_pulse & ~MmrWrEn);

    generic_dff_clr #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_ram_rd_cs_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    (int_MmrRdCs & is_ram_addr),
        .clr   (int_MmrCs_d3 & ~(int_MmrRdCs & is_ram_addr)),
        .in    (int_MmrRdCs),
        .out   (int_MmrRamRdCs)
    );

    generic_dff #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_rd_cs_d1_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    ('1),
        .in    (int_MmrRdCs),
        .out   (int_MmrRdCs_d1)
    );

    generic_dff #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_rd_cs_d2_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    ('1),
        .in    (int_MmrRdCs_d1),
        .out   (int_MmrRdCs_d2)
    );

    assign MmrCs = (int_MmrCs_level_pulse & MmrWrEn)
                 | int_MmrRdCs
                 | int_MmrRamRdCs
                 | jt_vld_int;

    generic_dff #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_cs_d1_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    (~TraceRamWrEn | (MmrCs & ~MmrWrEn)),
        .in    (MmrCs & ~MmrWrEn),
        .out   (int_MmrCs_d1)
    );

    generic_dff #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_cs_d2_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    ('1),
        .in    (int_MmrCs_d1),
        .out   (int_MmrCs_d2)
    );

    generic_dff #(
        .WIDTH       ($bits(logic)),
        .RESET_VALUE ('0)
    ) u_cs_d3_ff (
        .clk   (clk),
        .rst_n (reset_n),
        .en    ('1),
        .in    (int_MmrCs_d2),
        .out   (int_MmrCs_d3)
    );

    assign MmrCs_d1   = int_MmrCs_d1;
    assign MmrCs_d3   = int_MmrCs_d3;
    assign MmrRdCs_d2 = int_MmrRdCs_d2;

endmodule
