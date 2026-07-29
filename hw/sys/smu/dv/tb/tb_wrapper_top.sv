// SPDX-License-Identifier: Apache-2.0
//
// OSS smu_wrapper harness for the native cocotb/PyUVM flow (issue #3357).
// Instantiates the unmodified hw/.bos/wrapper/smu/smu_wrapper.sv.

`timescale 1ps/1fs

module smu_wrapper_uvm_top (
    input  wire logic clk_smu_i,
    input  wire logic clk_ref_i,
    input  wire logic clk_periph_i,
    input  wire logic clk_sep_wdt_i,
    input  wire logic rst_cold_ni,
    input  wire logic powergood_i,
    output logic        dut_present_o,
    output logic        sep_enabled_o,
    output logic        rst_cold_n_o,
    output logic        powergood_o,
    output logic        fuse_sense_done_o,
    output logic        sep_fuse_sense_done_o,
    output logic        sep_reset_n_o,
    output logic [31:0] smc_scratch_0_o,
    output logic        smc_test_pass_o,
    output logic        smc_test_fail_o,
    output logic [31:0] smc_rom_read_count_o,
    output logic [31:0] smc_scratch_write_count_o,
    output logic        sep_trace_valid_o,
    output logic [31:0] sep_pc_o,
    output logic [31:0] sep_inst_count_o,
    output logic [31:0] sep_iccm_write_count_o,
    output logic [31:0] sep_dccm_write_count_o,
    output logic        sep_boot_rom_fetch_seen_o,
    output logic        sep_iccm_fetch_seen_o,
    output logic        sep_first_pc_valid_o,
    output logic [31:0] sep_first_pc_o,
    output logic        fw_done_o,
    output logic        fw_pass_o,
    output logic [7:0]  fw_char_o,
    output logic        fw_char_valid_o,
    output logic [31:0] smu_axi_out_write_count_o,
    output logic [31:0] smu_axi_out_read_count_o,
    output logic [31:0] ext_mailbox_interrupts_o
);

`ifdef SMU_NO_SEP
    localparam int unsigned SEP_ENABLED = 0;
    localparam smu_pkg::smu_cfg_t SMU_CFG = smu_pkg::NoSepCfg;
