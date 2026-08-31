// SPDX-License-Identifier: Apache-2.0
//
// OSS smu_wrapper harness for the native cocotb/PyUVM flow (issue #3357).
// Instantiates hw/top/smu_wrapper.sv (logical ports); the CPU memory macros
// come with smc_ip_integration inside it — same OSS composition pattern as
// smc_wrapper / sep_wrapper.

`timescale 1ps/1fs

module smu_wrapper_uvm_top (
    input  wire logic clk_smu_i,
    // Primary JTAG TAP, driven from cocotb exactly as the bare `--dut smu`
    // harness drives it (tb/tb_top.sv), so OcahJtagMasterDriver works against
    // either DUT. Previously this TB pulsed TCK internally with TMS tied high;
    // that walk now lives in the base test, which every wrapper test runs.
    input  wire logic jtag_tck,
    input  wire logic jtag_tms,
    input  wire logic jtag_trst,   // active-low
    input  wire logic jtag_tdi,
    // ESRC raw noise, driven from cocotb. Mirrors hw/sys/sep/dv/tb/tb_top.sv.
    input  wire logic [11:0] esrc_noise_ext_i,
    output logic [11:0]      esrc_noise_o,        // the driven 12-lane stimulus
    output logic             esrc_noise_active_o, // lane-0 actual dcor.noise_i
    // Entropy datapath observation taps. Read-only, never driven -- the same
    // nets hw/sys/sep/dv/tb/tb_top.sv watches. These are how a test tells
    // "the stack was programmed" from "entropy actually flowed".
    output logic             drbg_seed_valid_o,
    output logic             drbg_es_ack_o,
    output logic             drbg_genbits_vld_o,
    // Sticky versions. These are pulses; latching them in hardware means a test
    // can poll every few thousand cycles instead of sampling every edge from
    // Python, which is both far faster and cannot miss a one-cycle event.
    output logic             drbg_seed_valid_seen_o,
    output logic             drbg_es_ack_seen_o,
    output logic             drbg_genbits_seen_o,
    output logic             esrc_noise_took_o,
    output logic      jtag_tdo,
    output logic      jtag_tdo_oen,
    // IC_RESET override bits as the SMC and SEP reset controllers see them.
    // Every wrapper test depends on these being clear -- an asserted override
    // holds cold/fuse reset and the SEP never fetches -- but until now that was
    // an assumption the TB made and nothing checked.
    output logic [67:0] ic_reset_smc_ovrd_o,
    output logic        ic_reset_sep_ovrd_any_o,
    // SEP lifecycle-controller fan-out. The LCC decides the chiplet's posture
    // and three different consumers act on it, but until now only lc_state_o
    // was sampled -- and only once, statically, at the SMU boundary. These make
    // the other two legs observable so a test can prove the posture actually
    // reaches DTP and SMC rather than merely existing on a port.
    output logic [1:0]  lcc_demote_state_1_o,
    output logic [1:0]  lcc_demote_state_2_o,
    output logic [63:0] lcc_feat_ctrl_o,
    output logic [15:0] lcc_dbg_disable_o,     // to DTP
    output logic [7:0]  smc_lc_state_in_o,     // as SMC receives it
    // DTP JTAG2AXI traffic into the SMC. dbg_disable.smc_jtag2axi stops the
    // bridge from launching a transaction at all (jtag2axi.sv: the update is
    // gated by `!security_disable_i`), so counting AW/AR here is how a test
    // tells "debug is gated" from "the signal merely says so".
    output logic [31:0] dtp_smc_dbg_aw_count_o,
    output logic [31:0] dtp_smc_dbg_ar_count_o,
    input  wire logic clk_ref_i,
    input  wire logic clk_periph_i,
    input  wire logic clk_sep_wdt_i,
    // ESRC ring-oscillator sample clock. A separate, faster clock than clk_smu:
    // the entropy source samples its noise lanes on this one, so with it static
    // the ESRC produces nothing no matter how the stack is programmed. The SEP
    // DV testbench drives it at 3 ns.
    input  wire logic entropy_rosc_sample_clk_i,
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
    // From the bound smc_cpu_mem_dv: whether the SMC core is actually fetching
    // and writing scratch RAM. Separates "the ROM never handed over" from
    // "control reached the scratch image and it faulted".
    // SMC CPU_CTRL scratch6/7/10: the ext_axi protocol's SMC-side READY, GO and
    // PASS. Reading them here is diagnosis only -- the master reads the same
    // registers through the aperture, which is the path under test.
    output logic [31:0] smc_scratch_6_o,
    output logic [31:0] smc_scratch_7_o,
    output logic [31:0] smc_scratch_10_o,
    output logic [31:0] smc_scratch_read_count_o,
    output logic [31:0] smc_scratch_write_count_dv_o,
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
    // Sticky per-stage bitmap of the SEP DV firmware STAGE_BEACON words
    // (0xB1B0B0B_<stage>) seen on the STDOUT mailbox. Bit N = stage N reached.
    output logic [15:0] fw_beacon_mask_o,
    output logic [31:0] fw_last_word_o,
    // SEP outbound (SMN) path observation. Separates "the SEP never issued the
    // write" from "the SMU crossbar did not route it to ext_out", which are the
    // two ways a firmware mailbox handshake goes silent.
    output logic [31:0] sep_smn_out_aw_count_o,
    output logic [55:0] sep_xbar_global_base_o,
    output logic [31:0] sep_xbar_region_size_o,
    // Crossbar -> SEP inbound AW. Separates "the crossbar never routed the
    // transaction to the SEP" from "it arrived and the SEP inbound filter
    // dropped it", which look identical from the firmware's side.
    output logic [31:0] sep_xbar_in_aw_count_o,
    // AWUSER of the last crossbar->SEP write. The SEP inbound filter matches
    // src_id/group_id out of this field (axi_filter_wrap.sv:159), so a window
    // that looks correctly programmed still drops traffic whose user field
    // carries a different source id.
    output logic [11:0] sep_xbar_in_aw_user_o,
    output logic [55:0] sep_xbar_in_aw_addr_o,
    // SEP AP / STEE output-remap region-0 offsets, as the remap datapath sees
    // them. sep_smu_remap programs these write-only and cannot read them back,
    // so the golden comparison has to happen here.
    output logic [55:0] sep_ap_remap_offset0_o,
    output logic [55:0] sep_stee_remap_offset0_o,
    // AP output-remap CSR path, split at the two stages unique to this branch:
    // the second-level 16-way demux inside sep_system_csr, and the generated
    // register block behind it. Everything upstream is shared with the filter
    // and scratch CSRs, which are known good.
    output logic [31:0] sep_ap_csr_aw_count_o,   // reaches the AP_OUTPUT_REMAP demux
    output logic [31:0] sep_ap_reg0_aw_count_o,  // reaches region 0's register block
    output logic [31:0] sep_csr_aw_count_o,      // reaches sep_system_csr at all
    output logic [55:0] sep_csr_last_aw_addr_o,  // ...and with what address
    output logic [31:0] sep_csr_errslv_aw_count_o, // ...or was classified ERR_SLV
    output logic [31:0] smu_axi_out_write_count_o,
    output logic [31:0] smu_axi_out_read_count_o,
    // Outbound-boundary handshake split: write_count only moves on B, so it
    // cannot separate a stalled write from one the crossbar never routed here.
    // aw_valid says the beat was presented at the boundary; aw_ready says the
    // boundary slave accepted it.
    // ext_in AXI master pins, named for cocotbext.axi AxiBus.from_prefix
    // (prefix "ext_in"). Driven by the cocotb master; see the assigns below.
    input  wire logic        ext_in_awvalid,
    output logic             ext_in_awready,
    input  wire logic [7:0]  ext_in_awid,
    input  wire logic [55:0] ext_in_awaddr,
    input  wire logic [7:0]  ext_in_awlen,
    input  wire logic [2:0]  ext_in_awsize,
    input  wire logic [1:0]  ext_in_awburst,
    input  wire logic [11:0] ext_in_awuser,
    input  wire logic        ext_in_wvalid,
    output logic             ext_in_wready,
    input  wire logic [63:0] ext_in_wdata,
    input  wire logic [7:0]  ext_in_wstrb,
    input  wire logic        ext_in_wlast,
    output logic             ext_in_bvalid,
    input  wire logic        ext_in_bready,
    output logic [7:0]       ext_in_bid,
    output logic [1:0]       ext_in_bresp,
    input  wire logic        ext_in_arvalid,
    output logic             ext_in_arready,
    input  wire logic [7:0]  ext_in_arid,
    input  wire logic [55:0] ext_in_araddr,
    input  wire logic [7:0]  ext_in_arlen,
    input  wire logic [2:0]  ext_in_arsize,
    input  wire logic [1:0]  ext_in_arburst,
    input  wire logic [11:0] ext_in_aruser,
    output logic             ext_in_rvalid,
    input  wire logic        ext_in_rready,
    output logic [7:0]       ext_in_rid,
    output logic [63:0]      ext_in_rdata,
    output logic [1:0]       ext_in_rresp,
    output logic             ext_in_rlast,
    output logic        smu_axi_out_aw_valid_seen_o,
    output logic        smu_axi_out_aw_fired_seen_o,
    output logic [55:0] smu_axi_out_first_aw_addr_o,
    output logic        smu_axi_out_w_valid_seen_o,
    output logic        smu_axi_out_w_fired_seen_o,
    output logic        smu_axi_out_w_last_seen_o,
    output logic        smu_axi_out_b_valid_seen_o,
    // First AW's control fields, latched. A beat whose length or size is X is
    // accepted on the address channel and then stalls, which the B counter
    // alone cannot tell apart from a beat that never arrived.
    output logic [7:0]  smu_axi_out_first_aw_len_o,
    output logic [2:0]  smu_axi_out_first_aw_size_o,
    output logic [1:0]  smu_axi_out_first_aw_burst_o,
    output logic [9:0]  smu_axi_out_first_aw_id_o,
    output logic        smu_axi_out_first_aw_ctrl_x_o,
    output logic [15:0] smu_axi_out_aw_valid_cycles_o,
    output logic [15:0] smu_axi_out_aw_ready_cycles_o,
    output logic [15:0] smu_axi_out_w_valid_cycles_o,
    output logic [15:0] smu_axi_out_w_ready_cycles_o,
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

    prim_jtag_pkg::jtag_tap_ctrl_t jtag_ptap_client_tap_ctrl;
    logic jtag_ptap_tdi;
    logic jtag_ptap_tdo;
    logic jtag_ptap_tdo_oen;

    // The DTP IC_RESET TDR powers up in a state that can assert SMC cold/fuse
    // overrides under Verilator two-state and VCS X-init, which would hold the
    // SEP in reset. Clearing it needs a real TRST->TCK walk into
    // Test-Logic-Reset; smu_base_test.jtag_tap_reset() does that at time zero
    // and again after TRST rises.
    assign jtag_ptap_client_tap_ctrl = '{
        tms: jtag_tms,
        trst_n: jtag_trst,
        tck: jtag_tck
    };
    assign jtag_ptap_tdi = jtag_tdi;
`ifndef SMU_NO_SEP
    assign lcc_demote_state_1_o = u_dut.u_smu.lcc_demote_state_1_o;
    assign lcc_demote_state_2_o = u_dut.u_smu.lcc_demote_state_2_o;
    assign lcc_feat_ctrl_o      = 64'(u_dut.u_smu.gen_sep.u_sep.sep_crypto.u_sep_lifecycle_ctrl.feat_ctrl_o);
    assign lcc_dbg_disable_o    = 16'(u_dut.u_smu.sep_dbg_disable);
    assign smc_lc_state_in_o    = 8'(u_dut.u_smu.sep_lc_state);
