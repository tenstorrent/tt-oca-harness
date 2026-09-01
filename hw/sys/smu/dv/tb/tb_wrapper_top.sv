// SPDX-License-Identifier: Apache-2.0
//
// OSS smu_wrapper harness for the native cocotb/PyUVM flow (issue #3357).
// Instantiates hw/top/smu_wrapper.sv (logical ports); the CPU memory macros
// come with smc_ip_integration inside it — same OSS composition pattern as
// smc_wrapper / sep_wrapper.

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
    output logic        fuse_reset_n_delayed_o,
    output logic        rst_primary_smc_clk_n_o,
    output logic        init_mem_done_o,
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
    output logic [31:0] ext_mailbox_interrupts_o,
    // SEP run-gate / IFU bring-up probes (keep nets visible under VCS)
    output logic [15:0] sep_cla_custom_o,
    output logic        sep_mpc_reset_run_o,
    output logic        sep_mpc_debug_run_o,
    output logic        sep_cpu_run_req_o,
    output logic        sep_halt_status_o,
    output logic        sep_debug_mode_o,
    output logic [31:0] sep_boot_rom_req_count_o,
    output logic        sep_cpu_rst_ni_o,
    output logic        sep_dbg_rstb_o,
    output logic        sep_mod_rst_ni_o,
    output logic [31:0] sep_cpu_clk_count_o,
    output logic        sep_rungate_at_release_valid_o,
    output logic        sep_mpc_reset_run_at_release_o,
    output logic        sep_mpc_xz_at_release_o,
    output logic [15:0] sep_cla_at_release_o,
    // SMU_ALL_001 compose / clk-domain / lifecycle observe surface
    output logic [7:0]  lc_state_o,
    // Hierarchical SEP lifecycle source (for lc_state=from_sep identity).
    // Under SMU_NO_SEP this is tied off; checkers must not treat that as from_sep.
    output logic [7:0]  obs_sep_lc_state_o,
    // Legacy compile-time present flags — not used by SMU_ALL_001 FAIL-ON path
    // (presence is proven via hierarchical clk/rst identity observes below).
    output logic        obs_compose_smc_present_o,
    output logic        obs_compose_sep_present_o,
    output logic        obs_compose_dtp_present_o,
    output logic        obs_compose_xbar_present_o,
    output logic        obs_dtp_clk_o,
    output logic        obs_smc_clk_o,
    output logic        obs_sep_clk_o,
    output logic        obs_xbar_clk_o,
    output logic        obs_dtp_rst_n_o,
    output logic        obs_smc_rst_n_o,
    output logic        obs_sep_rst_n_o,
    output logic        obs_xbar_rst_n_o,
    output logic        obs_smc_tel_clk_o,
    output logic        obs_sep_wdt_clk_o,
    output logic        obs_jtag_tdo_o,
    output logic        obs_smu_axi_awready_o,
    output logic        obs_xtrig_src_req0_o
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

    // ------------------------------------------------------------------
    // TB glue: clocks / JTAG / AXI / GPIO / CPU mem / observability
    // ------------------------------------------------------------------

    logic tb_jtag_tck;
    prim_jtag_pkg::jtag_tap_ctrl_t jtag_ptap_client_tap_ctrl;
    logic jtag_ptap_tdi;
    logic jtag_ptap_tdo;
    logic jtag_ptap_tdo_oen;

    // Walk PTAP into Test-Logic-Reset with TMS=1 TCK pulses. Verilator
    // two-state and VCS X-init both leave the DTP IC_RESET TDR in a state that
    // can assert SMC cold/fuse overrides (rst_primary never releases → no
    // fuse_sense_done → CPU never fetches). Pulse at time zero, then again
    // after TRST (rst_cold_ni) rises so TDR defaults reload with a real
    // TRST→TCK sequence.
    initial begin
        tb_jtag_tck = 1'b0;
        for (int unsigned i = 0; i < 8; i++) begin
            #5ns tb_jtag_tck = 1'b1;
            #5ns tb_jtag_tck = 1'b0;
        end
        wait (rst_cold_ni === 1'b0);
        wait (rst_cold_ni === 1'b1);
        for (int unsigned i = 0; i < 16; i++) begin
            #5ns tb_jtag_tck = 1'b1;
            #5ns tb_jtag_tck = 1'b0;
        end
    end

    assign jtag_ptap_client_tap_ctrl = '{
        tms: 1'b1,
        trst_n: rst_cold_ni,
        tck: tb_jtag_tck
    };
    assign jtag_ptap_tdi = 1'b0;

    smu_axi_xbar_pkg::axi_56_64_req_t  smu_axi_in_req;
    smu_axi_xbar_pkg::axi_56_64_resp_t smu_axi_in_resp;
    smu_axi_xbar_pkg::axi_out_req_t     smu_axi_out_req;
    smu_axi_xbar_pkg::axi_out_resp_t    smu_axi_out_resp;
    logic [7:0] lc_state;
    // Matches smu_wrapper XTRIG_NUM_INT_CT (= DEFAULT_NUM_INT_CT - 2).
    logic [dtp_pkg::DEFAULT_NUM_INT_CT-3:0] xtrig_ctm_src_req;

    // CPU memory macros are inside smc_ip_integration now, so the ROM request
    // is observed hierarchically instead of on a wrapper passthrough port.
    chipyard_4core_mem_pkg::rom_req_t            rom_intf_req;
    assign rom_intf_req = u_dut.u_smc_ip_integration.rom_intf_req;

    wire [smc_pkg::NUM_GPIO_WRAPS-1:0] gpio_pad_io;
    logic [31:0] ext_mailbox_interrupts;
    logic [31:0] smc_scratch_0_q;
    logic        rst_cold_stable_ref_clk_n;
    logic        rst_primary_smc_clk_n;
    logic        sep_reset_n;
    sep_pkg::sep_cpu_trace_t sep_cpu_trace;
    sep_pkg::sep_straps_t    sep_straps;

    trace_mem_pkg::SinkMemPktIn_s
        [tn_pkg::TRC_RAM_INSTANCES-1:0] trc_req;
    trace_mem_pkg::SinkMemPktOut_s
        [tn_pkg::TRC_RAM_INSTANCES-1:0] trc_resp;
    assign trc_resp = '0;

    i3c_pkg::dat_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dat_src;
    i3c_pkg::dct_mem_src_t  [smc_config_pkg::NUM_I3C-1:0] i3c_dct_src;
    assign i3c_dat_src = '0;
    assign i3c_dct_src = '0;

    assign sep_straps = '0;
    assign smu_axi_in_req = '0;

    // Cocotb observe ports that hw/top/smu_wrapper does not expose directly.
    assign dut_present_o = 1'b1;
    assign sep_enabled_o = SEP_ENABLED;
    assign powergood_o   = powergood_i;
    assign rst_cold_n_o  = rst_cold_stable_ref_clk_n;
    assign rst_primary_smc_clk_n_o = rst_primary_smc_clk_n;
`ifndef SMU_NO_SEP
    assign sep_reset_n = u_dut.u_smu.gen_sep.u_sep.sep_reset_n;
`else
    assign sep_reset_n = 1'b1;
`endif
    assign sep_reset_n_o = sep_reset_n;
    assign ext_mailbox_interrupts_o = ext_mailbox_interrupts;
    assign lc_state_o = lc_state;
    assign obs_jtag_tdo_o = jtag_ptap_tdo;
    assign obs_smu_axi_awready_o = smu_axi_in_resp.aw_ready;
    assign obs_xtrig_src_req0_o = xtrig_ctm_src_req[0];

    // Compose presence + shared-domain mirrors (hierarchical passive observe).
    // SMC/DTP always elaborate; SEP/xbar only under SEP=1 generate.
    assign obs_compose_smc_present_o = 1'b1;
    assign obs_compose_dtp_present_o = 1'b1;
    assign obs_smc_clk_o = u_dut.u_smu.u_smc.clk_smc_i;
    assign obs_dtp_clk_o = u_dut.u_smu.u_dtp.clk_i;
    assign obs_smc_rst_n_o = u_dut.u_smu.u_smc.rst_primary_smc_clk_no;
    assign obs_dtp_rst_n_o = u_dut.u_smu.u_dtp.rst_n_i;
    assign obs_smc_tel_clk_o = u_dut.u_smu.u_smc.clk_telemetry_i;

`ifndef SMU_NO_SEP
    assign obs_compose_sep_present_o = 1'b1;
    assign obs_compose_xbar_present_o = 1'b1;
    assign obs_sep_clk_o = u_dut.u_smu.gen_sep.u_sep.clk_i;
    assign obs_xbar_clk_o = u_dut.u_smu.gen_sep.u_smu_axi_xbar.clk_i;
    assign obs_sep_rst_n_o = u_dut.u_smu.gen_sep.u_sep.rst_ni;
    assign obs_xbar_rst_n_o = u_dut.u_smu.gen_sep.u_smu_axi_xbar.rst_ni;
    assign obs_sep_wdt_clk_o = u_dut.u_smu.gen_sep.u_sep.clk_wdt_i;
    // Live SEP LCC export — must match lc_state_o for lc_state=from_sep.
    assign obs_sep_lc_state_o = u_dut.u_smu.gen_sep.u_sep.lc_state_o;
`else
    assign obs_compose_sep_present_o = 1'b0;
    assign obs_compose_xbar_present_o = 1'b0;
    assign obs_sep_clk_o = 1'b0;
    assign obs_xbar_clk_o = 1'b0;
    assign obs_sep_rst_n_o = 1'b0;
    assign obs_xbar_rst_n_o = 1'b0;
    assign obs_sep_wdt_clk_o = 1'b0;
    assign obs_sep_lc_state_o = 8'h00;
`endif

    assign smc_scratch_0_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
    assign smc_test_pass_o = smc_scratch_0_o == SMC_TEST_PASS;
    assign smc_test_fail_o = smc_scratch_0_o == SMC_TEST_FAIL;

    // Mask SEP trace while the CPU is in reset: VCS leaves the EL2 trace
    // struct at X and cocotb read_int() rejects X/Z.
    assign sep_trace_valid_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_valid_ip : 1'b0;
    assign sep_pc_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_address_ip : '0;

    // Observe SEP run-gate nets. Use ifdef (not generate-if) so the no-SEP
    // compile never resolves gen_sep hierarchy XMRs.
`ifndef SMU_NO_SEP
    assign sep_cla_custom_o =
        16'(u_dut.u_smu.cla_ext_action_custom);
    assign sep_mpc_reset_run_o =
        u_dut.u_smu.gen_sep.u_sep.mpc_reset_run_req;
    assign sep_mpc_debug_run_o =
        u_dut.u_smu.gen_sep.u_sep.mpc_debug_run_req;
    assign sep_cpu_run_req_o =
        u_dut.u_smu.gen_sep.u_sep.i_cpu_run_req;
    assign sep_halt_status_o =
        u_dut.u_smu.gen_sep.u_sep.o_cpu_halt_status;
    assign sep_debug_mode_o =
        u_dut.u_smu.gen_sep.u_sep.o_debug_mode_status;
    assign sep_cpu_rst_ni_o =
        u_dut.u_smu.gen_sep.u_sep.sep_cpu.rst_ni;
    assign sep_dbg_rstb_o =
        u_dut.u_smu.gen_sep.u_sep.dbg_rstb_i;
    assign sep_mod_rst_ni_o =
        u_dut.u_smu.gen_sep.u_sep.rst_ni;

    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_boot_rom_req_count_o <= '0;
        end else if (u_dut.sep_boot_rom_req.req) begin
            sep_boot_rom_req_count_o <= sep_boot_rom_req_count_o + 32'd1;
        end
    end

    always_ff @(posedge u_dut.u_smu.gen_sep.u_sep.sep_cpu.clk_i or negedge
                rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_cpu_clk_count_o <= '0;
        end else begin
            sep_cpu_clk_count_o <= sep_cpu_clk_count_o + 32'd1;
        end
    end

    // Capture run-gate at the SEP CPU reset 0->1 edge (EL2 samples then).
    logic sep_cpu_rst_ni_q;
    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_cpu_rst_ni_q               <= 1'b0;
            sep_rungate_at_release_valid_o <= 1'b0;
            sep_mpc_reset_run_at_release_o <= 1'b0;
            sep_mpc_xz_at_release_o        <= 1'b0;
            sep_cla_at_release_o           <= '0;
        end else begin
            if (!sep_cpu_rst_ni_q && sep_cpu_rst_ni_o) begin
                sep_rungate_at_release_valid_o <= 1'b1;
                sep_mpc_reset_run_at_release_o <= (sep_mpc_reset_run_o === 1'b1);
                sep_mpc_xz_at_release_o        <= $isunknown(sep_mpc_reset_run_o);
                sep_cla_at_release_o           <= sep_cla_custom_o;
            end
            sep_cpu_rst_ni_q <= sep_cpu_rst_ni_o;
        end
    end
`else
    assign sep_cla_custom_o         = '0;
    assign sep_mpc_reset_run_o      = 1'b0;
    assign sep_mpc_debug_run_o      = 1'b0;
    assign sep_cpu_run_req_o        = 1'b0;
    assign sep_halt_status_o        = 1'b0;
    assign sep_debug_mode_o         = 1'b0;
    assign sep_boot_rom_req_count_o = '0;
    assign sep_cpu_rst_ni_o         = 1'b0;
    assign sep_dbg_rstb_o           = 1'b0;
    assign sep_mod_rst_ni_o         = 1'b0;
    assign sep_cpu_clk_count_o      = '0;
    assign sep_rungate_at_release_valid_o = 1'b0;
    assign sep_mpc_reset_run_at_release_o = 1'b0;
    assign sep_mpc_xz_at_release_o        = 1'b0;
    assign sep_cla_at_release_o           = '0;
`endif

    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            smc_rom_read_count_o      <= '0;
            smc_scratch_write_count_o <= '0;
            sep_inst_count_o          <= '0;
            smc_scratch_0_q           <= '0;
        end else begin
            if (rom_intf_req.en && !rom_intf_req.wmode) begin
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

    // SEP TCM write-count probes deferred (DV sep_tcm_wrapper shim removed).
    assign sep_iccm_write_count_o = '0;
    assign sep_dccm_write_count_o = '0;

`ifndef SMU_NO_SEP
    // The SEP boot ROM macro model (prim_rom) has no init-file hook in the
    // OSS integration, so load its memory from the testbench at time zero.
    string boot_rom_path;
    int    boot_rom_fd;
    initial begin
        boot_rom_path = "smu_sep_boot_rom.hex";
        void'($value$plusargs("sep_boot_rom_hex=%s", boot_rom_path));
        boot_rom_fd = $fopen(boot_rom_path, "r");
        if (boot_rom_fd == 0) begin
            $fatal(1, "[smu_wrapper_uvm_top] missing SEP boot-ROM image %s",
                   boot_rom_path);
        end
        $fclose(boot_rom_fd);
        $readmemh(boot_rom_path,
                  u_dut.u_sep_ip_integration.u_sep_boot_rom.mem);
        $display("[smu_wrapper_uvm_top] loaded SEP boot ROM from %s",
                 boot_rom_path);
    end
`endif

    // ------------------------------------------------------------------
    // External SMN AXI slave — SEP rom_boot / SMC SYS_OUT posture:
    // pulp axi_sim_mem on the boundary (no custom DV mem module, no Force).
    // Firmware console / PASS magic is a TB observe snoop on the same wires
    // (SEP sep_outbound_mbx decode), not a second bus terminator.
    // ------------------------------------------------------------------
    localparam logic [31:0] FW_STDOUT_ADDR = 32'h8000_0000;
    localparam logic [31:0] FW_MAGIC0      = 32'hA5A5_5A5A;
    localparam logic [31:0] FW_MAGIC_PASS  = 32'hCAFE_BABE;
    localparam logic [31:0] FW_MAGIC_FAIL  = 32'hDEAD_BEEF;

    smu_axi_xbar_pkg::axi_out_req_t  [0:0] axi_out_mem_req;
    smu_axi_xbar_pkg::axi_out_resp_t [0:0] axi_out_mem_resp;

    assign axi_out_mem_req[0] = smu_axi_out_req;
    assign smu_axi_out_resp   = axi_out_mem_resp[0];

    // smu_clk floor is 8ns (env_cfg); keep ApplDelay < AcqDelay < 8ns.
    axi_sim_mem #(
        .AddrWidth         (56),
        .DataWidth         (64),
        .IdWidth           (10),
        .UserWidth         (12),
        .NumPorts          (1),
        .axi_req_t         (smu_axi_xbar_pkg::axi_out_req_t),
        .axi_rsp_t         (smu_axi_xbar_pkg::axi_out_resp_t),
        .WarnUninitialized (1'b0),
        .UninitializedData ("zeros"),
        .ClearErrOnAccess  (1'b1),
        .ApplDelay         (1ns),
        .AcqDelay          (3ns)
    ) u_axi_out_mem (
        .clk_i     (clk_smu_i),
        .rst_ni    (rst_cold_n_o),
        .axi_req_i (axi_out_mem_req),
        .axi_rsp_o (axi_out_mem_resp)
    );

    logic [55:0] axi_out_aw_addr_q;
    logic        fw_magic0_seen_q;

    wire axi_out_aw_fire =
        smu_axi_out_req.aw_valid & smu_axi_out_resp.aw_ready;
    wire axi_out_w_fire =
        smu_axi_out_req.w_valid & smu_axi_out_resp.w_ready;
    wire axi_out_b_fire =
        smu_axi_out_resp.b_valid & smu_axi_out_req.b_ready;
    wire axi_out_r_last_fire =
        smu_axi_out_resp.r_valid & smu_axi_out_req.r_ready &
        smu_axi_out_resp.r.last;
    // Same-cycle AW+W: prefer live AW addr (SEP mbx cur_awaddr style).
    wire [55:0] axi_out_cur_awaddr =
        axi_out_aw_fire ? smu_axi_out_req.aw.addr : axi_out_aw_addr_q;
    wire axi_out_to_stdout =
        (axi_out_cur_awaddr[31:0] == FW_STDOUT_ADDR);
    wire [31:0] axi_out_fw_word =
        (smu_axi_out_req.w.strb[7:4] != 4'h0)
            ? smu_axi_out_req.w.data[63:32]
            : smu_axi_out_req.w.data[31:0];

    always_ff @(posedge clk_smu_i or negedge rst_cold_n_o) begin
        if (!rst_cold_n_o) begin
            axi_out_aw_addr_q         <= '0;
            smu_axi_out_write_count_o <= '0;
            smu_axi_out_read_count_o  <= '0;
            fw_done_o                 <= 1'b0;
            fw_pass_o                 <= 1'b0;
            fw_char_o                 <= '0;
            fw_char_valid_o           <= 1'b0;
            fw_magic0_seen_q          <= 1'b0;
        end else begin
            fw_char_valid_o <= 1'b0;

            if (axi_out_aw_fire) begin
                axi_out_aw_addr_q <= smu_axi_out_req.aw.addr;
            end
            if (axi_out_b_fire) begin
                smu_axi_out_write_count_o <=
                    smu_axi_out_write_count_o + 32'd1;
            end
            if (axi_out_r_last_fire) begin
                smu_axi_out_read_count_o <=
                    smu_axi_out_read_count_o + 32'd1;
            end

            // Firmware console / PASS magic (retired tb_smu_axi_responder /
            // SEP sep_outbound_mbx decode) — observe only, axi_sim_mem owns resp.
            if (axi_out_w_fire && axi_out_to_stdout) begin
                if (smu_axi_out_req.w.strb == 8'h01) begin
                    fw_char_o       <= smu_axi_out_req.w.data[7:0];
                    fw_char_valid_o <= 1'b1;
                end
                if (smu_axi_out_req.w.strb == 8'h0F ||
                        smu_axi_out_req.w.strb == 8'hF0) begin
                    if (!fw_magic0_seen_q) begin
                        fw_magic0_seen_q <= (axi_out_fw_word == FW_MAGIC0);
                    end else if (axi_out_fw_word == FW_MAGIC_PASS) begin
                        fw_done_o        <= 1'b1;
                        fw_pass_o        <= 1'b1;
                        fw_magic0_seen_q <= 1'b0;
                    end else if (axi_out_fw_word == FW_MAGIC_FAIL) begin
                        fw_done_o        <= 1'b1;
                        fw_pass_o        <= 1'b0;
                        fw_magic0_seen_q <= 1'b0;
                    end else if (axi_out_fw_word != FW_MAGIC0) begin
                        fw_magic0_seen_q <= 1'b0;
                    end
                end
            end
        end
    end

    // CPU ROM/scratch/L1$ macros (same module smc_wrapper embeds).

    // ------------------------------------------------------------------
    // DUT: hw/top/smu_wrapper (logical ports)
    // ------------------------------------------------------------------
    smu_wrapper #(
        .Cfg (SMU_CFG),
        .SEP (SEP_ENABLED[0])
    ) u_dut (
        .clk_smu_i,
        .clk_ref_i,
        .clk_periph_i,
        .rst_cold_ni,
        .rst_cold_stable_ref_clk_no (rst_cold_stable_ref_clk_n),
        .powergood_i,

        .jtag_ptap_client_tap_ctrl_i (jtag_ptap_client_tap_ctrl),
        .jtag_ptap_client_tdi_i      (jtag_ptap_tdi),
        .jtag_ptap_client_tdo_o      (jtag_ptap_tdo),
        .jtag_ptap_client_tdo_oen_o  (jtag_ptap_tdo_oen),

        .jtag_bsr_host_scan_ctrl_o (),
        .jtag_bsr_host_scan_in_i   (1'b0),
        .jtag_bsr_host_scan_out_o  (),

        .jtag_stap_io_host_tap_ctrl_o (),
        .jtag_stap_io_host_tdi_i      (1'b0),
        .jtag_stap_io_host_tdo_o      (),
        .jtag_stap_io_host_tdo_oen_o  (),

        .jtag_stap_extra_host_tap_ctrl_o (),
        .jtag_stap_extra_host_tdi_i      ('{default: '0}),
        .jtag_stap_extra_host_tdo_o      (),
        .jtag_stap_extra_host_tdo_oen_o  (),

        .jtag_stap_host_scan_ctrl_o (),
        .jtag_stap_host_scan_in_i   (1'b0),
        .jtag_stap_host_scan_out_o  (),

        .jtag_dfd_host_scan_ctrl_o (),
        .jtag_dfd_host_scan_in_i   (1'b0),
        .jtag_dfd_host_scan_out_o  (),

        .jtag_dft_secure_host_scan_ctrl_o (),
        .jtag_dft_secure_host_scan_in_i   (1'b0),
        .jtag_dft_secure_host_scan_out_o  (),

        .jtag_dft_host_scan_ctrl_o (),
        .jtag_dft_host_scan_in_i   (1'b0),
        .jtag_dft_host_scan_out_o  (),

        .dtp_stop_clks_o (),
        .jtag_ptap_state_o (),
        .jtag_ptap_inst_decoded_o (),
        .jtag_ic_reset_ext_o (),

        .xtrig_ctm_src_req_o (xtrig_ctm_src_req),
        .xtrig_ctm_src_ack_i ('0),
        .xtrig_ctm_dst_req_i ('0),
        .xtrig_ctm_dst_ack_o (),
        .xtrig_clk_stop_req_i ('0),

        .xtrig_ctp_req_out_dout_o (),
        .xtrig_ctp_req_out_dout_en_o (),
        .xtrig_ctp_req_out_din_i ('0),
        .xtrig_ctp_req_out_din_en_o (),
        .xtrig_ctp_req_in_dout_o (),
        .xtrig_ctp_req_in_dout_en_o (),
        .xtrig_ctp_req_in_din_i ('0),
        .xtrig_ctp_req_in_din_en_o (),
        .xtrig_ctp_ack_in_dout_o (),
        .xtrig_ctp_ack_in_dout_en_o (),
        .xtrig_ctp_ack_in_din_i ('0),
        .xtrig_ctp_ack_in_din_en_o (),
        .xtrig_ctp_ack_out_dout_o (),
        .xtrig_ctp_ack_out_dout_en_o (),
        .xtrig_ctp_ack_out_din_i ('0),
        .xtrig_ctp_ack_out_din_en_o (),

        .rst_primary_ref_clk_no (),
        .rst_primary_smc_clk_no (rst_primary_smc_clk_n),

        .smu_axi_in_req_i  (smu_axi_in_req),
        .smu_axi_in_resp_o (smu_axi_in_resp),
        .smu_axi_out_req_o (smu_axi_out_req),
        .smu_axi_out_resp_i (smu_axi_out_resp),

        .smc_shadow_regs_o (),
        .lsio_interface_select_o (),
        .gpio_pad_io (gpio_pad_io),
        .rst_cool_n_from_pin_i (1'b1),

        .clk_telemetry_i (clk_ref_i),
        .rst_telemetry_ni (rst_cold_ni),
        .telemetry_atdata_i ('0),
        .telemetry_atid_i ('0),
        .telemetry_atready_o (),
        .telemetry_atvalid_i ('0),
        .telemetry_afvalid_o (),
        .telemetry_afready_i ('0),

        .cluster_ded_o (),
        .wdt_first_timeout_o (),
        .wdt_second_timeout_o (),

        .smc_global_base_o (),
        .smc_region_size_o (),
        .sep_global_base_o (),
        .sep_region_size_o (),

        .ext_interrupts_i ('0),
        .fuse_sense_done_o,
        .fuse_reset_n_delayed_o,
        .skip_mem_repair_o (),
        .ext_boot_seq_done_i (1'b1),
        .temp_interrupt_i (1'b0),
        .lc_state_o (lc_state),
        .lc_sigint_err_o (),
        .ras_bank_chip_o (),
        .ras_bank_instance_o (),
        .ndmreset_request_i ('0),
        .ndmreset_process_o (),
        .ext_mailbox_interrupts_o (ext_mailbox_interrupts),

        .cfg_flr_pf_active_i (1'b0),
        .isolate_req_o (),
        .ss_reset_complete_i ('1),
        .ss_config_o (),
        .ss_reset_ctrl_o (),
        .sync_irq_o (),

        .disable_sram_auto_init_i (1'b0),
        .init_mem_done_o,
        .chiplet_is_primary_i (1'b1),
        .timer_count_o (),
        .trace_mem_req_o (trc_req),
        .trace_mem_resp_i (trc_resp),

        .test_en_i (1'b0),
        .scan_rst_ni (1'b1),
        .captured_straps_i ('0),

        // Without an external BISR/MBIST agent the boot sequencer waits forever
        // if these stay low (CPU never fetches ROM).
        .mem_repair_done_i (1'b1),
        .mem_repair_success_i (1'b1),
        .mem_repair_abort_i (1'b0),
        .mbist_done_i (1'b1),
        .mbist_pass_i (1'b1),
        .mbist_abort_i (1'b0),

        .spi_irq_i (1'b0),
        .sep_cpu_trace_o (sep_cpu_trace),
        .sep_extintsrc_req_i ('0),
        .lcc_demote_state_1_o (),
        .lcc_demote_state_2_o (),
        .sep_fuse_sense_done_o,
        .clk_sep_wdt_i,
        .sep_straps_i (sep_straps),

        .i3c_dat_mem_src_i (i3c_dat_src),
        .i3c_dat_mem_sink_o (),
        .i3c_dct_mem_src_i (i3c_dct_src),
        .i3c_dct_mem_sink_o (),

        .ext_debug_bus_i ('0),
        .gpio_interrupt_o (),
        .uart_interrupt_o (),
        .sep_efuse_debug_bus_o (),
        .smc_efuse_debug_bus_o ()
    );

endmodule : smu_wrapper_uvm_top
