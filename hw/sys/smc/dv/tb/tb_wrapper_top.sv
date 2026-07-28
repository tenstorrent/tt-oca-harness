// SPDX-License-Identifier: Apache-2.0
//
// OSS smc_wrapper harness for the native cocotb/PyUVM flow
// (dv/smc/tb/doc/oss_rtl_imp.md §6). Instantiates
// hw/oss-example/wrapper/smc/smc_wrapper.sv without mutating bare-smc tb_top.

`timescale 1ps/1fs

module smc_wrapper_uvm_top (
    input  wire logic clk_smc_i,
    input  wire logic clk_ref_i,
    input  wire logic clk_periph_i,
    input  wire logic rst_cold_ni,
    input  wire logic powergood_i,
    output logic        dut_present_o,
    output logic        rst_cold_n_o,
    output logic        powergood_o,
    output logic        fuse_sense_done_o,
    output logic        smc_reset_n_o,
    output logic        init_mem_done_o,
    output logic [31:0] smc_scratch_0_o,
    output logic        smc_test_pass_o,
    output logic        smc_test_fail_o,
    output logic [31:0] output_axi_write_count_o,
    output logic [31:0] output_axi_read_count_o
);

    localparam logic [31:0] SMC_TEST_PASS = 32'hACAF_ACA1;
    localparam logic [31:0] SMC_TEST_FAIL = 32'hFFFF_FFFF;

    tri BP_P_TCK;
    tri BP_P_TMS;
    tri BP_P_TRSTN;
    tri BP_P_TDI;
    tri BP_P_TDO;
    tri BP_S_TCK;
    tri BP_S_TMS;
    tri BP_S_TRSTN;
    tri BP_S_TDI;
    tri BP_S_TDO;
    tri BP_FUSE_SMC_VPP;
    tri BP_FUSE_SMC_VREFM;
    tri BP_FUSE_SMC_VTDO;
    tri [smc_pkg::NUM_BONDED_GPIO-1:0] GPIO_PAD;
    tri [smc_pkg::NUM_UNBONDED_GPIO-1:0] BP_UNBONDED_GPIO;
    tri [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0]
        BP_XTRIG_REQ_OUT;
    tri [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0]
        BP_XTRIG_REQ_IN;
    tri [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0]
        BP_XTRIG_ACK_IN;
    tri [smc_ip_integration_pkg::NUM_DEDICATED_XTRIG_INTFS-1:0]
        BP_XTRIG_ACK_OUT;

    logic [1:0] pll_cgm_clk;
    logic [4:0] pll_awm_clk;
    logic       ref_clk_vdd;
    logic       fuse_reset_n_delayed;
    logic [smc_pkg::NUM_MAILBOXES-1:0] ext_mailbox_interrupt;

    smc_pkg::smc_sep_in_56_64_6_12_axi_req_t   sep_axi_in_req;
    smc_pkg::smc_sep_in_56_64_6_12_axi_resp_t  sep_axi_in_resp;
    smc_pkg::smc_sys_in_56_64_6_12_axi_req_t   sys_axi_in_req;
    smc_pkg::smc_sys_in_56_64_6_12_axi_resp_t  sys_axi_in_resp;
    smc_pkg::smc_sys_out_56_64_8_12_axi_req_t  output_axi_req;
    smc_pkg::smc_sys_out_56_64_8_12_axi_resp_t output_axi_resp;
    smc_pkg::smc_axil_32_32_req_t              axil_dtp_csr_req;
    smc_pkg::smc_axil_32_32_resp_t             axil_dtp_csr_resp;
    smc_pkg::smc_jtag_56_64_2_12_axi_req_t     jtag_axi_in_req;
    smc_pkg::smc_jtag_56_64_2_12_axi_resp_t    jtag_axi_in_resp;
    smc_pkg::smc_axil_32_32_req_t              axil_smc_otp_jtag_req;
    smc_pkg::smc_axil_32_32_resp_t             axil_smc_otp_jtag_resp;
    smc_pkg::smc_axil_32_32_req_t              axil_extension_req;
    smc_pkg::smc_axil_32_32_resp_t             axil_extension_resp;

    logic jtag_ptap_tck;
    logic jtag_ptap_tms;
    logic jtag_ptap_trstn;
    logic jtag_ptap_tdi;
    logic jtag_stap_tdi;

    // Walk both TAPs into Test-Logic-Reset with TMS=1 TCK pulses at time zero
    // (same rationale as smu_wrapper_uvm_top).
    logic tb_jtag_tck;
    initial begin
        tb_jtag_tck = 1'b0;
        for (int unsigned i = 0; i < 8; i++) begin
            #5ns tb_jtag_tck = 1'b1;
            #5ns tb_jtag_tck = 1'b0;
        end
    end

    assign BP_P_TCK   = tb_jtag_tck;
    assign BP_P_TMS   = 1'b1;
    assign BP_P_TRSTN = rst_cold_ni;
    assign BP_P_TDI   = 1'b0;
    assign BP_S_TCK   = tb_jtag_tck;
    assign BP_S_TMS   = 1'b1;
    assign BP_S_TRSTN = rst_cold_ni;
    assign BP_S_TDI   = 1'b0;
    assign BP_FUSE_SMC_VPP   = 1'b0;
    assign BP_FUSE_SMC_VREFM = 1'b0;
    assign BP_FUSE_SMC_VTDO  = 1'b0;
    assign GPIO_PAD           = 'z;
    assign BP_UNBONDED_GPIO   = 'z;
    assign BP_XTRIG_REQ_OUT   = 'z;
    assign BP_XTRIG_REQ_IN    = 'z;
    assign BP_XTRIG_ACK_IN    = 'z;
    assign BP_XTRIG_ACK_OUT   = 'z;

    assign sep_axi_in_req        = '0;
    assign sys_axi_in_req        = '0;
    assign jtag_axi_in_req       = '0;
    assign axil_smc_otp_jtag_req = '0;

    assign dut_present_o = 1'b1;
    // oss-example smc_wrapper declares smc_reset_n_o but does not drive it;
    // probe the real primary SMC-clock reset from the integration hierarchy.
    assign smc_reset_n_o = u_dut.rst_primary_smc_clk_n;
    assign smc_scratch_0_o =
        u_dut.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
    assign smc_test_pass_o = smc_scratch_0_o == SMC_TEST_PASS;
    assign smc_test_fail_o = smc_scratch_0_o == SMC_TEST_FAIL;

    tb_smc_output_mem_responder u_output_mem (
        .clk_i          (clk_smc_i),
        .rst_ni         (rst_cold_n_o),
        .axi_req_i      (output_axi_req),
        .axi_resp_o     (output_axi_resp),
        .force_slverr_i (1'b0),
        .write_count_o  (output_axi_write_count_o),
        .read_count_o   (output_axi_read_count_o),
        .last_addr_o    (),
        .last_wdata_o   ()
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (32),
        .AXI_DATA_WIDTH (32),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_DECERR),
        .RESP_WIDTH     (32),
        .RESP_DATA      (32'hDEAD_D700)
    ) u_dtp_err_slv (
        .clk_i       (clk_smc_i),
        .rst_ni      (rst_cold_n_o),
        .axil_req_i  (axil_dtp_csr_req),
        .axil_resp_o (axil_dtp_csr_resp)
    );

    prim_axi_lite_err_slv #(
        .AXI_ADDR_WIDTH (32),
        .AXI_DATA_WIDTH (32),
        .axil_req_t     (smc_pkg::smc_axil_32_32_req_t),
        .axil_resp_t    (smc_pkg::smc_axil_32_32_resp_t),
        .RESP           (axi_pkg::RESP_SLVERR),
        .RESP_WIDTH     (32),
        .RESP_DATA      (32'hBADC_AB1E)
    ) u_extension_err_slv (
        .clk_i       (clk_smc_i),
        .rst_ni      (rst_cold_n_o),
        .axil_req_i  (axil_extension_req),
        .axil_resp_o (axil_extension_resp)
    );

    smc_wrapper u_dut (
        .ref_clk_vdd_o          (ref_clk_vdd),
        .rst_cold_n             (rst_cold_n_o),
        .BP_REFCLK              (clk_ref_i),
        .BP_RESETN              (rst_cold_ni),
        .BP_POWERGOOD           (powergood_i),
        .BP_P_TCK,
        .BP_P_TMS,
        .BP_P_TRSTN,
        .BP_P_TDI,
        .BP_P_TDO,
        .BP_S_TCK,
        .BP_S_TMS,
        .BP_S_TRSTN,
        .BP_S_TDI,
        .BP_S_TDO,
        .BP_XTRIG_REQ_OUT,
        .BP_XTRIG_REQ_IN,
        .BP_XTRIG_ACK_IN,
        .BP_XTRIG_ACK_OUT,
        .GPIO_PAD,
        .BP_UNBONDED_GPIO,
        .BP_FUSE_SMC_VPP,
        .BP_FUSE_SMC_VREFM,
        .BP_FUSE_SMC_VTDO,
        .test_en_i              (1'b0),
        .scan_rst_ni            (1'b1),
        .secure_tm_i            (1'b0),
        .lcc_demote_state_1_i   (2'b10),
        .lcc_demote_state_2_i   (2'b10),
        .init_mem_done_o,
        .sep_axi_in_req_i       (sep_axi_in_req),
        .sep_axi_in_resp_o      (sep_axi_in_resp),
        .sys_axi_in_req_i       (sys_axi_in_req),
        .sys_axi_in_resp_o      (sys_axi_in_resp),
        .output_axi_req_o       (output_axi_req),
        .output_axi_resp_i      (output_axi_resp),
        .axil_dtp_csr_req_o     (axil_dtp_csr_req),
        .axil_dtp_csr_resp_i    (axil_dtp_csr_resp),
        .jtag_axi_in_req_i      (jtag_axi_in_req),
        .jtag_axi_in_resp_o     (jtag_axi_in_resp),
        .axil_smc_otp_jtag_req_i(axil_smc_otp_jtag_req),
        .axil_smc_otp_jtag_resp_o(axil_smc_otp_jtag_resp),
        .axil_extension_req_o   (axil_extension_req),
        .axil_extension_resp_i  (axil_extension_resp),
        .jtag_ptap_tck_o        (jtag_ptap_tck),
        .jtag_ptap_tms_o        (jtag_ptap_tms),
        .jtag_ptap_trstn_o      (jtag_ptap_trstn),
        .jtag_ptap_tdi_o        (jtag_ptap_tdi),
        .jtag_ptap_tdo_i        (1'b0),
        .jtag_stap_tck_i        (1'b0),
        .jtag_stap_tms_i        (1'b0),
        .jtag_stap_trstn_i      (1'b1),
        .jtag_stap_tdi_o        (jtag_stap_tdi),
        .jtag_stap_tdo_i        (1'b0),
        .lc_state_i             ('0),
        .lc_sigint_err_o        (),
        .demote_sigint_err_o    (),
        .feat_ctrl_i            ('0),
        .sep_wdt_reset_n_i      (1'b1),
        .ndmreset_request_i     ('0),
        .ndmreset_process_o     (),
        .fuse_sense_done_o,
        .fuse_reset_n_delayed_o (fuse_reset_n_delayed),
        .boot_stall_jtag_ovrd_i (1'b0),
        .boot_stall_jtag_val_i  (1'b0),
        .boot_stall_combined_o  (),
        .skip_mem_repair_o      (),
        .ext_boot_seq_done_i    (1'b1),
        .sep_security_disable_i (1'b0),
        .interrupts_i           ('0),
        .ext_mailbox_interrupt_o(ext_mailbox_interrupt),
        .captured_straps_o      (),
        .sync_irq_o             (),
        .cla_ext_action_custom_o(),
        .tdr_dbg_ctrl_clock_stop_en_i(1'b0),
        .tdr_dbg_ctrl_clocks_stopped_by_cla_o(),
        .powergood_o,
        .smc_reset_n_o          (),
        .rst_wdt_smc_clk_no     (),
        .sep_cold_reset_n_o     (),
        .sep_debug_reset_n_o    (),
        .sep_warm_reset_n_o     (),
        .ss_reset_ctrl_o        (),
        .ss_reset_complete_i    ('1),
        .ss_config_o            (),
        .smc_global_base_addr_o (),
        .smc_region_size_o      (),
        .telemetry_clk_i        (clk_ref_i),
        .telemetry_reset_n_i    (rst_cold_ni),
        .noc_o_telemetry_atvalid_i(1'b0),
        .noc_o_telemetry_atdata_i ('0),
        .noc_m_telemetry_atvalid_i(1'b0),
        .noc_m_telemetry_atdata_i ('0),
        .noc_n_telemetry_atvalid_i(1'b0),
        .noc_n_telemetry_atdata_i ('0),
        .spi_enable_i           (1'b0),
        .spi_clk_i              (1'b0),
        .spi_txd_i              ('0),
        .spi_cs_n_i             (1'b1),
        .spi_cs_oe_n_i          (1'b1),
        .spi_cs_ie_n_i          (1'b1),
        .spi_clk_ie_n_i         (1'b1),
        .spi_clk_oe_n_i         (1'b1),
        .spi_dqs_ie_n_i         (1'b1),
        .spi_dqs_oe_n_i         (1'b1),
        .spi_dq_ie_n_i          ('1),
        .spi_dq_oe_n_i          ('1),
        .spi_rxd_o              (),
        .spi_rxds_o             (),
        .spi_mem_rebar_oepad_i  (1'b0),
        .spi_mem_rebar_opad_i   (1'b0),
        .spi_mem_rebar_iepad_i  (1'b0),
        .spi_mem_rebar_ipad_o   (),
        .ptp_in_i               ('0),
        .ptp_oe_i               ('0),
        .ptp_out_o              (),
        .cat_therm_i            (1'b0),
        .tile_event_i           ('0),
        .droop_event_i          ('0),
        .isolate_req_o          (),
        .cfg_flr_pf_active_i    (1'b0),
        .pll_cgm_clk_o          (pll_cgm_clk),
        .pll_awm_clk_o          (pll_awm_clk),
        // smc_ip_integration takes clocks from the DFX inputs.
        .pll_cgm_clk_dfx_i      ({2{clk_smc_i}}),
        .pll_awm_clk_dfx_i      ({5{clk_periph_i}}),
        .ref_clk_vdd_sys_dfx_i  (clk_ref_i),
        .xtrigger_ss_o          (),
        .xtrigger_ss_i          ('0),
        .ext_debug_bus_i        ('0),
        .timer_count_o          (),
        .mem_repair_done_i      (1'b0),
        .mem_repair_success_i   (1'b0),
        .mem_repair_abort_i     (1'b0),
        .mbist_done_i           (1'b0),
        .mbist_pass_i           (1'b0),
        .mbist_abort_i          (1'b0),
        .jtag_reset_ctrl_i      ('0),
        .smc_cpu_jtag_TCK_i     (1'b0),
        .smc_cpu_jtag_TMS_i     (1'b0),
        .smc_cpu_jtag_TDI_i     (1'b0),
        .smc_cpu_jtag_TDO_data_o(),
        .smc_cpu_jtag_reset_i   (1'b1),
        .smc_cpu_jtag_mfr_id_i  ('0),
        .smc_cpu_jtag_part_number_i('0),
        .smc_cpu_jtag_version_i ('0),
        .gpio_interrupt_o       (),
        .uart_interrupt_o       ()
    );

endmodule : smc_wrapper_uvm_top