`else
    assign lcc_demote_state_1_o = '0;
    assign lcc_demote_state_2_o = '0;
    assign lcc_feat_ctrl_o      = '0;
    assign lcc_dbg_disable_o    = '0;
    assign smc_lc_state_in_o    = '0;
`endif

    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            dtp_smc_dbg_aw_count_o <= '0;
            dtp_smc_dbg_ar_count_o <= '0;
        end else begin
            if (u_dut.u_smu.dtp_axi_smc_dbg_req.aw_valid &&
                u_dut.u_smu.dtp_axi_smc_dbg_resp.aw_ready) begin
                dtp_smc_dbg_aw_count_o <= dtp_smc_dbg_aw_count_o + 32'd1;
            end
            if (u_dut.u_smu.dtp_axi_smc_dbg_req.ar_valid &&
                u_dut.u_smu.dtp_axi_smc_dbg_resp.ar_ready) begin
                dtp_smc_dbg_ar_count_o <= dtp_smc_dbg_ar_count_o + 32'd1;
            end
        end
    end

    // ------------------------------------------------------------------
    // ESRC raw-noise force.
    // ------------------------------------------------------------------
    // POLICY EXCEPTION. This DV root's rule is "no DUT Force" (see README), and
    // this is the single named exception, adopted deliberately to match
    // hw/sys/sep/dv/tb/tb_top.sv, which calls the same thing "the one permitted
    // force (raw noise at the source)".
    //
    // Why it is not a way around the logic under test: the ESRC ring
    // oscillators rely on `#delay` feedback, which Verilator ignores, so the 12
    // noise lanes never toggle and no entropy is produced at all. The force
    // replaces an analogue behaviour the simulator cannot model, at the very
    // first node of the chain. Everything downstream -- decorrelator,
    // compressor, SHA, CSRNG, EDN -- is the real RTL doing real work on the
    // driven sequence. Nothing downstream is forced; the probes are read-only.
    //
    // Scope of the exception, and nothing beyond it:
    //   * only under +esrc_noise_force,
    //   * only dcor.noise_i on the 12 generator lanes,
    //   * downstream taps observe, never drive.
    // Note the SEP TB also carries a +sep_crypto_edn_force that grants OTBN's
    // EDN handshakes directly and bypasses the chain. That one is NOT adopted
    // here: it would skip the logic these tests exist to exercise.
