// SPDX-License-Identifier: Apache-2.0
//
// Behavioral, Verilator-safe stub for smc_reset_unit.
//
// The real module instantiates smc_reset_ctrl + smc_cool_reset_wrap +
// smc_subsystem_resets and combines their hwif_in / hwif_out structs. Those
// reset_unit_reg_pkg nested PeakRDL structs trigger a Verilator C++ codegen
// defect. This stub provides a deterministic functional reset chain
// (powergood stretch + cold-reset propagation) without ever touching the
// broken struct fields. All other reset_unit outputs are tied to safe
// defaults.
//
// The cold-reset observables verified by the OSS PyUVM smoke
// (powergood_stable, rst_cold_stable_*, rst_primary_*, rst_wdt_*) come out of
// here with the same post-release semantics as the real RTL.

module smc_reset_unit (
        input  logic                                   clk_ref_i,
        input  logic                                   clk_smc_i,
        input  logic                                   clk_periph_i,

        input  logic                                   powergood_i,
        output logic                                   powergood_stable_o,

        input  logic                                   rst_cold_ni,
        input  logic                                   fuse_reset_ni,

        output logic                                   rst_cold_stable_ref_clk_no,
        output logic                                   rst_cold_stable_smc_clk_no,

        input  smc_pkg::jtag_smc_reset_ctrl_t          jtag_reset_ctrl_i,

        input  smc_pkg::smc_axil_32_32_req_t           reg_axi_lite_req_i,
        output smc_pkg::smc_axil_32_32_resp_t          reg_axi_lite_resp_o,

        input  logic                                   rst_ext_wdt_ni,
        input  logic                                   smc_wdt_first_timeout_i,
        input  logic                                   smc_wdt_second_timeout_i,

        input  logic                                   isolate_req_pin_i,
        input  logic                                   cfg_flr_pf_active_i,
        input  logic                                   rst_cool_ni,
        output logic [31:0]                            isolate_req_o,
        output logic                                   skip_mem_repair_o,
        output logic                                   rst_cool_no,

        input  logic [31:0]                            ss_reset_complete_i,
        output logic [31:0]                            ss_config_o,
        output smc_reset_unit_pkg::reset_ctrl_t        ss_reset_ctrl_o[31:0],

        output logic                                   rst_primary_ref_clk_no,
        output logic                                   rst_primary_smc_clk_no,
        output logic                                   rst_warm_smc_clk_no,
        output logic                                   rst_wdt_smc_clk_no,
        output logic                                   rst_primary_periph_clk_no,

        output logic                                   sync_irq_o,

        input  logic                                   test_en_i,
        input  logic                                   scan_rst_ni,

        input  logic [63:0]                            captured_straps_i
    );

    // Stretch powergood through a 4-stage flop chain so X never makes it to
    // an observer and the stable signal follows powergood deterministically.
    logic [3:0] powergood_stretch_q;
    always_ff @(posedge clk_ref_i) begin
        if (!powergood_i) begin
            powergood_stretch_q <= '0;
        end else begin
            powergood_stretch_q <= {powergood_stretch_q[2:0], 1'b1};
        end
    end
    assign powergood_stable_o = &powergood_stretch_q;

    // Cold-reset stretch through a small flop chain (ref-clk domain).
    logic [3:0] cold_rst_ref_q;
    always_ff @(posedge clk_ref_i) begin
        if (!rst_cold_ni || !powergood_stable_o) begin
            cold_rst_ref_q <= '0;
        end else begin
            cold_rst_ref_q <= {cold_rst_ref_q[2:0], 1'b1};
        end
    end
    assign rst_cold_stable_ref_clk_no = &cold_rst_ref_q;
    assign rst_primary_ref_clk_no     = &cold_rst_ref_q;

    // SMC-clk domain reset stretch.
    logic [3:0] cold_rst_smc_q;
    always_ff @(posedge clk_smc_i) begin
        if (!rst_cold_ni || !powergood_stable_o) begin
            cold_rst_smc_q <= '0;
        end else begin
            cold_rst_smc_q <= {cold_rst_smc_q[2:0], 1'b1};
        end
    end
    assign rst_cold_stable_smc_clk_no = &cold_rst_smc_q;
    assign rst_primary_smc_clk_no     = &cold_rst_smc_q;

    // Pulse warm/WDT reset while smc_wdt_second_timeout_i is high so DV can
    // Force-inject second-stage WDT and clear cold-warm scratch (real RTL path
    // via smc_reset_ctrl). Cold sticky scratch uses rst_cold only and survives.
    logic wdt_warm_n;
    always_ff @(posedge clk_smc_i) begin
        if (!(&cold_rst_smc_q)) begin
            wdt_warm_n <= 1'b0;
        end else if (smc_wdt_second_timeout_i) begin
            wdt_warm_n <= 1'b0;
        end else begin
            wdt_warm_n <= 1'b1;
        end
    end
    assign rst_warm_smc_clk_no = wdt_warm_n;
    assign rst_wdt_smc_clk_no  = wdt_warm_n;

    // Periph-clk reset stretch.
    logic [3:0] cold_rst_periph_q;
    always_ff @(posedge clk_periph_i) begin
        if (!rst_cold_ni || !powergood_stable_o) begin
            cold_rst_periph_q <= '0;
        end else begin
            cold_rst_periph_q <= {cold_rst_periph_q[2:0], 1'b1};
        end
    end
    assign rst_primary_periph_clk_no = &cold_rst_periph_q;

    // Minimal AXI-Lite slave: complete every txn; STRAPS_LO/HI mirror
    // captured_straps_i (offsets 0x90 / 0x94 match reset_unit_reg). Other
    // addresses return 0. Avoid PeakRDL hwif structs (Verilator codegen bug).
    logic        axil_b_valid_q;
    logic        axil_r_valid_q;
    logic [31:0] axil_r_data_q;

    always_ff @(posedge clk_smc_i) begin
        if (!(&cold_rst_smc_q)) begin
            axil_b_valid_q <= 1'b0;
            axil_r_valid_q <= 1'b0;
            axil_r_data_q  <= 32'h0;
        end else begin
            if (axil_b_valid_q && reg_axi_lite_req_i.b_ready) begin
                axil_b_valid_q <= 1'b0;
            end else if (
                reg_axi_lite_req_i.aw_valid && reg_axi_lite_req_i.w_valid &&
                !axil_b_valid_q
            ) begin
                axil_b_valid_q <= 1'b1;
            end

            if (axil_r_valid_q && reg_axi_lite_req_i.r_ready) begin
                axil_r_valid_q <= 1'b0;
            end else if (reg_axi_lite_req_i.ar_valid && !axil_r_valid_q) begin
                axil_r_valid_q <= 1'b1;
                unique case (reg_axi_lite_req_i.ar.addr[7:0])
                    8'h90: axil_r_data_q <= captured_straps_i[31:0];
                    8'h94: axil_r_data_q <= captured_straps_i[63:32];
                    default: axil_r_data_q <= 32'h0;
                endcase
            end
        end
    end

    always_comb begin
        reg_axi_lite_resp_o = '{default: '0};
        reg_axi_lite_resp_o.aw_ready = !axil_b_valid_q;
        reg_axi_lite_resp_o.w_ready  = !axil_b_valid_q;
        reg_axi_lite_resp_o.b_valid  = axil_b_valid_q;
        reg_axi_lite_resp_o.b.resp   = axi_pkg::RESP_OKAY;
        reg_axi_lite_resp_o.ar_ready = !axil_r_valid_q;
        reg_axi_lite_resp_o.r_valid  = axil_r_valid_q;
        reg_axi_lite_resp_o.r.data   = axil_r_data_q;
        reg_axi_lite_resp_o.r.resp   = axi_pkg::RESP_OKAY;
    end

    assign isolate_req_o     = '0;
    assign skip_mem_repair_o = 1'b0;
    assign rst_cool_no       = rst_cool_ni;
    assign ss_config_o       = '0;
    assign sync_irq_o        = 1'b0;

    genvar i;
    generate
        for (i = 0; i < 32; i++) begin : gen_ss_ctrl
            assign ss_reset_ctrl_o[i] = '{default: '0};
        end
    endgenerate

endmodule
