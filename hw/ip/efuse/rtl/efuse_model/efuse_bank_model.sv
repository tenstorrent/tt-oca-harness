// SPDX-License-Identifier: Apache-2.0
// (c) 2026 Tenstorrent USA Inc

//-----------------------------------------------------------------------------
// Example Fuse Bank Model
//
//-----------------------------------------------------------------------------

module efuse_bank_model
# (
    parameter int unsigned NumFuseByteWidth = 12,
    parameter type efuse_apb_req_t = logic,
    parameter type efuse_apb_resp_t = logic
)
(
    // Global Interface
    input logic                   clk_i,
    input logic                   rst_ni,

    // APB Register Interface
    input  efuse_apb_req_t   apb_req_i,
    output efuse_apb_resp_t  apb_resp_o,

    output efuse_bank_reg_pkg::efuse_bank__out_t hwif_out
);

// Bank Macro

efuse_bank_reg u_efuse_bank_reg (
    .clk(clk_i),
    .arst_n(rst_ni),

    // This is the interface to the OTP Bank Macro
    .s_apb_psel(apb_req_i.psel),
    .s_apb_penable(apb_req_i.penable),
    .s_apb_pwrite(apb_req_i.pwrite),
    .s_apb_pprot(apb_req_i.pprot),
    .s_apb_paddr(apb_req_i.paddr[NumFuseByteWidth-1:0]),
    .s_apb_pwdata(apb_req_i.pwdata),
    .s_apb_pstrb(apb_req_i.pstrb),
    .s_apb_pready(apb_resp_o.pready),
    .s_apb_prdata(apb_resp_o.prdata),
    .s_apb_pslverr(apb_resp_o.pslverr),

    .hwif_out(hwif_out)
);

endmodule: efuse_bank_model