`else
    localparam int unsigned SEP_ENABLED = 1;
    localparam smu_pkg::smu_cfg_t SMU_CFG = smu_pkg::DefaultCfg;
`endif

    localparam logic [31:0] SMC_TEST_PASS = 32'hACAF_ACA1;
    localparam logic [31:0] SMC_TEST_FAIL = 32'hFFFF_FFFF;
    localparam logic [31:0] SEP_BOOT_ROM_BASE = 32'h1004_0000;
    localparam logic [31:0] SEP_BOOT_ROM_END  = 32'h1005_0000;
    localparam logic [31:0] SEP_ICCM_BASE     = 32'hC000_0000;
    localparam logic [31:0] SEP_ICCM_END      = 32'hC004_0000;

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
    logic       init_mem_done;
    logic       fuse_reset_n_delayed;
    logic [31:0] ext_mailbox_interrupts;

    smu_axi_xbar_pkg::axi_56_64_req_t  smu_axi_in_req;
    smu_axi_xbar_pkg::axi_56_64_resp_t smu_axi_in_resp;
    smu_axi_xbar_pkg::axi_out_req_t     smu_axi_out_req;
    smu_axi_xbar_pkg::axi_out_resp_t    smu_axi_out_resp;
    smc_pkg::smc_axil_32_32_req_t       smc_axil_extension_req;
    smc_pkg::smc_axil_32_32_resp_t      smc_axil_extension_resp;
    logic [31:0]                         smc_scratch_0_q;

    // Walk both TAPs into Test-Logic-Reset with TMS=1 TCK pulses at time
    // zero, as a physical JTAG host would. Verilator two-state simulation
    // initializes the TCK-domain TAP/TDR flops to zero and a TRST edge alone
    // does not reliably re-arm the registered decodes, which leaves the DTP
    // IC_RESET TDR asserting its reset overrides (SEP would be held in
    // reset). Real TCK edges load every TDR default regardless of
    // async-reset edge ordering.
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
    assign GPIO_PAD           = '0;
    assign BP_UNBONDED_GPIO   = '0;
    assign BP_XTRIG_REQ_OUT   = 'z;
    assign BP_XTRIG_REQ_IN    = 'z;
    assign BP_XTRIG_ACK_IN    = 'z;
    assign BP_XTRIG_ACK_OUT   = 'z;

    assign smu_axi_in_req = '0;
    assign dut_present_o  = 1'b1;
    assign sep_enabled_o  = SEP_ENABLED;
    assign smc_scratch_0_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
    assign smc_test_pass_o = smc_scratch_0_o == SMC_TEST_PASS;
    assign smc_test_fail_o = smc_scratch_0_o == SMC_TEST_FAIL;
    assign sep_trace_valid_o =
        u_dut.sep_cpu_trace.trace_rv_i_valid_ip;
    assign sep_pc_o =
        u_dut.sep_cpu_trace.trace_rv_i_address_ip;
    assign sep_reset_n_o = u_dut.sep_reset_n;
    assign ext_mailbox_interrupts_o = ext_mailbox_interrupts;

    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            smc_rom_read_count_o       <= '0;
            smc_scratch_write_count_o  <= '0;
            sep_inst_count_o           <= '0;
            smc_scratch_0_q             <= '0;
        end else begin
            if (u_dut.rom_intf_req.en && !u_dut.rom_intf_req.wmode) begin
                smc_rom_read_count_o <= smc_rom_read_count_o + 32'd1;
            end
            if (smc_scratch_0_o != smc_scratch_0_q) begin
                smc_scratch_write_count_o <= smc_scratch_write_count_o + 32'd1;
                smc_scratch_0_q <= smc_scratch_0_o;
            end
            if (sep_trace_valid_o) begin
                sep_inst_count_o <= sep_inst_count_o + 32'd1;
            end
        end
    end

    // Sticky retired-PC window detectors. The SEP boot-ROM trampoline retires
    // only a couple of instructions right after reset release — typically
    // while the Python sequence is still inside the bring-up settling wait —
    // so the fetch-window evidence must be collected in hardware from the
    // first cycle, not by polling from the sequence loop.
    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_boot_rom_fetch_seen_o <= 1'b0;
            sep_iccm_fetch_seen_o     <= 1'b0;
            sep_first_pc_valid_o      <= 1'b0;
            sep_first_pc_o            <= '0;
        end else if (sep_trace_valid_o) begin
            if (!sep_first_pc_valid_o) begin
                sep_first_pc_valid_o <= 1'b1;
                sep_first_pc_o       <= sep_pc_o;
            end
            if (sep_pc_o >= SEP_BOOT_ROM_BASE && sep_pc_o < SEP_BOOT_ROM_END) begin
                sep_boot_rom_fetch_seen_o <= 1'b1;
            end
            if (sep_pc_o >= SEP_ICCM_BASE && sep_pc_o < SEP_ICCM_END) begin
                sep_iccm_fetch_seen_o <= 1'b1;
            end
        end
    end

    // SEP TCM write activity from the vendor-free sep_tcm_wrapper shim:
    // positive evidence that the SEP LSU stored firmware results into DCCM.
    if (SEP_ENABLED) begin : gen_sep_tcm_probe
        assign sep_iccm_write_count_o = 32'(
            u_dut.gen_sep_ip.u_sep_ip_integration.u_sep_tcm_wrapper.iccm_write_count);
        assign sep_dccm_write_count_o = 32'(
            u_dut.gen_sep_ip.u_sep_ip_integration.u_sep_tcm_wrapper.dccm_write_count);
    end else begin : gen_no_sep_tcm_probe
        assign sep_iccm_write_count_o = '0;
        assign sep_dccm_write_count_o = '0;
    end

    // The SEP boot ROM macro model (prim_rom) has no init-file hook in the
    // OSS integration, so load its memory from the testbench at time zero.
    // The image basename resolves in the per-test run directory, staged from
    // the declared c_build outputs.
    if (SEP_ENABLED) begin : gen_sep_boot_rom_load
        initial begin
            string boot_rom_path = "smu_sep_boot_rom.hex";
            int boot_rom_fd;
            void'($value$plusargs("sep_boot_rom_hex=%s", boot_rom_path));
            boot_rom_fd = $fopen(boot_rom_path, "r");
            if (boot_rom_fd == 0) begin
                $fatal(1, "[smu_wrapper_uvm_top] missing SEP boot-ROM image %s",
                       boot_rom_path);
            end
            $fclose(boot_rom_fd);
            $readmemh(boot_rom_path,
                      u_dut.gen_sep_ip.u_sep_ip_integration.u_sep_boot_rom.mem);
            $display("[smu_wrapper_uvm_top] loaded SEP boot ROM from %s",
                     boot_rom_path);
        end
    end

    tb_smu_axi_responder u_external_axi_responder (
        .clk_i          (clk_smu_i),
        .rst_ni         (rst_cold_n_o),
        .req_i          (smu_axi_out_req),
        .resp_o         (smu_axi_out_resp),
        .write_count_o  (smu_axi_out_write_count_o),
        .read_count_o   (smu_axi_out_read_count_o),
        .fw_done_o,
        .fw_pass_o,
        .fw_char_o,
        .fw_char_valid_o
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
        .clk_i       (clk_smu_i),
        .rst_ni      (rst_cold_n_o),
        .axil_req_i  (smc_axil_extension_req),
        .axil_resp_o (smc_axil_extension_resp)
    );

    smu_wrapper #(
        .Cfg (SMU_CFG),
        .SEP (SEP_ENABLED)
    ) u_dut (
        .ref_clk_vdd_o          (ref_clk_vdd),
        .rst_cold_n              (rst_cold_n_o),
        .BP_REFCLK               (clk_ref_i),
        .BP_RESETN               (rst_cold_ni),
        .BP_POWERGOOD            (powergood_i),
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
        .init_mem_done_o        (init_mem_done),
        .ref_clk_vdd_sys_dfx_i  (clk_ref_i),
        .jtag_bsr_host_scan_ctrl_o(),
        .jtag_bsr_host_scan_in_i(1'b0),
        .jtag_bsr_host_scan_out_o(),
        .jtag_stap_extra_host_tap_ctrl_o(),
        .jtag_stap_extra_host_tdi_i('{default: '0}),
        .jtag_stap_extra_host_tdo_o(),
        .jtag_stap_extra_host_tdo_oen_o(),
        .jtag_stap_host_scan_ctrl_o(),
        .jtag_stap_host_scan_in_i(1'b0),
        .jtag_stap_host_scan_out_o(),
        .jtag_dfd_host_scan_ctrl_o(),
        .jtag_dfd_host_scan_in_i(1'b0),
        .jtag_dfd_host_scan_out_o(),
        .jtag_dft_secure_host_scan_ctrl_o(),
        .jtag_dft_secure_host_scan_in_i(1'b0),
        .jtag_dft_secure_host_scan_out_o(),
        .jtag_dft_host_scan_ctrl_o(),
        .jtag_dft_host_scan_in_i(1'b0),
        .jtag_dft_host_scan_out_o(),
        .jtag_ptap_state_o(),
        .jtag_ptap_inst_decoded_o(),
        .jtag_ic_reset_ext_o(),
        .xtrig_ctm_src_req_o(),
        .xtrig_ctm_src_ack_i('0),
        .xtrig_ctm_dst_req_i('0),
        .xtrig_ctm_dst_ack_o(),
        .xtrig_clk_stop_req_i('0),
        .smu_axi_in_req_i      (smu_axi_in_req),
        .smu_axi_in_resp_o     (smu_axi_in_resp),
        .smu_axi_out_req_o     (smu_axi_out_req),
        .smu_axi_out_resp_i    (smu_axi_out_resp),
        .smc_axil_extension_req_o (smc_axil_extension_req),
        .smc_axil_extension_resp_i(smc_axil_extension_resp),
        .pll_cgm_clk_o         (pll_cgm_clk),
        .pll_awm_clk_o         (pll_awm_clk),
        .pll_cgm_clk_dfx_i     ({2{clk_smu_i}}),
        .pll_awm_clk_dfx_i     ({5{clk_periph_i}}),
        .tile_event_i          ('0),
        .fuse_sense_done_o,
        .fuse_reset_n_delayed_o(fuse_reset_n_delayed),
        .lc_sigint_err_o(),
        .demote_sigint_err_o(),
        .skip_mem_repair_o(),
        .ext_boot_seq_done_i   (1'b1),
        .interrupts_i          ('0),
        .ext_mailbox_interrupt_o(ext_mailbox_interrupts),
        .uart_interrupt_o(),
        .gpio_interrupt_o(),
        .captured_straps_o(),
        .sync_irq_o(),
        .ndmreset_request_i    ('0),
        .ndmreset_process_o(),
        .cfg_flr_pf_active_i   (1'b0),
        .isolate_req_o(),
        .ss_reset_complete_i   ('1),
        .ss_config_o(),
        .ss_reset_ctrl_o(),
        .smc_global_base_addr_o(),
        .smc_region_size_o(),
        .sep_global_base_addr_o(),
        .sep_region_size_o(),
        .telemetry_clk_i       (clk_ref_i),
        .telemetry_reset_n_i   (rst_cold_ni),
        .noc_o_telemetry_atvalid_i(1'b0),
        .noc_o_telemetry_atdata_i ('0),
        .noc_m_telemetry_atvalid_i(1'b0),
        .noc_m_telemetry_atdata_i ('0),
        .noc_n_telemetry_atvalid_i(1'b0),
        .noc_n_telemetry_atdata_i ('0),
        .cat_therm_i           (1'b0),
        .tile_event_i_pvt      ('0),
        .droop_event_i         ('0),
        .powergood_o,
        .timer_count_o(),
        .mem_repair_done_i     (1'b0),
        .mem_repair_success_i  (1'b0),
        .mem_repair_abort_i    (1'b0),
        .mbist_done_i          (1'b0),
        .mbist_pass_i          (1'b0),
        .mbist_abort_i         (1'b0),
        .clk_sep_wdt_i,
        .lcc_demote_state_1_o(),
        .lcc_demote_state_2_o(),
        .secure_tm_o(),
        .sep_fuse_sense_done_o,
        .sep_extintsrc_req_i   ('0)
    );

endmodule : smu_wrapper_uvm_top
