// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

 /*
    Multistage DFF. This module allows users to specify the number of staging flops inbetween input and output

    This module is built on the existing dfd_rv_dff modules. The i_en signal will enable ALL flops. 
 */

module dfd_rv_dff_staging #(parameter WIDTH=8,
                parameter DEPTH=2,
                parameter RESET_VALUE=0)
(
   input  logic             i_clk,
   input  logic             i_reset_n,
   input  logic             i_en,
   input  logic [WIDTH-1:0] i_d,

   output logic [WIDTH-1:0] o_q
);

   // spyglass disable_block STARC-2.3.4.3
   // spyglass disable_block FlopEConst
   /* verilator lint_off BLKANDNBLK */
   generate 
    if(DEPTH<=0) begin
        dfd_rv_dff #(.WIDTH(WIDTH), .RESET_VALUE(RESET_VALUE), .BYP(1)) u_dff_flop (
            .o_q(o_q),
            .i_d(i_d),
            .i_en(i_en),
            .i_clk(i_clk),
            .i_reset_n(i_reset_n)
        );
    end else if (DEPTH==1) begin
        dfd_rv_dff #(.WIDTH(WIDTH), .RESET_VALUE(RESET_VALUE), .BYP(0)) u_dff_flop (
            .o_q(o_q),
            .i_d(i_d),
            .i_en(i_en),
            .i_clk(i_clk),
            .i_reset_n(i_reset_n)
        );
    end else begin
        logic [DEPTH:0][WIDTH-1:0] int_q;

        assign o_q = int_q[DEPTH];
        assign int_q[0] = i_d;
        
        for (genvar ii = 0; ii < DEPTH; ii++) begin
            dfd_rv_dff #(.WIDTH(WIDTH), .RESET_VALUE(RESET_VALUE), .BYP(0)) u_dff_flop_int (
                .o_q(int_q[ii+1]),
                .i_d(int_q[ii]),
                .i_en(i_en),
                .i_clk(i_clk),
                .i_reset_n(i_reset_n)
            );
        end
    end
   endgenerate
   /* verilator lint_on BLKANDNBLK */
   // spyglass enable_block FlopEConst
   // spyglass enable_block STARC-2.3.4.3
   
endmodule 
// Local Variables:
// verilog-library-directories:(".")
// verilog-library-extensions:(".sv" ".h" ".v")
// verilog-typedef-regexp: "_[tseu]$"
// End:

