// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for smc_cool_reset_wrap.
//
// The real wrap module uses reset_unit_reg_pkg::reset_unit__in_t / __out_t
// types which trigger a Verilator C++ codegen defect. This stub presents the
// same port signature and ties the FLR outputs to neutral values. The
// cold-reset observable path (powergood_stable / rst_primary_*) is not
// affected because it originates from smc_reset_ctrl, not this wrap.

module smc_cool_reset_wrap (
        input  logic                                   clk_ref_i,
        input  logic                                   rst_cold_ref_ni,

        input  logic                                   clk_smc_i,
        input  logic                                   rst_cold_smc_ni,

        input  reset_unit_reg_pkg::reset_unit__out_t   hwif_out,
        output reset_unit_reg_pkg::reset_unit__in_t    hwif_in,

        input  logic                                   isolate_req_pin_i,
        input  logic                                   cfg_flr_pf_active_i,
        input  logic                                   rst_cool_ni,
        output logic [31:0]                            isolate_req_o,
        output logic                                   skip_mem_repair_o,
        output logic                                   rst_cool_no
    );

    reset_unit_reg_pkg::reset_unit__in_t hwif_in_internal;

    always_ff @(posedge clk_ref_i or negedge rst_cold_ref_ni) begin
        if (!rst_cold_ref_ni) hwif_in_internal <= '{default: '0};
    end

    assign hwif_in            = hwif_in_internal;
    assign isolate_req_o      = '0;
    assign skip_mem_repair_o  = 1'b0;
    assign rst_cool_no        = rst_cool_ni;  // pass-through

endmodule
