// SPDX-License-Identifier: Apache-2.0
// OSS DV stub override for the FOSS simulator; see gpio_macro_wrapper.sv.
module input_gpio_macro_wrapper
#(
    parameter logic INPUT_BY_DEFAULT = 1'b1,
    parameter logic ENABLE_PULL      = 1'b0,
    parameter logic USE_PULL_UP      = 1'b0,
    parameter logic PAD_ORIENTATION  = 1'b0
) (
    input  wire logic                            clk_i,
    input  wire logic                            rst_primary_ni,
    input  wire logic                            rst_cold_ni,
    input  wire logic                            test_en_i,
`ifdef POWER_PINS
    inout  wire                                  VDD,
    inout  wire                                  VDDO,
    inout  wire                                  VSS,
`endif
    input  wire                                  VSW_vdd_sys,
    input  wire                                  VREFN_vdd_sys,
    input  wire                                  VREFP_vdd_sys,
    input  wire                                  RTN_vdd_sys,
    input  wire                                  SPS_vdd_sys,
    input  wire logic                            core2pad_i,
    input  wire logic                            core2pad_en_i,
    output logic                                 pad2core_o,
    input  wire logic                            pad2core_en_i,
    input  wire logic                            core2pad_ovrd_i,
    input  wire logic                            core2pad_en_ovrd_i,
    output logic                                 pad2core_ovrd_o,
    input  wire logic                            pad2core_en_ovrd_i,
    input  wire logic                            ext_intf_sel_i,
    input  wire logic                            reg_lsio_sel_i,
    input  wire logic                            reg_lsio_disable_i,
    input  wire logic [2:0]                      ext_drive_strength_i,
    input  wire logic                            ext_pull_en_i,
    input  wire logic                            ext_pull_sel_i,
    input  wire logic                            ext_gf_disable_i,
    output logic                                 captured_strap_o,
    input  wire gpio_pkg::gpio_axil_req_t        axil_req_i,
    output gpio_pkg::gpio_axil_resp_t            axil_resp_o,
    input  wire logic                            gpio_nandtree_in_i,
    output logic                                 gpio_nandtree_out_o,
    inout  wire                                  GPIO_PAD
);

    assign pad2core_o = GPIO_PAD;
    assign pad2core_ovrd_o = GPIO_PAD;
    assign captured_strap_o = 1'b0;
    assign gpio_nandtree_out_o = gpio_nandtree_in_i;

    always_comb begin
        axil_resp_o = '0;
        axil_resp_o.aw_ready = 1'b1;
        axil_resp_o.w_ready  = 1'b1;
        axil_resp_o.ar_ready = 1'b1;
        axil_resp_o.b_valid  = axil_req_i.aw_valid & axil_req_i.w_valid;
        axil_resp_o.r_valid  = axil_req_i.ar_valid;
    end

endmodule
