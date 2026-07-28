// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for the SMC DFX control status wrap.
//
// The real wrapper (hw/smc/smc_misc/rtl/smc_dfx_ctrl_status_wrap.sv) uses
// dfx_ctrl_status_reg_pkg::dfx_ctrl_status__in_t, whose nested PeakRDL struct
// (STATUS_SMU) triggers a Verilator 5.046 C++ codegen defect:
//   Vtop_dfx_ctrl_status___STATUS___in_t__struct__0 has no non-static data
//   member named __PVT__STATUS_SMU
// This stub keeps the same module port signature, ties the AXI-Lite response
// to always-ready / never-respond, and drives all DFD config outputs to safe
// defaults, without ever referencing the broken struct type. The DFX/DFD path
// is observation-only on the public smoke, so functional coverage is
// unaffected.
//
// Selected ahead of the real RTL via Verilator -Wno-MODDUP "first definition
// wins" by listing this file in [build].stubs. The module/file name must match
// the real module (smc_dfx_ctrl_status_wrap) or the override does not bind.

module smc_dfx_ctrl_status_wrap
    (
        input  logic                                clk_i,
        input  logic                                rst_ni,

        // AXI-Lite interface to DFX CSR
        input  smc_pkg::smc_axil_32_64_req_t        axil_dfx_csr_req_i,
        output smc_pkg::smc_axil_32_64_resp_t       axil_dfx_csr_resp_o,

        // indicators for DFT status (ignored by the stub)
        input  logic                                mem_repair_done_i,
        input  logic                                mem_repair_success_i,
        input  logic                                mem_repair_abort_i,
        input  logic                                mbist_done_i,
        input  logic                                mbist_pass_i,
        input  logic                                mbist_abort_i,

        // DFD config (DEBUG_CTRL / DEBUG_BUS_MUX) — tied off by the stub
        output logic [dfd_cla_pkg::XTRIGGER_WIDTH-1:0] debug_chiplet_enable_o,
        output smc_pkg::dfd_enable_t                dfd_enables_o,
        output dfd_tt_dbm_pkg::DbgMuxSelCsr_s       dbg_mux_sel_csr_o
    );

    // Drive the AXI-Lite response as always-ready / never-respond. This avoids
    // referencing the broken PeakRDL nested struct types.
    always_comb begin
        axil_dfx_csr_resp_o = '{default: '0};
        axil_dfx_csr_resp_o.aw_ready = 1'b1;
        axil_dfx_csr_resp_o.w_ready  = 1'b1;
        axil_dfx_csr_resp_o.ar_ready = 1'b1;
    end

    // DFD config outputs default to disabled/zero.
    assign debug_chiplet_enable_o = '0;
    assign dfd_enables_o          = '{default: '0};
    assign dbg_mux_sel_csr_o      = '{default: '0};

endmodule