`ifndef SMU_NO_SEP
    logic [11:0] esrc_noise_d;
    assign esrc_noise_d = esrc_noise_ext_i;
    assign esrc_noise_o = esrc_noise_d;
    // Lane 0's ACTUAL noise_i. With the force active this tracks the driven bit;
    // without it, it is whatever the RTL leaves there. A test compares the two so
    // "entropy flowed" cannot pass on a force that silently failed to take.
    assign esrc_noise_active_o = u_dut.u_smu.gen_sep.u_sep.sep_crypto
        .u_entropy_source_s3c_scan.u_generator_complex.g_ecmplx[0].u_generator
        .u_decorrelator.noise_i;

    // Force the decorrelator INPUT PORT -- the exact node the SR flop samples.
    // Re-issued every clock: a `force` inside an `initial` snapshots its RHS once
    // at t=0 under Verilator and would hold that stale value. Explicit per-lane
    // indices because a genvar-indexed cross-hierarchy force is not allowed.
`define SMU_ESRC_NOISE_FORCE(i)                                                \
    force u_dut.u_smu.gen_sep.u_sep.sep_crypto.u_entropy_source_s3c_scan       \
        .u_generator_complex.g_ecmplx[i].u_generator.u_decorrelator.noise_i =  \
        esrc_noise_d[i]
    // Plain `always`: `force` is a procedural continuous override, so always_ff
    // semantics do not apply. No `release` is needed -- the force is plusarg
    // gated and each test is its own elaboration.
    always @(posedge clk_smu_i) begin
        if ($test$plusargs("esrc_noise_force")) begin
            `SMU_ESRC_NOISE_FORCE(0);  `SMU_ESRC_NOISE_FORCE(1);
            `SMU_ESRC_NOISE_FORCE(2);  `SMU_ESRC_NOISE_FORCE(3);
            `SMU_ESRC_NOISE_FORCE(4);  `SMU_ESRC_NOISE_FORCE(5);
            `SMU_ESRC_NOISE_FORCE(6);  `SMU_ESRC_NOISE_FORCE(7);
            `SMU_ESRC_NOISE_FORCE(8);  `SMU_ESRC_NOISE_FORCE(9);
            `SMU_ESRC_NOISE_FORCE(10); `SMU_ESRC_NOISE_FORCE(11);
        end
    end
`undef SMU_ESRC_NOISE_FORCE
`else
    assign esrc_noise_o        = '0;
    assign esrc_noise_active_o = 1'b0;
