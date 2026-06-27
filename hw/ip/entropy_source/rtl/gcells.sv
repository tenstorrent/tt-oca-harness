// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//------------------------------------------------------------------------------
// Generic Standard Cells
//
// Description:
// Wrapper modules around technology specific standard cells. These are modules
// are primarily used by the ring oscillators which need to be tightly
// constrained.
//------------------------------------------------------------------------------

/* verilator lint_off DECLFILENAME */
module gbuff (
    input  logic d_i,
    output logic z_o
);
    /* verilator lint_off ASSIGNDLY */
    assign #1 z_o = d_i;
    /* verilator lint_on ASSIGNDLY */
endmodule
/* verilator lint_on DECLFILENAME */

module ginv (
    input  logic d_i,
    output logic z_o
);
    /* verilator lint_off ASSIGNDLY */
    assign #1 z_o = ~d_i;
    /* verilator lint_on ASSIGNDLY */
endmodule

module gnand2 (
    input  logic a_i,
    input  logic b_i,
    output logic z_o
);
    /* verilator lint_off ASSIGNDLY */
    assign #1 z_o = ~(a_i & b_i);
    /* verilator lint_on ASSIGNDLY */
endmodule

module gmux2 (
    input  logic i0_i,
    input  logic i1_i,
    input  logic s_i,
    output logic z_o
);
    /* verilator lint_off ASSIGNDLY */
    assign #1 z_o = s_i ? i1_i : i0_i;
    /* verilator lint_on ASSIGNDLY */
endmodule

// D flip-flop with async clear and single output
module gdff (
    input  logic d_i,
    input  logic cdn_i,
    input  logic cp_i,
    output logic q_o
);
    always @(posedge cp_i or negedge cdn_i) begin
        if (~cdn_i) begin
            q_o <= 1'b0;
        end else begin
            q_o <= d_i;
        end
    end
endmodule

// D flip-flop with async clear; inverting and non-inverting outputs
module gdffqb (
    input  logic d_i,
    input  logic cdn_i,
    input  logic cp_i,
    output logic q_o,
    output logic qb_o
);
    always @(posedge cp_i or negedge cdn_i) begin
        if (~cdn_i) begin
            q_o  <= 1'b0;
            qb_o <= 1'b1;
        end else begin
            q_o  <=  d_i;
            qb_o <= ~d_i;
        end
    end
endmodule

// Synchronizer
// Two cascaded flip-flops with optional
// metastable behavior in simulation
module gdffsync (
    input  logic d_i,
    input  logic cp_i,
    output logic q_o
);
  `ifdef SIMULATION
    logic df0_o, df1_i, dfe_i, dfe_o, edgein, metasig;
    // 1st stage flip-flop
    gdff df0 (
        .d_i,
        .cdn_i (1'b1),
        .cp_i,
        .q_o   (df0_o)
    );
    // HL|LH edge detector
    assign edgein = df0_o ^ d_i;
    gdff dfe (
        .d_i   (edgein),
        .cdn_i (1'b1),
        .cp_i,
        .q_o   (dfe_o)
    );
    // 2nd flip-flop randomly goes metastable on HL|LH edges
    assign metasig = dfe_o & $random;
    assign df1_i = metasig ^ df0_o;
    gdff df1 (
        .d_i   (df1_i),
        .cdn_i (1'b1),
        .cp_i,
        .q_o
    );

    always_comb begin
        if (metasig) begin
            $display($time, "metastable event");
        end
    end
  `else
    // potentially metastable signal has time to stabilize
    // then is sampled by 2nd flip-flop
    logic metasig;

    gdff df0 (
        .d_i,
        .cdn_i (1'b1),
        .cp_i,
        .q_o   (metasig)
    );
    gdff df1 (
        .d_i   (metasig),
        .cdn_i (1'b1),
        .cp_i,
        .q_o
    );
  `endif
endmodule
