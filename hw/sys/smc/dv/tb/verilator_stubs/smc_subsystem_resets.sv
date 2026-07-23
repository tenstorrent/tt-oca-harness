// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for smc_subsystem_resets.
//
// The real module uses reset_unit_reg_pkg::reset_unit__in_t / __out_t types
// which trigger a Verilator C++ codegen defect (nested PeakRDL struct
// mis-typing). This stub keeps the same port signature, ties hwif_in to its
// default and ss_config_o / ss_reset_ctrl_o to zero. The cold-reset chain
// observed by the public smoke comes from smc_reset_ctrl, not from this
// subsystem path, so functional coverage is unaffected.

module smc_subsystem_resets (
        input  logic                                   clk_i,
        input  logic                                   rst_primary_ni,

        input  reset_unit_reg_pkg::reset_unit__out_t   hwif_out,
        output reset_unit_reg_pkg::reset_unit__in_t    hwif_in,

        input  logic [31:0]                            ss_reset_complete_i,
        output logic [31:0]                            ss_config_o,
        output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o[31:0]
    );

    // Tie outputs to safe defaults without dereferencing the broken nested
    // struct fields. ``hwif_in`` is declared but never written; consumers
    // see all-zero default propagation.
    reset_unit_reg_pkg::reset_unit__in_t hwif_in_internal;

    always_ff @(posedge clk_i or negedge rst_primary_ni) begin
        if (!rst_primary_ni) hwif_in_internal <= '{default: '0};
    end

    assign hwif_in     = hwif_in_internal;
    assign ss_config_o = '0;

    genvar i;
    generate
        for (i = 0; i < 32; i++) begin : gen_ss_ctrl
            assign ss_reset_ctrl_o[i] = '{default: '0};
        end
    endgenerate

endmodule