`endif

`ifndef SMU_NO_SEP
    assign drbg_seed_valid_o = u_dut.u_smu.gen_sep.u_sep.sep_crypto
        .u_drbg_s3c_scan.u_csrng_seed_adapter.seed_queue_valid_o;
    assign drbg_es_ack_o = u_dut.u_smu.gen_sep.u_sep.sep_crypto
        .u_drbg_s3c_scan.u_csrng.entropy_src_hw_if_i.es_ack;
    assign drbg_genbits_vld_o = u_dut.u_smu.gen_sep.u_sep.sep_crypto
        .u_drbg_s3c_scan.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_vld_o;
    // Sticky capture. esrc_noise_took requires a driven 1 that the DUT node
    // actually shows: a match on 0 would also hold with the force absent.
    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            drbg_seed_valid_seen_o <= 1'b0;
            drbg_es_ack_seen_o     <= 1'b0;
            drbg_genbits_seen_o    <= 1'b0;
            esrc_noise_took_o      <= 1'b0;
        end else begin
            if (drbg_seed_valid_o)  drbg_seed_valid_seen_o <= 1'b1;
            if (drbg_es_ack_o)      drbg_es_ack_seen_o     <= 1'b1;
            if (drbg_genbits_vld_o) drbg_genbits_seen_o    <= 1'b1;
            if (esrc_noise_o[0] && esrc_noise_active_o) esrc_noise_took_o <= 1'b1;
        end
    end
`else
    assign drbg_seed_valid_o  = 1'b0;
    assign drbg_es_ack_o      = 1'b0;
    assign drbg_genbits_vld_o = 1'b0;
    assign drbg_seed_valid_seen_o = 1'b0;
    assign drbg_es_ack_seen_o     = 1'b0;
    assign drbg_genbits_seen_o    = 1'b0;
    assign esrc_noise_took_o      = 1'b0;
`endif

    assign ic_reset_smc_ovrd_o = 68'(u_dut.u_smu.jtag_smc_reset_ctrl.ovrd);
`ifndef SMU_NO_SEP
    assign ic_reset_sep_ovrd_any_o = |u_dut.u_smu.jtag_sep_reset_ctrl.ovrd;
`else
    assign ic_reset_sep_ovrd_any_o = 1'b0;
`endif

    assign jtag_tdo      = jtag_ptap_tdo;
    assign jtag_tdo_oen  = jtag_ptap_tdo_oen;

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
    assign smc_scratch_read_count_o =
        u_dut.u_smc_ip_integration.u_smc_cpu_mem_dv.scratch_ram_read_count_q;
    assign smc_scratch_write_count_dv_o =
        u_dut.u_smc_ip_integration.u_smc_cpu_mem_dv.scratch_ram_write_count_q;

    // DV hooks for those absorbed memories: the ROM/scratch image backdoors,
    // the access counters and the firmware mailbox. hw/sys/smc/dv binds the
    // same module into smc_ip_integration (tb_top.sv); without this bind the
    // wrapper environment has none of those hooks.
    //
    // The port expressions are elaborated in smc_ip_integration's scope, so
    // they name that module's own signals, not anything here. ECC injection is
    // tied off: no test in this environment drives it.
    bind smc_ip_integration smc_cpu_mem_dv u_smc_cpu_mem_dv (
        .clk_i                (clk_smc_i),
        .rst_ni               (rst_primary_smc_clk_ni),
        .rom_req_i            (rom_intf_req),
        .scratch_ram_req_i    (scratch_ram_intf_req),
        .l1_dcache_data_req_i (l1_dcache_data_intf_req),
        .ecc_inject_sbe_i     (1'b0),
        .ecc_inject_dbe_i     (1'b0)
    );

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
    // ------------------------------------------------------------------
    // ext_in AXI master surface.
    //
    // These flat ports let a cocotb AXI master act as the external master on
    // the sys-inbound path. The names are what cocotbext.axi's
    // AxiBus.from_prefix expects, so the shared OcahAxiMasterDriver binds
    // straight onto them with no per-signal wiring in the sequence.
    //
    // Everything the crossbar does not consume is tied to its AXI reset value
    // here rather than exposed, so a sequence cannot accidentally drive a
    // meaningless field. Bursts are supported (len/size/burst are real ports)
    // because the ext_axi protocol's route legs are single-beat but its DECERR
    // leg is easier to reason about with the full channel present.
    assign smu_axi_in_req.aw.id     = ext_in_awid;
    assign smu_axi_in_req.aw.addr   = ext_in_awaddr;
    assign smu_axi_in_req.aw.len    = ext_in_awlen;
    assign smu_axi_in_req.aw.size   = ext_in_awsize;
    assign smu_axi_in_req.aw.burst  = ext_in_awburst;
    assign smu_axi_in_req.aw.lock   = 1'b0;
    assign smu_axi_in_req.aw.cache  = '0;
    assign smu_axi_in_req.aw.prot   = '0;
    assign smu_axi_in_req.aw.qos    = '0;
    assign smu_axi_in_req.aw.region = '0;
    assign smu_axi_in_req.aw.atop   = '0;
    assign smu_axi_in_req.aw.user   = ext_in_awuser;
    assign smu_axi_in_req.aw_valid  = ext_in_awvalid;

    assign smu_axi_in_req.w.data    = ext_in_wdata;
    assign smu_axi_in_req.w.strb    = ext_in_wstrb;
    assign smu_axi_in_req.w.last    = ext_in_wlast;
    assign smu_axi_in_req.w.user    = '0;
    assign smu_axi_in_req.w_valid   = ext_in_wvalid;

    assign smu_axi_in_req.b_ready   = ext_in_bready;

    assign smu_axi_in_req.ar.id     = ext_in_arid;
    assign smu_axi_in_req.ar.addr   = ext_in_araddr;
    assign smu_axi_in_req.ar.len    = ext_in_arlen;
    assign smu_axi_in_req.ar.size   = ext_in_arsize;
    assign smu_axi_in_req.ar.burst  = ext_in_arburst;
    assign smu_axi_in_req.ar.lock   = 1'b0;
    assign smu_axi_in_req.ar.cache  = '0;
    assign smu_axi_in_req.ar.prot   = '0;
    assign smu_axi_in_req.ar.qos    = '0;
    assign smu_axi_in_req.ar.region = '0;
    assign smu_axi_in_req.ar.user   = ext_in_aruser;
    assign smu_axi_in_req.ar_valid  = ext_in_arvalid;

    assign smu_axi_in_req.r_ready   = ext_in_rready;

    assign ext_in_awready = smu_axi_in_resp.aw_ready;
    assign ext_in_wready  = smu_axi_in_resp.w_ready;
    assign ext_in_bid     = smu_axi_in_resp.b.id;
    assign ext_in_bresp   = smu_axi_in_resp.b.resp;
    assign ext_in_bvalid  = smu_axi_in_resp.b_valid;
    assign ext_in_arready = smu_axi_in_resp.ar_ready;
    assign ext_in_rid     = smu_axi_in_resp.r.id;
    assign ext_in_rdata   = smu_axi_in_resp.r.data;
    assign ext_in_rresp   = smu_axi_in_resp.r.resp;
    assign ext_in_rlast   = smu_axi_in_resp.r.last;
    assign ext_in_rvalid  = smu_axi_in_resp.r_valid;

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
    assign smc_scratch_6_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[6];
    assign smc_scratch_7_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[7];
    assign smc_scratch_10_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[10];
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

`ifndef SMU_NO_SEP
    // ------------------------------------------------------------------
    // SEP ICCM/DCCM backdoor: time-zero image load + write-count evidence.
    //
    // hw/sys/sep/rtl/sep_tcm_wrapper.sv instantiates the upstream VeeR
    // `ram_<depth>x39` models (vendor/chipsalliance/Cores-VeeR-EL2/upstream/
    // design/lib/mem_lib.sv, already on the smu_wrapper Bender closure). Those
    // macros have no init-file hook, so the firmware images named by
    // +sep_itcm_hex / +sep_dtcm_hex are loaded here at time zero — the same
    // backdoor pattern the SEP DV TB uses (hw/sys/sep/dv/tb/tb_top.sv
    // `BD_ICCM/`BD_DCCM), against the same `ram.ram_core` arrays.
    //
    // Geometry is fixed by the SEP EL2 config and matches fw/common/sep_tcm.ld:
    //   ICCM 256 KiB @ 0xC000_0000 = 4 banks x 16384 rows x 39b
    //   DCCM 128 KiB @ 0xC004_0000 = 2 banks x 16384 rows x 39b
    // Byte offset -> {bank, row} interleave follows the macro address wiring:
    //   ICCM bank = offset[3:2], row = offset[17:4]
    //   DCCM bank = offset[2],   row = offset[16:3]
    // ------------------------------------------------------------------
    localparam int unsigned SEP_ICCM_BYTES = 262144;  // 256 KiB
    localparam int unsigned SEP_DCCM_BYTES = 131072;  // 128 KiB

`define SEP_BD_ICCM(b) \
    u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.gen_iccm.gen_bank[b].gen_iccm_ram.ram.ram_core
`define SEP_BD_DCCM(b) \
    u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.gen_dccm.gen_bank[b].gen_dccm_ram.ram.ram_core

    logic [7:0] sep_itcm_buf [SEP_ICCM_BYTES];
    logic [7:0] sep_dtcm_buf [SEP_DCCM_BYTES];

    // RISC-V SECDED (Hsiao) ECC over a 32-bit word — the EL2 TCM encoding.
    // Identical to bd_riscv_ecc32() in hw/sys/sep/dv/tb/tb_top.sv.
    function automatic logic [6:0] sep_tcm_ecc32(input logic [31:0] data);
        logic [6:0] synd;
        synd[0] = ^(data & 32'h56aa_ad5b);
        synd[1] = ^(data & 32'h9b33_366d);
        synd[2] = ^(data & 32'he3c3_c78e);
        synd[3] = ^(data & 32'h03fc_07f0);
        synd[4] = ^(data & 32'h03ff_f800);
        synd[5] = ^(data & 32'hfc00_0000);
        synd[6] = ^{data, synd[5:0]};
        return synd;
    endfunction

    string sep_itcm_path;
    string sep_dtcm_path;
    logic  sep_tcm_load_q;

    // Resolve the image names and fire the load trigger at time zero. A missing
    // image is fatal here: booting a zeroed TCM would otherwise surface as an
    // opaque "SEP retired no instructions" timeout instead of a setup error.
    initial begin
        int fd;
        bit no_tcm_preload;
        sep_tcm_load_q = 1'b0;
        sep_itcm_path  = "smu_sep_smoke.itcm.hex";
        sep_dtcm_path  = "smu_sep_smoke.dtcm.hex";
        // +sep_no_tcm_preload selects the boot-ROM-only flow, where the image
        // running from ROM loads the TCM itself (secure DMA) instead of being
        // placed there by this loader. Opt-in on purpose: for every other test a
        // missing TCM image stays fatal, because silently booting a zeroed ICCM
        // is exactly the failure this loader exists to prevent.
        no_tcm_preload = $test$plusargs("sep_no_tcm_preload") != 0;
        if (no_tcm_preload) begin
            $display("[smu_wrapper_uvm_top] +sep_no_tcm_preload: TCM zeroed, firmware loads it");
        end
        void'($value$plusargs("sep_itcm_hex=%s", sep_itcm_path));
        void'($value$plusargs("sep_dtcm_hex=%s", sep_dtcm_path));
        // With no preload the loader still runs: it zeroes every TCM row so the
        // EL2 reads ECC-valid words instead of X out of memory the firmware has
        // not written yet. Only the image read is skipped.
        if (!no_tcm_preload) begin
            fd = $fopen(sep_itcm_path, "r");
            if (fd == 0) begin
                $fatal(1, "[smu_wrapper_uvm_top] missing SEP ICCM image %s",
                       sep_itcm_path);
            end
            $fclose(fd);
            fd = $fopen(sep_dtcm_path, "r");
            if (fd == 0) begin
                $fatal(1, "[smu_wrapper_uvm_top] missing SEP DCCM image %s",
                       sep_dtcm_path);
            end
            $fclose(fd);
        end
        #0;  // still time zero, long before cocotb starts the clocks
        sep_tcm_load_q = 1'b1;
    end

    // De-interleave the byte images into the EL2 bank/row layout with per-word
    // Hsiao ECC. Byte buffers are pre-zeroed so every row is written (imaged or
    // an architectural zero word) rather than left X. Bank indices stay constant
    // (`case`) because gen_bank[] is a generate index. Kept in an `always` block,
    // not an `initial`: a constant-bound ~100k-row sweep inside an `initial`
    // unrolls into an uncompilable C++ function under Verilator — same reason
    // hw/sys/sep/dv/tb/tb_top.sv runs its TCM backdoor on a load trigger.
    always @(posedge sep_tcm_load_q) begin : sep_tcm_backdoor_load
        int          off;
        logic [31:0] w;
        logic [38:0] fw;
        for (int i = 0; i < SEP_ICCM_BYTES; i++) sep_itcm_buf[i] = 8'h00;
        if (!$test$plusargs("sep_no_tcm_preload")) begin
            $readmemh(sep_itcm_path, sep_itcm_buf);
        end
        for (off = 0; off + 3 < SEP_ICCM_BYTES; off += 4) begin
            w  = {sep_itcm_buf[off+3], sep_itcm_buf[off+2],
                  sep_itcm_buf[off+1], sep_itcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {sep_tcm_ecc32(w), w};
            case (off[3:2])
                2'd0: `SEP_BD_ICCM(0)[off[17:4]] = fw;
                2'd1: `SEP_BD_ICCM(1)[off[17:4]] = fw;
                2'd2: `SEP_BD_ICCM(2)[off[17:4]] = fw;
                2'd3: `SEP_BD_ICCM(3)[off[17:4]] = fw;
            endcase
        end
        for (int i = 0; i < SEP_DCCM_BYTES; i++) sep_dtcm_buf[i] = 8'h00;
        if (!$test$plusargs("sep_no_tcm_preload")) begin
            $readmemh(sep_dtcm_path, sep_dtcm_buf);
        end
        for (off = 0; off + 3 < SEP_DCCM_BYTES; off += 4) begin
            w  = {sep_dtcm_buf[off+3], sep_dtcm_buf[off+2],
                  sep_dtcm_buf[off+1], sep_dtcm_buf[off]};
            fw = (w == 32'h0) ? '0 : {sep_tcm_ecc32(w), w};
            if (off[2]) `SEP_BD_DCCM(1)[off[16:3]] = fw;
            else        `SEP_BD_DCCM(0)[off[16:3]] = fw;
        end
        if ($test$plusargs("sep_no_tcm_preload")) begin
            $display("[smu_wrapper_uvm_top] SEP TCM zeroed, no image preloaded");
        end else begin
            $display("[smu_wrapper_uvm_top] loaded SEP ICCM from %s, DCCM from %s",
                     sep_itcm_path, sep_dtcm_path);
        end
    end

    // Write-count evidence. The upstream macros carry no counters, so count
    // qualified bank writes at the sep_tcm_wrapper request port using the same
    // {clken & wren} qualification the macro applies to ME/WE
    // (mem_lib.sv: `if (ME && WE) ram_core[ADR] <= D`).
    wire       sep_tcm_clk = u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.tcm_req_i.clk;
    wire [3:0] sep_iccm_wr = u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.tcm_req_i.iccm_clken &
                             u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.tcm_req_i.iccm_wren_bank;
    wire [1:0] sep_dccm_wr = u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.tcm_req_i.dccm_clken &
                             u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.tcm_req_i.dccm_wren_bank;

    // Banks write independently in the same cycle, so accumulate the per-cycle
    // bank count — a per-bank `+ 1` would collapse to at most one per cycle.
    always_ff @(posedge sep_tcm_clk or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_iccm_write_count_o <= '0;
            sep_dccm_write_count_o <= '0;
        end else begin
            sep_iccm_write_count_o <= sep_iccm_write_count_o + 32'($countones(sep_iccm_wr));
            sep_dccm_write_count_o <= sep_dccm_write_count_o + 32'($countones(sep_dccm_wr));
        end
    end
    // The crossbar gives ext_out no address rule -- it is the catch-all for
    // whatever the SEP/SMC aperture rules do not claim (smu_axi_xbar.sv:90) --
    // so the apertures are what decide whether an outbound firmware mailbox
    // write leaves the SMU or is swallowed back into sep_in.
    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_ap_csr_aw_count_o  <= '0;
            sep_ap_reg0_aw_count_o <= '0;
            sep_csr_aw_count_o     <= '0;
            sep_csr_last_aw_addr_o <= '0;
            sep_csr_errslv_aw_count_o <= '0;
        end else begin
            if (u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_reqs[sep_pkg::AP_OUTPUT_REMAP].aw_valid) begin
                sep_ap_csr_aw_count_o <= sep_ap_csr_aw_count_o + 32'd1;
            end
            if (u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_sep_system_csr
                    .ap_output_remap_reqs[0].aw_valid) begin
                sep_ap_reg0_aw_count_o <= sep_ap_reg0_aw_count_o + 32'd1;
            end
            if (u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_req_i.aw_valid) begin
                sep_csr_aw_count_o     <= sep_csr_aw_count_o + 32'd1;
                sep_csr_last_aw_addr_o <= 56'(u_dut.u_smu.gen_sep.u_sep
                    .sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_req_i.aw.addr);
            end
            if (u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_reqs[sep_pkg::ERR_SLV].aw_valid) begin
                sep_csr_errslv_aw_count_o <= sep_csr_errslv_aw_count_o + 32'd1;
            end
        end
    end

    assign sep_ap_remap_offset0_o =
        u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_ap_remap.remap_table[0].offset;
    assign sep_stee_remap_offset0_o =
        u_dut.u_smu.gen_sep.u_sep.sep_system_peripherals.u_stee_remap.remap_table[0].offset;

    assign sep_xbar_global_base_o = u_dut.u_smu.sep_global_base_o;
    assign sep_xbar_region_size_o = u_dut.u_smu.sep_region_size_o[31:0];

    always_ff @(posedge clk_smu_i or negedge rst_cold_ni) begin
        if (!rst_cold_ni) begin
            sep_smn_out_aw_count_o <= '0;
            sep_xbar_in_aw_count_o <= '0;
            sep_xbar_in_aw_user_o  <= '0;
            sep_xbar_in_aw_addr_o  <= '0;
        end else begin
            if (u_dut.u_smu.gen_sep.sep_out_xbar_req.aw_valid &&
                u_dut.u_smu.gen_sep.sep_out_xbar_resp.aw_ready) begin
                sep_smn_out_aw_count_o <= sep_smn_out_aw_count_o + 32'd1;
            end
            if (u_dut.u_smu.xbar_to_sep_req.aw_valid &&
                u_dut.u_smu.xbar_to_sep_resp.aw_ready) begin
                sep_xbar_in_aw_count_o <= sep_xbar_in_aw_count_o + 32'd1;
                sep_xbar_in_aw_user_o  <= 12'(u_dut.u_smu.xbar_to_sep_req.aw.user);
                sep_xbar_in_aw_addr_o  <= 56'(u_dut.u_smu.xbar_to_sep_req.aw.addr);
            end
        end
    end
`undef SEP_BD_ICCM

`undef SEP_BD_DCCM

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
`else
    // No SEP instance in this profile: no TCM to load or count, no SMN path.
    assign sep_iccm_write_count_o  = '0;
    assign sep_dccm_write_count_o  = '0;
    assign sep_smn_out_aw_count_o  = '0;
    assign sep_xbar_global_base_o  = '0;
    assign sep_xbar_region_size_o  = '0;
    assign sep_xbar_in_aw_count_o  = '0;
    assign sep_xbar_in_aw_user_o   = '0;
    assign sep_xbar_in_aw_addr_o   = '0;
    assign sep_ap_remap_offset0_o  = '0;
    assign sep_stee_remap_offset0_o = '0;
    assign sep_ap_csr_aw_count_o   = '0;
    assign sep_ap_reg0_aw_count_o  = '0;
    assign sep_csr_aw_count_o      = '0;
    assign sep_csr_last_aw_addr_o  = '0;
    assign sep_csr_errslv_aw_count_o = '0;
`endif

    // ------------------------------------------------------------------
    // External SMN AXI slave — SEP rom_boot / SMC SYS_OUT posture. Firmware
    // console / PASS magic is a TB observe snoop on the same wires (SEP
    // sep_outbound_mbx decode), not a second bus terminator.
    // ------------------------------------------------------------------
    localparam logic [31:0] FW_STDOUT_ADDR = 32'h8000_0000;
    localparam logic [31:0] FW_MAGIC0      = 32'hA5A5_5A5A;
    localparam logic [31:0] FW_MAGIC_PASS  = 32'hCAFE_BABE;
    localparam logic [31:0] FW_MAGIC_FAIL  = 32'hDEAD_BEEF;

    smu_axi_xbar_pkg::axi_out_req_t  [0:0] axi_out_mem_req;
    smu_axi_xbar_pkg::axi_out_resp_t [0:0] axi_out_mem_resp;

    // Register the boundary channels so the terminator sees edge-aligned
    // request signals: the crossbar's ext_out aw_valid settles late in the
    // cycle. The cut also keeps the terminator's ready out of the crossbar's
    // combinational cone.
    smu_axi_xbar_pkg::axi_out_req_t  axi_out_cut_req;
    smu_axi_xbar_pkg::axi_out_resp_t axi_out_cut_resp;

    axi_cut #(
        .aw_chan_t  (smu_axi_xbar_pkg::axi_out_aw_chan_t),
        .w_chan_t   (smu_axi_xbar_pkg::axi_out_w_chan_t),
        .b_chan_t   (smu_axi_xbar_pkg::axi_out_b_chan_t),
        .ar_chan_t  (smu_axi_xbar_pkg::axi_out_ar_chan_t),
        .r_chan_t   (smu_axi_xbar_pkg::axi_out_r_chan_t),
        .axi_req_t  (smu_axi_xbar_pkg::axi_out_req_t),
        .axi_resp_t (smu_axi_xbar_pkg::axi_out_resp_t)
    ) u_axi_out_cut (
        .clk_i      (clk_smu_i),
        .rst_ni     (rst_cold_n_o),
        .slv_req_i  (smu_axi_out_req),
        .slv_resp_o (smu_axi_out_resp),
        .mst_req_o  (axi_out_cut_req),
        .mst_resp_i (axi_out_cut_resp)
    );

    assign axi_out_mem_req[0] = axi_out_cut_req;
    assign axi_out_cut_resp   = axi_out_mem_resp[0];

    smu_axi_out_sim_slave #(
        .axi_req_t  (smu_axi_xbar_pkg::axi_out_req_t),
        .axi_resp_t (smu_axi_xbar_pkg::axi_out_resp_t),
        .AddrWidth  (56)
    ) u_axi_out_mem (
        .clk_i      (clk_smu_i),
        .rst_ni     (rst_cold_n_o),
        .axi_req_i  (axi_out_mem_req[0]),
        .axi_resp_o (axi_out_mem_resp[0])
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
            smu_axi_out_aw_valid_seen_o  <= 1'b0;
            smu_axi_out_aw_fired_seen_o  <= 1'b0;
            smu_axi_out_first_aw_addr_o  <= '0;
            smu_axi_out_w_valid_seen_o   <= 1'b0;
            smu_axi_out_w_fired_seen_o   <= 1'b0;
            smu_axi_out_w_last_seen_o    <= 1'b0;
            smu_axi_out_b_valid_seen_o   <= 1'b0;
            smu_axi_out_first_aw_len_o    <= '0;
            smu_axi_out_first_aw_size_o   <= '0;
            smu_axi_out_first_aw_burst_o  <= '0;
            smu_axi_out_first_aw_id_o     <= '0;
            smu_axi_out_first_aw_ctrl_x_o <= 1'b0;
            smu_axi_out_aw_valid_cycles_o <= '0;
            smu_axi_out_aw_ready_cycles_o <= '0;
            smu_axi_out_w_valid_cycles_o  <= '0;
            smu_axi_out_w_ready_cycles_o  <= '0;
            smu_axi_out_write_count_o <= '0;
            smu_axi_out_read_count_o  <= '0;
            fw_done_o                 <= 1'b0;
            fw_pass_o                 <= 1'b0;
            fw_char_o                 <= '0;
            fw_char_valid_o           <= 1'b0;
            fw_magic0_seen_q          <= 1'b0;
            fw_beacon_mask_o          <= '0;
            fw_last_word_o            <= '0;
        end else begin
            fw_char_valid_o <= 1'b0;

            if (smu_axi_out_req.aw_valid && !smu_axi_out_aw_valid_seen_o) begin
                smu_axi_out_aw_valid_seen_o <= 1'b1;
                smu_axi_out_first_aw_addr_o <= smu_axi_out_req.aw.addr;
                smu_axi_out_first_aw_len_o    <= smu_axi_out_req.aw.len;
                smu_axi_out_first_aw_size_o   <= smu_axi_out_req.aw.size;
                smu_axi_out_first_aw_burst_o  <= smu_axi_out_req.aw.burst;
                smu_axi_out_first_aw_id_o     <= smu_axi_out_req.aw.id;
                smu_axi_out_first_aw_ctrl_x_o <=
                    ($isunknown(smu_axi_out_req.aw.len)   ||
                     $isunknown(smu_axi_out_req.aw.size)  ||
                     $isunknown(smu_axi_out_req.aw.burst) ||
                     $isunknown(smu_axi_out_req.aw.id)    ||
                     $isunknown(smu_axi_out_req.aw.addr));
            end
            if (smu_axi_out_req.aw_valid) begin
                smu_axi_out_aw_valid_cycles_o <= smu_axi_out_aw_valid_cycles_o + 16'd1;
            end
            if (smu_axi_out_req.w_valid) begin
                smu_axi_out_w_valid_cycles_o <= smu_axi_out_w_valid_cycles_o + 16'd1;
            end
            if (smu_axi_out_resp.w_ready) begin
                smu_axi_out_w_ready_cycles_o <= smu_axi_out_w_ready_cycles_o + 16'd1;
            end
            if (smu_axi_out_resp.aw_ready) begin
                smu_axi_out_aw_ready_cycles_o <= smu_axi_out_aw_ready_cycles_o + 16'd1;
            end
            if (smu_axi_out_req.w_valid) smu_axi_out_w_valid_seen_o <= 1'b1;
            if (axi_out_w_fire) begin
                smu_axi_out_w_fired_seen_o <= 1'b1;
                if (smu_axi_out_req.w.last) smu_axi_out_w_last_seen_o <= 1'b1;
            end
            if (smu_axi_out_resp.b_valid) smu_axi_out_b_valid_seen_o <= 1'b1;
            if (axi_out_aw_fire) begin
                smu_axi_out_aw_fired_seen_o <= 1'b1;
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
            // SEP sep_outbound_mbx decode) — observe only; the terminator owns resp.
            if (axi_out_w_fire && axi_out_to_stdout) begin
                if (smu_axi_out_req.w.strb == 8'h01) begin
                    fw_char_o       <= smu_axi_out_req.w.data[7:0];
                    fw_char_valid_o <= 1'b1;
                end
                if (smu_axi_out_req.w.strb == 8'h0F ||
                        smu_axi_out_req.w.strb == 8'hF0) begin
                    fw_last_word_o <= axi_out_fw_word;
                    // STAGE_BEACON(id) from hw/sys/sep/dv/fw tests: the low
                    // nibble carries the stage, so a run reports how far the
                    // firmware got even when it never reaches its verdict.
                    if (axi_out_fw_word[31:4] == 28'hB1B0B0B) begin
                        fw_beacon_mask_o[axi_out_fw_word[3:0]] <= 1'b1;
                    end
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
        .entropy_rosc_sample_clk_i,
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
