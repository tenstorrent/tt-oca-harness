// SPDX-License-Identifier: Apache-2.0
//
// OSS smu_wrapper harness, shared by the native cocotb/PyUVM flow and the
// SystemVerilog UVM flow. ONE module, two shapes:
//
//   * default (cocotb, `--dut smu`): the ANSI port list of
//     smu_tb_signal_list.svh; cocotb drives the stimulus pins and samples
//     the observables.
//   * `UVM` (SV-UVM, `--dut smu --framework uvm`): the port list is replaced
//     by internal TB signals of the same names, and the harness block at the
//     end of this module adds the clocks, the shared JTAG VIP interface, the
//     SMU-local and embedded-DTP TB interfaces, a passive AXI interface on
//     the DTP's SMC-fabric JTAG2AXI port, quiescent tie-offs, uvm_config_db
//     publication, and run_test(). Test classes are compiled via
//     `include "smu_tests.sv".
//
// Instantiates hw/top/smu_wrapper.sv (logical ports); the CPU and I3C table
// memory macros come with smc_ip_integration inside it, following the same OSS
// composition pattern as smc_wrapper / sep_wrapper.

`timescale 1ps / 1fs

// Shape selection for smu_tb_signal_list.svh: the same list expands as the
// ANSI port list (cocotb) or as internal TB signals (`UVM`). The macros live
// only from here to the `undef block after the module header.
`ifndef UVM
  // cocotb shape: every entry is a pin-level ANSI port.
  `define SMU_TB_IN_FIRST(dtype, name) input  wire dtype name
  `define SMU_TB_IN(dtype, name)     , input  wire dtype name
  `define SMU_TB_OUT(dtype, name)    , output dtype name
`else
  // SV-UVM shape: every entry is an internal TB signal for the harness
  // block at the end of this module.
  `define SMU_TB_IN_FIRST(dtype, name) dtype name;
  `define SMU_TB_IN(dtype, name) dtype name;
  `define SMU_TB_OUT(dtype, name) dtype name;
`endif

module smu_wrapper_uvm_top
`ifndef UVM
(
  `include "smu_tb_signal_list.svh"
);
`else
;
  `include "smu_tb_signal_list.svh"
`endif

`undef SMU_TB_IN_FIRST
`undef SMU_TB_IN
`undef SMU_TB_OUT

  localparam smu_pkg::smu_cfg_t SmuBaseCfg = smu_pkg::DefaultCfg;

  // SEP_SEC_DISABLE_TOKEN is the metal expected digest. Product RTL defaults it
  // to 0, which no SHA-256 output matches; the SHA-256 of the all-zero 32-byte
  // token stands in for the metal value so a frontdoor token can take the match.
  localparam bit [255:0] SEC_DIS_TB_DIGEST =
      256'h66687aad_f862bd77_6c8fc18b_8e9f8e20_08971485_6ee233b3_902a591d_0d5f2925;

  // Every file-path plusarg this bench and its models consume; a present one
  // whose file cannot be opened ends the run at time 0.
  `include "ocah_path_plusargs.svh"
  initial begin : path_plusarg_guard
    static string names[] = '{
      "rom_bin64", "rom_hex", "smc_scratch_ram_hex", "smc_efuse_hex", "sep_efuse_hex",
      "sep_boot_rom_hex", "sep_itcm_hex", "sep_dtcm_hex", "smc_shadow_reg_preload",
      "sep_shadow_reg_preload"
    };
    ocah_require_file_plusargs(names);
  end

  // Same override tb_top.sv applies: exercise the most-significant configured
  // DTP cross-trigger mode bit while [1:0] stay SMC-reserved. Without it lane 7
  // is wire-OR here and point-to-point there, so the CTM leaves would score a
  // different design on the two DUTs.
  function automatic smu_pkg::smu_cfg_t make_tb_cfg();
    smu_pkg::smu_cfg_t cfg = SmuBaseCfg;
    cfg.XTRIG_INT_CT_MODE = 8'h80;
    cfg.SEP_SEC_DISABLE_TOKEN = SEC_DIS_TB_DIGEST;
    return cfg;
  endfunction

  localparam smu_pkg::smu_cfg_t SmuCfg = make_tb_cfg();

  localparam logic [31:0] SmcTestPass = 32'hACAF_ACA1;
  localparam logic [31:0] SmcTestFail = 32'hFFFF_FFFF;
  localparam logic [31:0] SepBootRomBase = 32'h1004_0000;
  localparam logic [31:0] SepBootRomEnd = 32'h1005_0000;
  localparam logic [31:0] SepIccmBase = 32'hC000_0000;
  localparam logic [31:0] SepIccmEnd = 32'hC004_0000;

  // ------------------------------------------------------------------
  // TB glue: clocks / JTAG / AXI / GPIO / CPU mem / observability
  // ------------------------------------------------------------------

  logic clk_smu, clk_ref, clk_periph;

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
  assign lcc_feat_ctrl_o = 64'(u_dut.u_smu.gen_sep.u_sep.u_sep_crypto
        .u_sep_lifecycle_ctrl.feat_ctrl_o);
  assign lcc_dbg_disable_o    = 16'(u_dut.u_smu.sep_dbg_disable);
  assign lcc_dbg_disable_smc_jtag2axi_o = u_dut.u_smu.sep_dbg_disable.smc_jtag2axi;
  assign smc_lc_state_in_o    = 8'(u_dut.u_smu.sep_lc_state);

  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      dtp_smc_dbg_aw_count_o <= '0;
      dtp_smc_dbg_ar_count_o <= '0;
      dtp_smc_dbg_b_count_o  <= '0;
    end else begin
      if (u_dut.u_smu.dtp_axi_smc_dbg_req.aw_valid &&
                u_dut.u_smu.dtp_axi_smc_dbg_resp.aw_ready) begin
        dtp_smc_dbg_aw_count_o <= dtp_smc_dbg_aw_count_o + 32'd1;
      end
      if (u_dut.u_smu.dtp_axi_smc_dbg_req.ar_valid &&
                u_dut.u_smu.dtp_axi_smc_dbg_resp.ar_ready) begin
        dtp_smc_dbg_ar_count_o <= dtp_smc_dbg_ar_count_o + 32'd1;
      end
      if (u_dut.u_smu.dtp_axi_smc_dbg_resp.b_valid && u_dut.u_smu.dtp_axi_smc_dbg_req.b_ready) begin
        dtp_smc_dbg_b_count_o <= dtp_smc_dbg_b_count_o + 32'd1;
      end
    end
  end

  // ------------------------------------------------------------------
  // ESRC raw-noise force.
  // ------------------------------------------------------------------
  // POLICY EXCEPTION. This DV root's rule is "no DUT Force" (see README); this
  // is the single named exception, the same one hw/sys/sep/dv/tb/tb_top.sv
  // calls "the one permitted force (raw noise at the source)".
  //
  // The ESRC ring oscillators rely on `#delay` feedback, which Verilator
  // ignores, so the 12 noise lanes never toggle and no entropy is produced.
  // The force replaces that analogue behaviour at the first node of the chain;
  // everything downstream -- decorrelator, compressor, SHA, CSRNG, EDN -- is
  // the real RTL working on the driven sequence, and the probes are read-only.
  //
  // Scope:
  //   * only under +esrc_noise_force,
  //   * only dcor.noise_i on the 12 generator lanes,
  //   * downstream taps observe, never drive.
  // Neither the SEP nor SMU bench forces downstream EDN responses.
  logic [11:0] esrc_noise_d;
  assign esrc_noise_d = esrc_noise_ext_i;
  assign esrc_noise_o = esrc_noise_d;
  // Lane 0's ACTUAL noise_i. With the force active this tracks the driven bit;
  // without it, it is whatever the RTL leaves there. A test compares the two so
  // "entropy flowed" cannot pass on a force that silently failed to take.
  assign esrc_noise_active_o = u_dut.u_smu.gen_sep.u_sep.u_sep_crypto.u_sep_trng
        .u_entropy_source_s3c_scan.u_generator_complex.gen_ecmplx[0].u_generator
        .u_decorrelator.noise_i;

  // Force the decorrelator INPUT PORT -- the exact node the SR flop samples.
  // Re-issued every clock: a `force` inside an `initial` snapshots its RHS once
  // at t=0 under Verilator and would hold that stale value. Explicit per-lane
  // indices because a genvar-indexed cross-hierarchy force is not allowed.
  `define SMU_ESRC_NOISE_FORCE(i)                                                \
    force u_dut.u_smu.gen_sep.u_sep.u_sep_crypto.u_sep_trng                      \
        .u_entropy_source_s3c_scan.u_generator_complex.gen_ecmplx[i]             \
        .u_generator.u_decorrelator.noise_i = esrc_noise_d[i]

  always @(posedge clk_smu) begin
    if ($test$plusargs("esrc_noise_force")) begin
      `SMU_ESRC_NOISE_FORCE(0);
      `SMU_ESRC_NOISE_FORCE(1);
      `SMU_ESRC_NOISE_FORCE(2);
      `SMU_ESRC_NOISE_FORCE(3);
      `SMU_ESRC_NOISE_FORCE(4);
      `SMU_ESRC_NOISE_FORCE(5);
      `SMU_ESRC_NOISE_FORCE(6);
      `SMU_ESRC_NOISE_FORCE(7);
      `SMU_ESRC_NOISE_FORCE(8);
      `SMU_ESRC_NOISE_FORCE(9);
      `SMU_ESRC_NOISE_FORCE(10);
      `SMU_ESRC_NOISE_FORCE(11);
    end
  end
  `undef SMU_ESRC_NOISE_FORCE

  assign drbg_seed_valid_o = u_dut.u_smu.gen_sep.u_sep.u_sep_crypto.u_sep_trng
        .u_drbg_s3c_scan.u_csrng_seed_adapter.seed_queue_valid_o;
  assign drbg_es_ack_o = u_dut.u_smu.gen_sep.u_sep.u_sep_crypto.u_sep_trng
        .u_drbg_s3c_scan.u_csrng.entropy_src_hw_if_i.es_ack;
  assign drbg_genbits_vld_o = u_dut.u_smu.gen_sep.u_sep.u_sep_crypto.u_sep_trng
        .u_drbg_s3c_scan.u_csrng.u_csrng_core.u_csrng_ctr_drbg.bits_vld_o;
  // Sticky capture. esrc_noise_took requires a driven 1 that the DUT node
  // actually shows: a match on 0 would also hold with the force absent.
  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      drbg_seed_valid_seen_o <= 1'b0;
      drbg_es_ack_seen_o     <= 1'b0;
      drbg_genbits_seen_o    <= 1'b0;
      esrc_noise_took_o      <= 1'b0;
    end else begin
      if (drbg_seed_valid_o) drbg_seed_valid_seen_o <= 1'b1;
      if (drbg_es_ack_o) drbg_es_ack_seen_o <= 1'b1;
      if (drbg_genbits_vld_o) drbg_genbits_seen_o <= 1'b1;
      if (esrc_noise_o[0] && esrc_noise_active_o) esrc_noise_took_o <= 1'b1;
    end
  end

  assign ic_reset_smc_ovrd_o = 68'(u_dut.u_smu.jtag_smc_reset_ctrl.ovrd);
  assign ic_reset_sep_ovrd_any_o = |u_dut.u_smu.jtag_sep_reset_ctrl.ovrd;

  assign jtag_tdo      = jtag_ptap_tdo;
  assign jtag_tdo_oen  = jtag_ptap_tdo_oen;

  smu_axi_xbar_pkg::axi_56_64_req_t  smu_axi_in_req;
  smu_axi_xbar_pkg::axi_56_64_resp_t smu_axi_in_resp;
  smu_axi_xbar_pkg::axi_out_req_t     smu_axi_out_req;
  smu_axi_xbar_pkg::axi_out_resp_t    smu_axi_out_resp;
  logic [7:0] lc_state;

  // smc_4core_cpu zeroes the whole scratch RAM at boot to establish valid ECC
  // (its MEM_ZERO FSM, gated by this input). That runs after the time-zero
  // +smc_scratch_ram_hex load, so an image placed there does not survive to
  // first fetch. Hold the FSM off whenever a test supplies such an image;
  // hw/sys/smc/dv holds it off unconditionally.
  // tb_smc_sram_auto_init_restore returns the input low, so a later cold reset
  // runs the zeroing sweep over the image.
  logic smc_scratch_preloaded = 1'b0;
  logic smc_disable_sram_auto_init;
  initial begin : smc_scratch_preload_gates_auto_init
    string scratch_hex_path;
    smc_scratch_preloaded = $value$plusargs("smc_scratch_ram_hex=%s", scratch_hex_path);
  end
  assign smc_disable_sram_auto_init = smc_scratch_preloaded & ~tb_smc_sram_auto_init_restore;

  // CPU memory macros live inside smc_ip_integration, so the ROM request is
  // observed hierarchically.
  chipyard_4core_mem_pkg::rom_req_t rom_intf_req;
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
    .clk_i                (clk_sys_o),
    .rst_ni               (rst_primary_smc_clk_ni),
    .rom_req_i            (rom_intf_req),
    .scratch_ram_req_i    (scratch_ram_intf_req),
    .l1_dcache_data_req_i (l1_dcache_data_intf_req),
    .ecc_inject_sbe_i     (1'b0),
    .ecc_inject_dbe_i     (1'b0)
  );

  wire [smc_pkg::NumGpioWraps-1:0] gpio_pad_io;
  logic [smc_pkg::NumMailboxes-1:0] ext_mailbox_interrupts;
  logic [31:0] smc_scratch_0_q;
  logic        rst_cold_stable_ref_clk_n;
  prim_jtag_pkg::jtag_scan_ctrl_t bsr_ctrl_w;
  // BSR scan out folded back to scan in, as tb_top.sv does: the EXTEST
  // loopback test compares TDO against what it shifted in.
  logic bsr_scan_loop;
  logic smu_scope_boot_stall_val, smu_scope_boot_stall_ovrd;
  jtag_tap_pkg::jtag_ic_reset_default_t ic_reset_ext_w;
  prim_jtag_pkg::jtag_tap_ctrl_t        stap_io_ctrl_w;
  logic        rst_primary_smc_clk_n;
  logic        sep_reset_n;
  sep_pkg::sep_cpu_trace_t sep_cpu_trace;
  logic                    secure_tm_req;

  // Boundary outputs observed only by the cov/sv functional-coverage modules.
  logic skip_mem_repair_w;
  logic [31:0] ss_config_w;
  smc_reset_unit_pkg::reset_ctrl_t ss_reset_ctrl_w [31:0];
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_req_out_dout_w, ctp_req_in_dout_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_ack_in_dout_w, ctp_ack_out_dout_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_req_out_dout_en_w, ctp_req_out_din_en_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_req_in_dout_en_w, ctp_req_in_din_en_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_ack_in_dout_en_w, ctp_ack_in_din_en_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_ack_out_dout_en_w, ctp_ack_out_din_en_w;
  // CT_Req_out shared-wire model: the wire each pad's DUT input sees, a
  // private ocah_open_drain_bus per pad and one shared by the pads in
  // tb_xtrig_ctp_wire_group.
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_req_out_din_w;
  logic [dtp_pkg::DefaultNumCtp-1:0] ctp_wire_private_w, ctp_wire_private_mismatch_w;
  logic ctp_wire_group_wire_w, ctp_wire_group_mismatch_w;
  logic [31:0] jtag_ptap_state_w;
  logic [31:0] smu_axi_in_awvalid_count, smu_axi_out_awvalid_count;
  logic tb_axil_external_active;

  // Scan-chain closures. The STAP and BSR hosts return their scan_out on
  // their own scan_in. Each iJTAG host (DFD, DFT, secure DFT) returns through
  // one bench scan cell instead: a one-bit prim_jtag_scan_reg on the host's
  // scan control, which captures 0 at Capture-DR and shifts while the host
  // select is set, so a shift through an open SIB is one TCK longer than
  // through a closed one and the crossing of the boundary pins is visible at
  // TDO.
  prim_jtag_pkg::jtag_scan_ctrl_t stap_scan_ctrl_w, dfd_ctrl_w, dft_ctrl_w, dft_sec_ctrl_w;
  logic stap_scan_loop, dfd_scan_loop, dft_scan_loop, dft_sec_scan_loop;
  logic dfd_scan_ret, dft_scan_ret, dft_sec_scan_ret;
  logic stap_io_tdo_w, stap_io_tdo_oen_w;
  prim_jtag_pkg::jtag_tap_ctrl_t stap_extra_ctrl_w [0:0];
  logic stap_extra_tdi_w [0:0];
  logic stap_extra_tdo_w [0:0];
  logic stap_extra_tdo_oen_w [0:0];

  assign stap_extra_tdi_w[0] = stap_extra_tdo_w[0];

  assign tb_stap_host_select    = stap_scan_ctrl_w.select;
  assign tb_dfd_select          = dfd_ctrl_w.select;
  assign tb_dft_select          = dft_ctrl_w.select;
  assign tb_dft_secure_select   = dft_sec_ctrl_w.select;
  assign tb_dfd_scan_out        = dfd_scan_loop;
  assign tb_dft_scan_out        = dft_scan_loop;
  assign tb_dft_secure_scan_out = dft_sec_scan_loop;

  prim_jtag_scan_reg #(
    .WIDTH(1)
  ) u_dfd_loop_cell (
    .scan_ctrl_i(dfd_ctrl_w),
    .scan_in_i  (dfd_scan_loop),
    .scan_out_o (dfd_scan_ret),
    .data_in_i  (1'b0),
    .data_out_o ()
  );

  prim_jtag_scan_reg #(
    .WIDTH(1)
  ) u_dft_loop_cell (
    .scan_ctrl_i(dft_ctrl_w),
    .scan_in_i  (dft_scan_loop),
    .scan_out_o (dft_scan_ret),
    .data_in_i  (1'b0),
    .data_out_o ()
  );

  prim_jtag_scan_reg #(
    .WIDTH(1)
  ) u_dft_sec_loop_cell (
    .scan_ctrl_i(dft_sec_ctrl_w),
    .scan_in_i  (dft_sec_scan_loop),
    .scan_out_o (dft_sec_scan_ret),
    .data_in_i  (1'b0),
    .data_out_o ()
  );
  assign tb_stap_io_tms         = stap_io_ctrl_w.tms;
  assign tb_stap_io_tdo         = stap_io_tdo_w;
  assign tb_stap_io_tdo_oen     = stap_io_tdo_oen_w;
  assign tb_stap_extra0_tms     = stap_extra_ctrl_w[0].tms;
  assign tb_stap_extra0_tdo     = stap_extra_tdo_w[0];
  assign tb_stap_extra0_tdo_oen = stap_extra_tdo_oen_w[0];

  // ATB telemetry: the bench is the source for every receiver.
  localparam int unsigned NumTel = smc_config_pkg::NumTelemetryReceivers;
  telemetry_receiver_pkg::telemetry_data_t [NumTel-1:0] tel_atdata_w;
  telemetry_receiver_pkg::atb_id_t         [NumTel-1:0] tel_atid_w;
  logic [NumTel-1:0] tel_atvalid_w, tel_afready_w, tel_atready_w, tel_afvalid_w;

  always_comb begin
    for (int r = 0; r < NumTel; r++) begin
      tel_atdata_w[r] = tb_telemetry_atdata[r];
      tel_atid_w[r]   = tb_telemetry_atid[r];
    end
  end
  assign tel_atvalid_w        = tb_telemetry_atvalid;
  assign tel_afready_w        = tb_telemetry_afready;
  assign tb_telemetry_atready = tel_atready_w;
  assign tb_telemetry_afvalid = tel_afvalid_w;

  // SMC boundary: the external interrupt vector is NUM_INT_TO_SMC wide and the
  // bench drives its low 32 lanes.
  logic [SmuCfg.NUM_INT_TO_SMC-1:0] smc_ext_interrupts_w;
  logic [smc_config_pkg::CpuClusterCount-1:0] ndmreset_process_w;
  logic [31:0] isolate_req_w;
  logic sync_irq_w, cluster_ded_w, wdt_first_timeout_w, wdt_second_timeout_w;
  logic secure_tm_w;
  logic [smc_pkg::NumGpioWraps-1:0]   gpio_interrupt_w;
  logic [smc_config_pkg::NumUart-1:0] uart_interrupt_w;

  always_comb begin
    smc_ext_interrupts_w = '0;
    smc_ext_interrupts_w[smc_4core_cpu_pkg::NumExtInterrupts-1:0] = tb_smc_ext_interrupts;
  end

  assign tb_smc_ndmreset_process   = ndmreset_process_w;
  assign tb_isolate_req            = isolate_req_w;
  assign tb_ss_config              = ss_config_w;
  assign tb_sync_irq               = sync_irq_w;
  assign tb_skip_mem_repair        = skip_mem_repair_w;
  assign tb_smc_cluster_ded        = cluster_ded_w;
  assign tb_smc_wdt_first_timeout  = wdt_first_timeout_w;
  assign tb_smc_wdt_second_timeout = wdt_second_timeout_w;
  assign tb_gpio_interrupt         = gpio_interrupt_w;
  assign tb_uart_interrupt         = uart_interrupt_w;

  always_comb begin
    for (int ss = 0; ss < 32; ss++) begin
      tb_ss_cold_reset_n[ss]         = ss_reset_ctrl_w[ss].cold_reset_n;
      tb_ss_warm_reset_n[ss]         = ss_reset_ctrl_w[ss].warm_reset_n;
      tb_ss_config_state_hold[ss]    = ss_reset_ctrl_w[ss].config_state_hold;
      tb_ss_sram_hold[ss]            = ss_reset_ctrl_w[ss].sram_hold;
      tb_ss_critical_signal_hold[ss] = ss_reset_ctrl_w[ss].critical_signal_hold;
      tb_ss_debug_hold[ss]           = ss_reset_ctrl_w[ss].debug_hold;
      tb_ss_force_to_ref_clk_n[ss]   = ss_reset_ctrl_w[ss].force_to_ref_clk_n;
    end
  end

  assign tb_xtrig_ctp_req_out_dout    = ctp_req_out_dout_w;
  assign tb_xtrig_ctp_req_out_dout_en = ctp_req_out_dout_en_w;
  assign tb_xtrig_ctp_req_out_din_en  = ctp_req_out_din_en_w;

  // CT_Req_out shared wires. A chiplet driver pulls towards the level
  // opposite its wire's pull; a pad in the group leaves its private wire.
  for (genvar ctp = 0; ctp < dtp_pkg::DefaultNumCtp; ctp++) begin : gen_xtrig_ctp_wire
    ocah_open_drain_bus #(
      .NUM_DRIVERS(2)
    ) u_wire (
      .pull_i     (tb_xtrig_ctp_wire_pull[ctp]),
      .dout_i     ({~tb_xtrig_ctp_wire_pull[ctp], ctp_req_out_dout_w[ctp]}),
      .dout_en_i  ({tb_xtrig_ctp_wire_ext_assert[ctp], ctp_req_out_dout_en_w[ctp]}
                   & {2{~tb_xtrig_ctp_wire_group[ctp]}}),
      .wire_o     (ctp_wire_private_w[ctp]),
      .mismatch_o (ctp_wire_private_mismatch_w[ctp])
    );
    assign ctp_req_out_din_w[ctp] = tb_xtrig_ctp_wire_group[ctp]
        ? ctp_wire_group_wire_w : ctp_wire_private_w[ctp];
    assign tb_xtrig_ctp_wire_mismatch[ctp] = tb_xtrig_ctp_wire_group[ctp]
        ? ctp_wire_group_mismatch_w : ctp_wire_private_mismatch_w[ctp];
    assign tb_xtrig_ctp_ct_dst[ctp] =
        u_dut.u_smu.u_dtp.u_cross_trigger_network.gen_ext_ctp[ctp].u_ctp.ct_dst_o;
  end

  ocah_open_drain_bus #(
    .NUM_DRIVERS(2 * dtp_pkg::DefaultNumCtp)
  ) u_xtrig_ctp_group_wire (
    .pull_i     (tb_xtrig_ctp_wire_group_pull),
    .dout_i     ({{dtp_pkg::DefaultNumCtp{~tb_xtrig_ctp_wire_group_pull}},
                  ctp_req_out_dout_w}),
    .dout_en_i  ({tb_xtrig_ctp_wire_ext_assert & tb_xtrig_ctp_wire_group,
                  ctp_req_out_dout_en_w & tb_xtrig_ctp_wire_group}),
    .wire_o     (ctp_wire_group_wire_w),
    .mismatch_o (ctp_wire_group_mismatch_w)
  );

  assign tb_xtrig_ctp_req_out_din = ctp_req_out_din_w;

  assign tb_xtrig_ctp_req_in_dout     = ctp_req_in_dout_w;
  assign tb_xtrig_ctp_req_in_dout_en  = ctp_req_in_dout_en_w;
  assign tb_xtrig_ctp_req_in_din_en   = ctp_req_in_din_en_w;
  assign tb_xtrig_ctp_ack_in_dout     = ctp_ack_in_dout_w;
  assign tb_xtrig_ctp_ack_in_dout_en  = ctp_ack_in_dout_en_w;
  assign tb_xtrig_ctp_ack_in_din_en   = ctp_ack_in_din_en_w;
  assign tb_xtrig_ctp_ack_out_dout    = ctp_ack_out_dout_w;
  assign tb_xtrig_ctp_ack_out_dout_en = ctp_ack_out_dout_en_w;
  assign tb_xtrig_ctp_ack_out_din_en  = ctp_ack_out_din_en_w;

  assign secure_tm_req = tb_secure_tm_req;
  assign tb_secure_tm  = secure_tm_w;
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
  // meaningless field. len/size/burst are real ports: the ext_axi route legs
  // are single-beat, and the DECERR leg carries the full channel.
  assign smu_axi_in_req.aw.id     = ext_in_awid;
  assign smu_axi_in_req.aw.addr   = ext_in_awaddr;
  assign smu_axi_in_req.aw.len    = ext_in_awlen;
  assign smu_axi_in_req.aw.size   = ext_in_awsize;
  assign smu_axi_in_req.aw.burst  = ext_in_awburst;
  assign smu_axi_in_req.aw.lock   = ext_in_awlock;
  assign smu_axi_in_req.aw.cache  = ext_in_awcache;
  assign smu_axi_in_req.aw.prot   = ext_in_awprot;
  assign smu_axi_in_req.aw.qos    = ext_in_awqos;
  assign smu_axi_in_req.aw.region = ext_in_awregion;
  assign smu_axi_in_req.aw.atop   = '0;
  assign smu_axi_in_req.aw.user   = ext_in_awuser;
  assign smu_axi_in_req.aw_valid  = ext_in_awvalid;

  assign smu_axi_in_req.w.data    = ext_in_wdata;
  assign smu_axi_in_req.w.strb    = ext_in_wstrb;
  assign smu_axi_in_req.w.last    = ext_in_wlast;
  assign smu_axi_in_req.w.user    = ext_in_wuser;
  assign smu_axi_in_req.w_valid   = ext_in_wvalid;

  assign smu_axi_in_req.b_ready   = ext_in_bready;

  assign smu_axi_in_req.ar.id     = ext_in_arid;
  assign smu_axi_in_req.ar.addr   = ext_in_araddr;
  assign smu_axi_in_req.ar.len    = ext_in_arlen;
  assign smu_axi_in_req.ar.size   = ext_in_arsize;
  assign smu_axi_in_req.ar.burst  = ext_in_arburst;
  assign smu_axi_in_req.ar.lock   = ext_in_arlock;
  assign smu_axi_in_req.ar.cache  = ext_in_arcache;
  assign smu_axi_in_req.ar.prot   = ext_in_arprot;
  assign smu_axi_in_req.ar.qos    = ext_in_arqos;
  assign smu_axi_in_req.ar.region = ext_in_arregion;
  assign smu_axi_in_req.ar.user   = ext_in_aruser;
  assign smu_axi_in_req.ar_valid  = ext_in_arvalid;

  assign smu_axi_in_req.r_ready   = ext_in_rready;

  assign ext_in_awready = smu_axi_in_resp.aw_ready;
  assign ext_in_wready  = smu_axi_in_resp.w_ready;
  assign ext_in_bid     = smu_axi_in_resp.b.id;
  assign ext_in_bresp   = smu_axi_in_resp.b.resp;
  assign ext_in_buser   = smu_axi_in_resp.b.user;
  assign ext_in_bvalid  = smu_axi_in_resp.b_valid;
  assign ext_in_arready = smu_axi_in_resp.ar_ready;
  assign ext_in_rid     = smu_axi_in_resp.r.id;
  assign ext_in_rdata   = smu_axi_in_resp.r.data;
  assign ext_in_rresp   = smu_axi_in_resp.r.resp;
  assign ext_in_rlast   = smu_axi_in_resp.r.last;
  assign ext_in_ruser   = smu_axi_in_resp.r.user;
  assign ext_in_rvalid  = smu_axi_in_resp.r_valid;

  // Cocotb observe ports that hw/top/smu_wrapper does not expose directly.
  assign dut_present_o = 1'b1;
  assign sep_enabled_o = SmuCfg.SEP;
  assign powergood_o   = powergood_i;
  assign rst_cold_n_o  = rst_cold_stable_ref_clk_n;
  assign rst_primary_smc_clk_n_o = rst_primary_smc_clk_n;

  // prim_rom's noXOnCsI is never disabled (its reset argument is '0), so on a
  // four-state simulator it fires on the X that req_i carries before reset.
  // The wrapper elaborates sep_ip_integration on both profiles, so the two SEP
  // ROMs are present even with SEP disabled. Hold the three checks off until
  // the SMC primary reset has released and one SMC clock edge has sampled a
  // known req_i, then re-arm them so a later X still fails.
`ifndef VERILATOR
  initial begin
    $assertoff(0, u_dut.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.noXOnCsI);
    $assertoff(0, u_dut.u_sep_ip_integration.u_sep_boot_rom.noXOnCsI);
    $assertoff(0, u_dut.u_sep_ip_integration.u_km_rom.noXOnCsI);
    wait (rst_primary_smc_clk_n === 1'b1);
    @(posedge clk_smu);
    $asserton(0, u_dut.u_smc_ip_integration.u_mems.u_rom_mem.u_mem.noXOnCsI);
    $asserton(0, u_dut.u_sep_ip_integration.u_sep_boot_rom.noXOnCsI);
    $asserton(0, u_dut.u_sep_ip_integration.u_km_rom.noXOnCsI);
  end
`endif

  // powergood_stable is the SMC reset controller's stretched and synchronized
  // view of powergood_i (smc_reset_ctrl.sv), so it rises only once the DUT's own
  // synchronizer chain has clocked it through. The sticky low record carries no
  // reset: it must survive the cold-reset window in which it is set, so its
  // declaration initialiser is the only zeroing, and a variable with an
  // initialiser may not be an always_ff target (IEEE 1800-2017 9.2.2.4, an
  // error on VCS).
  assign obs_powergood_stable_o = u_dut.u_smu.powergood_stable;
  logic obs_powergood_stable_low_seen_q = 1'b0;
  always @(posedge clk_ref) begin
    if (!obs_powergood_stable_o) begin
      obs_powergood_stable_low_seen_q <= 1'b1;
    end
  end
  assign obs_powergood_stable_low_seen_o = obs_powergood_stable_low_seen_q;
  assign sep_reset_n = u_dut.u_smu.gen_sep.u_sep.sep_reset_n;
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

  assign obs_compose_sep_present_o = 1'b1;
  assign obs_compose_xbar_present_o = 1'b1;
  assign obs_sep_clk_o = u_dut.u_smu.gen_sep.u_sep.clk_i;
  assign obs_xbar_clk_o = u_dut.u_smu.gen_sep.u_smu_axi_xbar.clk_i;
  assign obs_sep_rst_n_o = u_dut.u_smu.gen_sep.u_sep.rst_ni;
  assign obs_xbar_rst_n_o = u_dut.u_smu.gen_sep.u_smu_axi_xbar.rst_ni;
  assign obs_sep_wdt_clk_o = u_dut.u_smu.gen_sep.u_sep.clk_wdt_i;
  // Live SEP LCC export — must match lc_state_o for lc_state=from_sep.
  assign obs_sep_lc_state_o = u_dut.u_smu.gen_sep.u_sep.lc_state_o;
  // The SEP efuse shadow registers' own sim_skip_fuse_sense flag: 1 when
  // +skip_fuse_sense replaces the fuse-sense sequence with the shadow preload,
  // 0 whenever the sense runs -- including a build without the SIMULATION
  // define, where the plusarg has no effect at all.
  assign sep_fuse_sense_skipped_o = u_dut.u_smu.gen_sep.u_sep.u_sep_crypto
        .u_sep_efuse_wrapper.u_efuse_interface_controller.u_efuse_shadow_regs
        .sim_skip_fuse_sense;

  assign smc_scratch_0_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[0];
  assign smc_scratch_6_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[6];
  assign smc_scratch_7_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[7];
  assign smc_scratch_10_o =
        u_dut.u_smu.u_smc.u_smc_cpu_wrapper.u_smc_cpu_ctrl_wrap.scratch_reg[10];
  assign smc_test_pass_o = smc_scratch_0_o == SmcTestPass;
  assign smc_test_fail_o = smc_scratch_0_o == SmcTestFail;

  // Mask SEP trace while the CPU is in reset: VCS leaves the EL2 trace
  // struct at X and cocotb read_int() rejects X/Z.
  assign sep_trace_valid_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_valid_ip : 1'b0;
  assign sep_pc_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_address_ip : '0;
  assign sep_trace_insn_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_insn_ip : '0;
  assign sep_trace_exc_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_exception_ip : 1'b0;
  assign sep_trace_ecause_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_ecause_ip : '0;
  assign sep_trace_interrupt_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_interrupt_ip : 1'b0;
  assign sep_trace_tval_o =
        sep_reset_n ? sep_cpu_trace.trace_rv_i_tval_ip : '0;

  // Observe SEP run-gate nets. Use ifdef (not generate-if) so the no-SEP
  // compile never resolves gen_sep hierarchy XMRs.
  assign sep_cla_custom_o =
        16'(u_dut.u_smu.cla_ext_action_custom);
  assign sep_mpc_reset_run_o =
        u_dut.u_smu.gen_sep.u_sep.mpc_reset_run_req_i;
  assign sep_mpc_debug_run_o =
        u_dut.u_smu.gen_sep.u_sep.mpc_debug_run_req_i;
  assign sep_cpu_run_req_o =
        u_dut.u_smu.gen_sep.u_sep.cpu_run_req_i;
  assign sep_halt_status_o =
        u_dut.u_smu.gen_sep.u_sep.cpu_halt_status_o;
  assign sep_debug_mode_o =
        u_dut.u_smu.gen_sep.u_sep.debug_mode_status_o;
  assign sep_cpu_rst_ni_o =
        u_dut.u_smu.gen_sep.u_sep.u_sep_cpu.rst_ni;
  assign sep_dbg_rstb_o =
        u_dut.u_smu.gen_sep.u_sep.dbg_rstb_i;
  assign sep_mod_rst_ni_o =
        u_dut.u_smu.gen_sep.u_sep.rst_ni;

  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      sep_boot_rom_req_count_o <= '0;
    end else if (u_dut.sep_boot_rom_req.req) begin
      sep_boot_rom_req_count_o <= sep_boot_rom_req_count_o + 32'd1;
    end
  end

  always_ff @(posedge u_dut.u_smu.gen_sep.u_sep.u_sep_cpu.clk_i or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      sep_cpu_clk_count_o <= '0;
    end else begin
      sep_cpu_clk_count_o <= sep_cpu_clk_count_o + 32'd1;
    end
  end

  // Capture run-gate at the SEP CPU reset 0->1 edge (EL2 samples then).
  logic sep_cpu_rst_ni_q;
  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
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

  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
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
  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
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
      if (sep_pc_o >= SepBootRomBase && sep_pc_o < SepBootRomEnd) begin
        sep_boot_rom_fetch_seen_o <= 1'b1;
      end
      if (sep_pc_o >= SepIccmBase && sep_pc_o < SepIccmEnd) begin
        sep_iccm_fetch_seen_o <= 1'b1;
      end
    end
  end

  // ------------------------------------------------------------------
  // SEP ICCM/DCCM backdoor: time-zero image load + write-count evidence.
  //
  // hw/sys/sep/rtl/sep_tcm_wrapper.sv instantiates the upstream VeeR
  // `ram_<depth>x39` models (vendor/chipsalliance/Cores-VeeR-EL2/upstream/
  // design/lib/mem_lib.sv, already on the smu_wrapper Bender closure). Those
  // macros have no init-file hook, so the firmware images named by
  // +sep_itcm_hex / +sep_dtcm_hex are loaded here at time zero — the same
  // backdoor pattern the SEP DV TB uses (hw/sys/sep/dv/tb/tb_top.sv
  // `BD_ICCM/`BD_DCCM), against the same `u_ram.ram_core` arrays.
  //
  // Geometry is fixed by the SEP EL2 config and matches fw/common/sep_tcm.ld:
  //   ICCM 256 KiB @ 0xC000_0000 = 4 banks x 16384 rows x 39b
  //   DCCM 128 KiB @ 0xC004_0000 = 2 banks x 16384 rows x 39b
  // Byte offset -> {bank, row} interleave follows the macro address wiring:
  //   ICCM bank = offset[3:2], row = offset[17:4]
  //   DCCM bank = offset[2],   row = offset[16:3]
  // ------------------------------------------------------------------
  localparam int unsigned SepIccmBytes = 262144;  // 256 KiB
  localparam int unsigned SepDccmBytes = 131072;  // 128 KiB

  `define SEP_BD_ICCM(b) \
    u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.gen_iccm.gen_bank[b].gen_iccm_ram.u_ram.ram_core
  `define SEP_BD_DCCM(b) \
    u_dut.u_sep_ip_integration.u_sep_tcm_wrapper.gen_dccm.gen_bank[b].gen_dccm_ram.u_ram.ram_core

  logic [7:0] sep_itcm_buf [SepIccmBytes];
  logic [7:0] sep_dtcm_buf [SepDccmBytes];

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
    // placed there by this loader.
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
        $fatal(1, "[smu_wrapper_uvm_top] missing SEP ICCM image %s", sep_itcm_path);
      end
      $fclose(fd);
      fd = $fopen(sep_dtcm_path, "r");
      if (fd == 0) begin
        $fatal(1, "[smu_wrapper_uvm_top] missing SEP DCCM image %s", sep_dtcm_path);
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
    for (int i = 0; i < SepIccmBytes; i++) sep_itcm_buf[i] = 8'h00;
    if (!$test$plusargs("sep_no_tcm_preload")) begin
      $readmemh(sep_itcm_path, sep_itcm_buf);
    end
    for (off = 0; off + 3 < SepIccmBytes; off += 4) begin
      w  = {sep_itcm_buf[off+3], sep_itcm_buf[off+2],
                  sep_itcm_buf[off+1], sep_itcm_buf[off]};
      fw = (w == 32'h0) ? '0 : {sep_tcm_ecc32(w), w};
      unique case (off[3:2])
        2'd0: `SEP_BD_ICCM(0)[off[17:4]] = fw;
        2'd1: `SEP_BD_ICCM(1)[off[17:4]] = fw;
        2'd2: `SEP_BD_ICCM(2)[off[17:4]] = fw;
        2'd3: `SEP_BD_ICCM(3)[off[17:4]] = fw;
      endcase
    end
    for (int i = 0; i < SepDccmBytes; i++) sep_dtcm_buf[i] = 8'h00;
    if (!$test$plusargs("sep_no_tcm_preload")) begin
      $readmemh(sep_dtcm_path, sep_dtcm_buf);
    end
    for (off = 0; off + 3 < SepDccmBytes; off += 4) begin
      w  = {sep_dtcm_buf[off+3], sep_dtcm_buf[off+2],
                  sep_dtcm_buf[off+1], sep_dtcm_buf[off]};
      fw = (w == 32'h0) ? '0 : {sep_tcm_ecc32(w), w};
      if (off[2]) `SEP_BD_DCCM(1) [off[16:3]] = fw;
      else `SEP_BD_DCCM(0) [off[16:3]] = fw;
    end
    if ($test$plusargs("sep_no_tcm_preload")) begin
      $display("[smu_wrapper_uvm_top] SEP TCM zeroed, no image preloaded");
    end else begin
      $display("[smu_wrapper_uvm_top] loaded SEP ICCM from %s, DCCM from %s", sep_itcm_path,
               sep_dtcm_path);
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
  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      sep_ap_csr_aw_count_o  <= '0;
      sep_ap_reg0_aw_count_o <= '0;
      sep_csr_aw_count_o     <= '0;
      sep_csr_last_aw_addr_o <= '0;
      sep_csr_errslv_aw_count_o <= '0;
    end else begin
      if (u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_reqs[sep_pkg::AP_OUTPUT_REMAP].aw_valid) begin
        sep_ap_csr_aw_count_o <= sep_ap_csr_aw_count_o + 32'd1;
      end
      if (u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_sep_system_csr
                    .ap_output_remap_reqs[0].aw_valid) begin
        sep_ap_reg0_aw_count_o <= sep_ap_reg0_aw_count_o + 32'd1;
      end
      if (u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_req_i.aw_valid) begin
        sep_csr_aw_count_o     <= sep_csr_aw_count_o + 32'd1;
        sep_csr_last_aw_addr_o <= 56'(u_dut.u_smu.gen_sep.u_sep
                    .u_sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_req_i.aw.addr);
      end
      if (u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_sep_system_csr
                    .sep_system_csr_axil_reqs[sep_pkg::ERR_SLV].aw_valid) begin
        sep_csr_errslv_aw_count_o <= sep_csr_errslv_aw_count_o + 32'd1;
      end
    end
  end

  assign sep_ap_remap_offset0_o =
        u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_ap_remap.remap_table[0].offset;
  assign sep_stee_remap_offset0_o =
        u_dut.u_smu.gen_sep.u_sep.u_sep_system_peripherals.u_stee_remap.remap_table[0].offset;

  assign sep_xbar_global_base_o = u_dut.u_smu.sep_global_base_o;
  assign sep_xbar_region_size_o = u_dut.u_smu.sep_region_size_o[31:0];

  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      sep_smn_out_aw_count_o <= '0;
      sep_xbar_in_aw_count_o <= '0;
      sep_xbar_in_aw_user_o  <= '0;
      sep_xbar_in_aw_addr_o  <= '0;
      smc_xbar_in_ar_count_o <= '0;
      smc_xbar_in_aw_count_o <= '0;
    end else begin
      if (u_dut.u_smu.xbar_to_smc_req.ar_valid && u_dut.u_smu.xbar_to_smc_resp.ar_ready) begin
        smc_xbar_in_ar_count_o <= smc_xbar_in_ar_count_o + 32'd1;
      end
      if (u_dut.u_smu.xbar_to_smc_req.aw_valid && u_dut.u_smu.xbar_to_smc_resp.aw_ready) begin
        smc_xbar_in_aw_count_o <= smc_xbar_in_aw_count_o + 32'd1;
      end
      if (u_dut.u_smu.gen_sep.sep_out_xbar_req.aw_valid &&
                u_dut.u_smu.gen_sep.sep_out_xbar_resp.aw_ready) begin
        sep_smn_out_aw_count_o <= sep_smn_out_aw_count_o + 32'd1;
      end
      if (u_dut.u_smu.xbar_to_sep_req.aw_valid && u_dut.u_smu.xbar_to_sep_resp.aw_ready) begin
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
      $fatal(1, "[smu_wrapper_uvm_top] missing SEP boot-ROM image %s", boot_rom_path);
    end
    $fclose(boot_rom_fd);
    $readmemh(boot_rom_path, u_dut.u_sep_ip_integration.u_sep_boot_rom.mem);
    $display("[smu_wrapper_uvm_top] loaded SEP boot ROM from %s", boot_rom_path);
  end

  // ------------------------------------------------------------------
  // DTP / JTAG observation taps -- SEP-independent, and kept in their own
  // block so they stay separate from the sep_* observables above.
  // ------------------------------------------------------------------
  assign rst_cold_stable_ref_clk_no = rst_cold_stable_ref_clk_n;
  assign jtag_boot_stall          = smu_scope_boot_stall_val;
  assign jtag_boot_stall_ovrd     = smu_scope_boot_stall_ovrd;
  assign jtag_ic_reset_ext_ovrd   = ic_reset_ext_w.ovrd;
  assign jtag_ic_reset_ext_ctrl_n = ic_reset_ext_w.val;
  assign jtag_ic_reset_smc_ovrd   = u_dut.u_smu.jtag_smc_reset_ctrl.ovrd.cold_reset_n_ovrd;
  assign jtag_ic_reset_smc_ctrl_n = u_dut.u_smu.jtag_smc_reset_ctrl.val.cold_reset_n_val;
  // The DTP output port, not smu's internal wire between the two instances.
  // That wire is collapsed here, so the XMR reads a constant 0 while the
  // register behind it holds the right value.
  assign smu_scope_boot_stall_val  = u_dut.u_smu.boot_stall_jtag_val;
  assign smu_scope_boot_stall_ovrd = u_dut.u_smu.boot_stall_jtag_ovrd;
  assign tb_stap_io_tck      = stap_io_ctrl_w.tck;
  assign tb_stap_smc_tck     = u_dut.u_smu.dtp_smc_stap_tap_ctrl.tck;
  assign tb_stap_smc_tms     = u_dut.u_smu.dtp_smc_stap_tap_ctrl.tms;
  assign tb_stap_smc_trst_n  = u_dut.u_smu.dtp_smc_stap_tap_ctrl.trst_n;
  assign tb_stap_smc_tdi     = u_dut.u_smu.u_smc.smc_cpu_jtag_TDI_i;
  assign tb_stap_smc_tdo_oen = u_dut.u_smu.u_dtp.jtag_stap_smc_host_tdo_oen_o;
  assign tb_stap_sep_tck     = u_dut.u_smu.dtp_sep_stap_tap_ctrl.tck;
  assign tb_stap_sep_tms     = u_dut.u_smu.dtp_sep_stap_tap_ctrl.tms;
  // smu_wrapper brings out a real bidirectional pad bus -- smc_ip_integration
  // puts a prim_pad_shim on every pin -- so TB stimulus goes onto the wire
  // itself. A weak pull-down on every pad gives an idle pin a defined 0 on a
  // four-state simulator without contending with a core output, which the
  // pad drives at pull strength at its default drive setting. Verilator
  // accepts no strength on the primitive, ignores it and reads an undriven
  // pad as 0, so both simulators see the same idle bus. A pull-up would stall boot: pad 57 is the
  // active-high boot-stall input (smc_padring: boot_stall_o =
  // lsio_pad2core_data[57]).
  for (
      genvar gpio_idx = 0; gpio_idx < smc_pkg::NumGpioWraps; gpio_idx++
  ) begin : gen_gpio_pad_pull
`ifdef VERILATOR
    pulldown u_pad_pulldown (gpio_pad_io[gpio_idx]);
`else
    pulldown (weak0) u_pad_pulldown (gpio_pad_io[gpio_idx]);
`endif
  end

  // One testbench driver per pad: the pin-0 and boot-stall straps merge into
  // the per-pad vectors so no pad carries two continuous assignments.
  logic [smc_pkg::NumGpioWraps-1:0] gpio_pad_drive_en;
  logic [smc_pkg::NumGpioWraps-1:0] gpio_pad_drive_val;

  always_comb begin
    gpio_pad_drive_en      = tb_gpio_drive_en;
    gpio_pad_drive_val     = tb_gpio_drive_val;
    gpio_pad_drive_en[0]   = tb_gpio_drive_en[0] | tb_gpio0_drive_en;
    gpio_pad_drive_val[0]  = tb_gpio0_drive_en ? tb_gpio0_drive_val : tb_gpio_drive_val[0];
    gpio_pad_drive_en[57]  = tb_gpio_drive_en[57] | gpio_boot_stall_drive_i;
    gpio_pad_drive_val[57] = gpio_boot_stall_drive_i ? 1'b1 : tb_gpio_drive_val[57];
  end

  for (genvar gpio_i = 0; gpio_i < int'(smc_pkg::NumGpioWraps); gpio_i++) begin : gen_gpio_drive
    assign gpio_pad_io[gpio_i] = gpio_pad_drive_en[gpio_i] ? gpio_pad_drive_val[gpio_i] : 1'bz;
  end

  // smu.sv does not forward the peripheral-domain primary reset to its own
  // boundary, so read it off the SMC the way tb_top.sv does.
  assign rst_primary_periph_clk_no = u_dut.u_smu.u_smc.rst_primary_periph_clk_no;

  assign dtp_cla_clock_stop_en = u_dut.u_smu.dtp_cla_clock_stop_en;
  assign tb_bsr_select = bsr_ctrl_w.select;
  assign tb_smc_jtag2axi_security_disable =
        u_dut.u_smu.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_jtag2axi_security_disable;
  assign tb_otp_jtag2axi_security_disable =
        u_dut.u_smu.u_dtp.u_jtag_intf_unit.u_jtag_ptap.smc_otp_jtag2axi_security_disable;

  // ------------------------------------------------------------------
  // External SMN AXI4 egress: the shared slave agent answers on u_axi_out_if
  // (cocotb binds the instance); the bridge places the cut's struct port on
  // it. Firmware console / PASS magic is a TB observe snoop on the same
  // wires (SEP sep_outbound_mbx decode), not a second responder.
  // ------------------------------------------------------------------
  localparam logic [31:0] FwStdoutAddr = 32'h8000_0000;
  localparam logic [31:0] FwMagic0 = 32'hA5A5_5A5A;
  localparam logic [31:0] FwMagicPass = 32'hCAFE_BABE;
  localparam logic [31:0] FwMagicFail = 32'hDEAD_BEEF;

  // Register the boundary channels so the responder sees edge-aligned
  // request signals: the crossbar's ext_out aw_valid settles late in the
  // cycle. The cut also keeps the responder's ready out of the crossbar's
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
    .clk_i      (clk_smu),
    .rst_ni     (rst_cold_n_o),
    .slv_req_i  (smu_axi_out_req),
    .slv_resp_o (smu_axi_out_resp),
    .mst_req_o  (axi_out_cut_req),
    .mst_resp_i (axi_out_cut_resp)
  );

  ocah_axi_if u_axi_out_if (
    .aclk    (clk_smu),
    .aresetn (rst_cold_n_o)
  );

  ocah_axi_struct_bridge #(
    .axi_req_t  (smu_axi_xbar_pkg::axi_out_req_t),
    .axi_resp_t (smu_axi_xbar_pkg::axi_out_resp_t)
  ) u_axi_out_bridge (
    .axi_req_i  (axi_out_cut_req),
    .axi_resp_o (axi_out_cut_resp),
    .axi_if     (u_axi_out_if)
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
        (axi_out_cur_awaddr[31:0] == FwStdoutAddr);
  wire [31:0] axi_out_fw_word =
        (smu_axi_out_req.w.strb[7:4] != 4'h0)
            ? smu_axi_out_req.w.data[63:32]
            : smu_axi_out_req.w.data[31:0];

  always_ff @(posedge clk_smu or negedge rst_cold_n_o) begin
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
        smu_axi_out_write_count_o <= smu_axi_out_write_count_o + 32'd1;
      end
      if (axi_out_r_last_fire) begin
        smu_axi_out_read_count_o <= smu_axi_out_read_count_o + 32'd1;
      end

      // Firmware console / PASS magic (SEP sep_outbound_mbx decode) — observe
      // only; the slave agent owns resp.
      if (axi_out_w_fire && axi_out_to_stdout) begin
        if (smu_axi_out_req.w.strb == 8'h01) begin
          fw_char_o       <= smu_axi_out_req.w.data[7:0];
          fw_char_valid_o <= 1'b1;
        end
        if (smu_axi_out_req.w.strb == 8'h0F || smu_axi_out_req.w.strb == 8'hF0) begin
          fw_last_word_o <= axi_out_fw_word;
          // STAGE_BEACON(id) from hw/sys/sep/dv/fw tests: the low
          // nibble carries the stage, so a run reports how far the
          // firmware got even when it never reaches its verdict.
          if (axi_out_fw_word[31:4] == 28'hB1B0B0B) begin
            fw_beacon_mask_o[axi_out_fw_word[3:0]] <= 1'b1;
          end
          if (!fw_magic0_seen_q) begin
            fw_magic0_seen_q <= (axi_out_fw_word == FwMagic0);
          end else if (axi_out_fw_word == FwMagicPass) begin
            fw_done_o        <= 1'b1;
            fw_pass_o        <= 1'b1;
            fw_magic0_seen_q <= 1'b0;
          end else if (axi_out_fw_word == FwMagicFail) begin
            fw_done_o        <= 1'b1;
            fw_pass_o        <= 1'b0;
            fw_magic0_seen_q <= 1'b0;
          end else if (axi_out_fw_word != FwMagic0) begin
            fw_magic0_seen_q <= 1'b0;
          end
        end
      end
    end
  end

  // ------------------------------------------------------------------
  // DUT: hw/top/smu_wrapper (logical ports)
  // ------------------------------------------------------------------
  // TB-owned SEP lockstep stimulus/observation. Initialised: an undriven
  // sep_lockstep_ctrl_i would reach the SEP core as X under RV_LOCKSTEP_ENABLE.
  sep_pkg::sep_lockstep_ctrl_t   sep_lockstep_ctrl_i = '0;
  sep_pkg::sep_lockstep_status_t sep_lockstep_status_o;

  smu_wrapper #(
    .CFG (SmuCfg)
  ) u_dut (
    .entropy_rosc_sample_clk_i,
    .rst_cold_ni,
    .rst_cold_stable_ref_clk_no (rst_cold_stable_ref_clk_n),
    .powergood_i,

    .jtag_ptap_client_tap_ctrl_i (jtag_ptap_client_tap_ctrl),
    .jtag_ptap_client_tdi_i      (jtag_ptap_tdi),
    .jtag_ptap_client_tdo_o      (jtag_ptap_tdo),
    .jtag_ptap_client_tdo_oen_o  (jtag_ptap_tdo_oen),

    .jtag_bsr_host_scan_ctrl_o (bsr_ctrl_w),
    .jtag_bsr_host_scan_in_i   (bsr_scan_loop),
    .jtag_bsr_host_scan_out_o  (bsr_scan_loop),

    .jtag_stap_io_host_tap_ctrl_o (stap_io_ctrl_w),
    .jtag_stap_io_host_tdi_i      (stap_io_tdo_w),
    .jtag_stap_io_host_tdo_o      (stap_io_tdo_w),
    .jtag_stap_io_host_tdo_oen_o  (stap_io_tdo_oen_w),

    .jtag_stap_extra_host_tap_ctrl_o (stap_extra_ctrl_w),
    .jtag_stap_extra_host_tdi_i      (stap_extra_tdi_w),
    .jtag_stap_extra_host_tdo_o      (stap_extra_tdo_w),
    .jtag_stap_extra_host_tdo_oen_o  (stap_extra_tdo_oen_w),

    .jtag_stap_host_scan_ctrl_o (stap_scan_ctrl_w),
    .jtag_stap_host_scan_in_i   (stap_scan_loop),
    .jtag_stap_host_scan_out_o  (stap_scan_loop),

    .jtag_dfd_host_scan_ctrl_o (dfd_ctrl_w),
    .jtag_dfd_host_scan_in_i   (dfd_scan_ret),
    .jtag_dfd_host_scan_out_o  (dfd_scan_loop),

    .jtag_dft_secure_host_scan_ctrl_o (dft_sec_ctrl_w),
    .jtag_dft_secure_host_scan_in_i   (dft_sec_scan_ret),
    .jtag_dft_secure_host_scan_out_o  (dft_sec_scan_loop),

    .jtag_dft_host_scan_ctrl_o (dft_ctrl_w),
    .jtag_dft_host_scan_in_i   (dft_scan_ret),
    .jtag_dft_host_scan_out_o  (dft_scan_loop),

    .dtp_stop_clks_o (dtp_stop_clks_o),
    .jtag_ptap_state_o (jtag_ptap_state),
    .jtag_ptap_inst_decoded_o (jtag_ptap_inst_decoded),
    .jtag_ic_reset_ext_o (ic_reset_ext_w),

    .xtrig_ctm_src_req_o (xtrig_ctm_src_req),
    .xtrig_ctm_src_ack_i (xtrig_ctm_src_ack),
    .xtrig_ctm_dst_req_i (xtrig_ctm_dst_req),
    .xtrig_ctm_dst_ack_o (xtrig_ctm_dst_ack),
    .xtrig_clk_stop_req_i (xtrig_clk_stop_req),

    .xtrig_ctp_req_out_dout_o (ctp_req_out_dout_w),
    .xtrig_ctp_req_out_dout_en_o (ctp_req_out_dout_en_w),
    .xtrig_ctp_req_out_din_i (ctp_req_out_din_w),
    .xtrig_ctp_req_out_din_en_o (ctp_req_out_din_en_w),
    .xtrig_ctp_req_in_dout_o (ctp_req_in_dout_w),
    .xtrig_ctp_req_in_dout_en_o (ctp_req_in_dout_en_w),
    .xtrig_ctp_req_in_din_i (tb_xtrig_ctp_req_in_din),
    .xtrig_ctp_req_in_din_en_o (ctp_req_in_din_en_w),
    .xtrig_ctp_ack_in_dout_o (ctp_ack_in_dout_w),
    .xtrig_ctp_ack_in_dout_en_o (ctp_ack_in_dout_en_w),
    .xtrig_ctp_ack_in_din_i (tb_xtrig_ctp_ack_in_din),
    .xtrig_ctp_ack_in_din_en_o (ctp_ack_in_din_en_w),
    .xtrig_ctp_ack_out_dout_o (ctp_ack_out_dout_w),
    .xtrig_ctp_ack_out_dout_en_o (ctp_ack_out_dout_en_w),
    .xtrig_ctp_ack_out_din_i ('0),
    .xtrig_ctp_ack_out_din_en_o (ctp_ack_out_din_en_w),

    .rst_primary_ref_clk_no (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_no (rst_primary_smc_clk_n),

    .smu_axi_in_req_i  (smu_axi_in_req),
    .smu_axi_in_resp_o (smu_axi_in_resp),
    .smu_axi_out_req_o (smu_axi_out_req),
    .smu_axi_out_resp_i (smu_axi_out_resp),

    .smc_shadow_regs_o (smc_shadow_regs),
    .lsio_interface_select_o (),
    .gpio_pad_io (gpio_pad_io),
    .rst_cool_n_from_pin_i (~tb_cool_reset_pin),

    .clk_telemetry_i (clk_ref),
    .rst_telemetry_ni (rst_cold_ni),
    .telemetry_atdata_i (tel_atdata_w),
    .telemetry_atid_i (tel_atid_w),
    .telemetry_atready_o (tel_atready_w),
    .telemetry_atvalid_i (tel_atvalid_w),
    .telemetry_afvalid_o (tel_afvalid_w),
    .telemetry_afready_i (tel_afready_w),

    .smc_cluster_ded_o (cluster_ded_w),
    .smc_wdt_first_timeout_o (wdt_first_timeout_w),
    .smc_wdt_second_timeout_o (wdt_second_timeout_w),

    .smc_global_base_o (smc_global_base_o),
    .smc_region_size_o (smc_region_size_o),
    .sep_global_base_o (sep_global_base_o),
    .sep_region_size_o (sep_region_size_o),

    .smc_ext_interrupts_i (smc_ext_interrupts_w),
    .smc_fuse_sense_done_o,
    .smc_fuse_reset_n_delayed_o,
    .skip_mem_repair_o (skip_mem_repair_w),
    .ext_boot_seq_done_i (ext_boot_seq_done_i),
    .lc_state_o (lc_state),
    .lc_sigint_err_o (lc_sigint_err_o),
    .smc_ndmreset_request_i (tb_smc_ndmreset_request),
    .smc_ndmreset_process_o (ndmreset_process_w),
    .smc_ext_mailbox_interrupts_o (ext_mailbox_interrupts),

    .cfg_flr_pf_active_i (tb_cfg_flr_pf_active),
    .isolate_req_o (isolate_req_w),
    .ss_reset_complete_i (~tb_ss_reset_incomplete),
    .ss_config_o (ss_config_w),
    .ss_reset_ctrl_o (ss_reset_ctrl_w),
    .sync_irq_o (sync_irq_w),

    .smc_disable_sram_auto_init_i (smc_disable_sram_auto_init),
    .smc_init_mem_done_o,
    .chiplet_is_primary_i (~tb_chiplet_secondary),
    .timer_count_o (tb_timer_count),

    .test_en_i (1'b0),
    .scan_rst_ni (1'b1),

    // No external BISR/MBIST agent on this bench: the done and pass straps
    // read asserted unless a leaf holds them down.
    .mem_repair_done_i (~tb_mem_repair_hold),
    .mem_repair_success_i (~tb_mem_repair_hold),
    .mem_repair_abort_i (tb_mem_repair_abort),
    .mbist_done_i (~tb_mbist_hold),
    .mbist_pass_i (~tb_mbist_hold),
    .mbist_abort_i (tb_mbist_abort),

    .sep_cpu_trace_o (sep_cpu_trace),
    .sep_ext_interrupts_i ('0),
    .lcc_demote_state_1_o (lcc_demote_state_1_o),
    .lcc_demote_state_2_o (lcc_demote_state_2_o),
    .sep_fuse_dft_disable_o (),
    .smc_fuse_dft_disable_o (),
    .sep_fuse_sense_done_o,
    .clk_sep_wdt_i,
    .secure_tm_o (secure_tm_w),
    .secure_tm_req_i (secure_tm_req),

    .ext_debug_bus_i ('0),
    .gpio_interrupt_o (gpio_interrupt_w),
    .uart_interrupt_o (uart_interrupt_w),
    .sep_efuse_debug_bus_o (),
    .smc_efuse_debug_bus_o (),

    // SEP CPU lockstep control/status
    .sep_lockstep_ctrl_i (sep_lockstep_ctrl_i),
    .sep_lockstep_status_o (sep_lockstep_status_o)
  );

  assign clk_smu    = u_dut.clk_sys;
  assign clk_ref    = u_dut.clk_ref;
  assign clk_periph = u_dut.clk_periph;

`ifndef UVM
  // cocotb toggles the model oscillators through the clock inputs, with
  // +pll_osc_bench selecting these nets over pll_wrap's own generators:
  // under Verilator, cocotb observes the pre-edge state only on a clock its
  // own write toggles.
  assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_ref_bench    = clk_ref_i;
  assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_sys_bench    = clk_smu_i;
  assign u_dut.u_smc_ip_integration.u_pll_wrap.osc_periph_bench = clk_periph_i;
`endif

  // ------------------------------------------------------------------
  // Functional coverage (cov/sv/): the same modules tb_top.sv carries, on
  // this bench's names, plus smu_clk_fcov, which needs the hierarchical
  // clock and reset mirrors only this bench exposes. Every port is a signal
  // of this module; the one hierarchical reference, tb_axil_external_active,
  // reads a window smu_wrapper keeps inside itself.
  // ------------------------------------------------------------------
  assign jtag_ptap_state_w = 32'(jtag_ptap_state);
  assign tb_ptap_inst_decoded = jtag_ptap_inst_decoded;

  always_ff @(posedge clk_smu or negedge rst_cold_ni) begin
    if (!rst_cold_ni) begin
      smu_axi_in_awvalid_count  <= '0;
      smu_axi_out_awvalid_count <= '0;
    end else begin
      if (ext_in_awvalid && ext_in_awready) begin
        smu_axi_in_awvalid_count <= smu_axi_in_awvalid_count + 32'd1;
      end
      if (axi_out_aw_fire) begin
        smu_axi_out_awvalid_count <= smu_axi_out_awvalid_count + 32'd1;
      end
    end
  end

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_boot_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_boot_fcov (
    .clk_ref_i                   (clk_ref),
    .clk_smu_i                   (clk_smu),
    .powergood_i                 (powergood_i),
    .rst_cold_ni                 (rst_cold_ni),
    .ext_boot_seq_done_i         (ext_boot_seq_done_i),
    .rst_cold_stable_ref_clk_ni  (rst_cold_stable_ref_clk_no),
    .rst_primary_ref_clk_ni      (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_n_o),
    .rst_primary_periph_clk_ni   (rst_primary_periph_clk_no),
    .init_mem_done_i             (smc_init_mem_done_o),
    .fuse_sense_done_i           (smc_fuse_sense_done_o),
    .fuse_reset_n_delayed_i      (smc_fuse_reset_n_delayed_o),
    .jtag_boot_stall_ovrd_i      (jtag_boot_stall_ovrd),
    .jtag_boot_stall_i           (jtag_boot_stall),
    .gpio_boot_stall_drive_i     (gpio_boot_stall_drive_i),
    .lc_state_i                  (lc_state_o),
    .lc_sigint_err_i             (lc_sigint_err_o),
    .lcc_demote_state_1_i        (lcc_demote_state_1_o),
    .lcc_demote_state_2_i        (lcc_demote_state_2_o)
  );

  // Macro AXI-Lite activity (OR of aw/w/ar valid), as tb_top.sv builds it at
  // its own boundary. smu_wrapper keeps that window inside itself, between
  // the SMC peripheral crossbar and smc_ip_integration, so it is read there.
  assign tb_axil_external_active = u_dut.smc_external_req.aw_valid
                                 | u_dut.smc_external_req.w_valid
                                 | u_dut.smc_external_req.ar_valid;

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_xbar_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_xbar_fcov (
    .clk_smu_i                (clk_smu),
    .rst_cold_ni              (rst_cold_ni),
    .sep_global_base_i        (sep_global_base_o),
    .sep_region_size_i        (sep_region_size_o),
    .smc_global_base_i        (smc_global_base_o),
    .smc_region_size_i        (smc_region_size_o),
    .s_axi_awvalid_i          (ext_in_awvalid),
    .s_axi_awready_i          (ext_in_awready),
    .s_axi_wvalid_i           (ext_in_wvalid),
    .s_axi_wready_i           (ext_in_wready),
    .s_axi_wlast_i            (ext_in_wlast),
    .s_axi_bvalid_i           (ext_in_bvalid),
    .s_axi_bready_i           (ext_in_bready),
    .s_axi_bresp_i            (ext_in_bresp),
    .s_axi_arvalid_i          (ext_in_arvalid),
    .s_axi_arready_i          (ext_in_arready),
    .s_axi_rvalid_i           (ext_in_rvalid),
    .s_axi_rready_i           (ext_in_rready),
    .s_axi_rlast_i            (ext_in_rlast),
    .s_axi_rresp_i            (ext_in_rresp),
    .axi_in_awvalid_count_i   (smu_axi_in_awvalid_count),
    .axi_out_awvalid_count_i  (smu_axi_out_awvalid_count),
    .axil_external_active_i   (tb_axil_external_active)
  );

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_rst_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_rst_fcov (
    .clk_ref_i                   (clk_ref),
    .clk_smu_i                   (clk_smu),
    .clk_periph_i                (clk_periph),
    .powergood_i                 (powergood_i),
    .rst_cold_ni                 (rst_cold_ni),
    .ext_boot_seq_done_i         (ext_boot_seq_done_i),
    .rst_cold_stable_ref_clk_ni  (rst_cold_stable_ref_clk_no),
    .rst_primary_ref_clk_ni      (rst_primary_ref_clk_no),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_n_o),
    .rst_primary_periph_clk_ni   (rst_primary_periph_clk_no),
    .smc_rst_ni                  (obs_smc_rst_n_o),
    .dtp_rst_ni                  (obs_dtp_rst_n_o),
    .sep_rst_ni                  (obs_sep_rst_n_o),
    .xbar_rst_ni                 (obs_xbar_rst_n_o),
    .fuse_sense_done_i           (smc_fuse_sense_done_o),
    .sep_fuse_sense_done_i       (sep_fuse_sense_done_o),
    .fuse_reset_n_delayed_i      (smc_fuse_reset_n_delayed_o),
    .skip_mem_repair_i           (skip_mem_repair_w),
    .init_mem_done_i             (smc_init_mem_done_o),
    .disable_sram_auto_init_i    (smc_disable_sram_auto_init),
    .jtag_ptap_state_i           (jtag_ptap_state_w)
  );

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_clk_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_clk_fcov (
    .clk_smu_i               (clk_smu),
    .rst_primary_smc_clk_ni  (rst_primary_smc_clk_n_o),
    .smc_clk_i               (obs_smc_clk_o),
    .dtp_clk_i               (obs_dtp_clk_o),
    .sep_clk_i               (obs_sep_clk_o),
    .xbar_clk_i              (obs_xbar_clk_o),
    .smc_rst_ni              (obs_smc_rst_n_o),
    .dtp_rst_ni              (obs_dtp_rst_n_o),
    .sep_rst_ni              (obs_sep_rst_n_o),
    .xbar_rst_ni             (obs_xbar_rst_n_o),
    .tel_clk_i               (obs_smc_tel_clk_o),
    .sep_wdt_clk_i           (obs_sep_wdt_clk_o)
  );

  smu_lc_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_lc_fcov (
    .clk_smu_i                (clk_smu),
    .rst_cold_ni              (rst_cold_ni),
    .rst_primary_smc_clk_ni   (rst_primary_smc_clk_n_o),
    .lc_state_i               (lc_state_o),
    .lcc_demote_state_1_i     (lcc_demote_state_1_o),
    .lcc_demote_state_2_i     (lcc_demote_state_2_o),
    .sep_global_base_i        (sep_global_base_o),
    .sep_region_size_i        (sep_region_size_o),
    .sep_fuse_sense_done_i    (sep_fuse_sense_done_o)
  );

  smu_dtp_fcov u_smu_dtp_fcov (
    .clk_smu_i                  (clk_smu),
    .rst_cold_ni                (rst_cold_ni),
    .rst_primary_smc_clk_ni     (rst_primary_smc_clk_n_o),
    .jtag_ic_reset_ext_ovrd_i   (jtag_ic_reset_ext_ovrd),
    .jtag_ic_reset_ext_ctrl_n_i (jtag_ic_reset_ext_ctrl_n),
    .ctp_req_out_dout_i         (ctp_req_out_dout_w),
    .ctp_req_in_dout_i          (ctp_req_in_dout_w),
    .ctp_ack_in_dout_i          (ctp_ack_in_dout_w),
    .ctp_ack_out_dout_i         (ctp_ack_out_dout_w)
  );

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_ext_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_ext_fcov (
    .clk_smu_i                (clk_smu),
    .rst_cold_ni              (rst_cold_ni),
    .rst_primary_smc_clk_ni   (rst_primary_smc_clk_n_o),
    .fuse_sense_done_i        (smc_fuse_sense_done_o),
    .s_axi_awvalid_i          (ext_in_awvalid),
    .s_axi_awready_i          (ext_in_awready),
    .s_axi_awid_i             (ext_in_awid),
    .axi_out_aw_valid_i       (smu_axi_out_req.aw_valid),
    .axi_out_aw_ready_i       (smu_axi_out_resp.aw_ready),
    .axi_out_aw_id_i          (smu_axi_out_req.aw.id),
    .smc_efuse_bank_ctrl_awvalid_i (u_dut.smc_efuse_bank_ctrl_req.aw_valid),
    .smc_efuse_bank_ctrl_arvalid_i (u_dut.smc_efuse_bank_ctrl_req.ar_valid),
    .smc_efuse_bank_ctrl_bvalid_i  (u_dut.smc_efuse_bank_ctrl_resp.b_valid),
    .smc_efuse_bank_ctrl_bready_i  (u_dut.smc_efuse_bank_ctrl_req.b_ready),
    .smc_efuse_bank_ctrl_rvalid_i  (u_dut.smc_efuse_bank_ctrl_resp.r_valid),
    .smc_efuse_bank_ctrl_rready_i  (u_dut.smc_efuse_bank_ctrl_req.r_ready),
    .sep_efuse_bank_ctrl_awvalid_i (u_dut.sep_efuse_bank_ctrl_req.aw_valid),
    .sep_efuse_bank_ctrl_arvalid_i (u_dut.sep_efuse_bank_ctrl_req.ar_valid),
    .sep_efuse_bank_ctrl_bvalid_i  (u_dut.sep_efuse_bank_ctrl_resp.b_valid),
    .sep_efuse_bank_ctrl_bready_i  (u_dut.sep_efuse_bank_ctrl_req.b_ready),
    .sep_efuse_bank_ctrl_rvalid_i  (u_dut.sep_efuse_bank_ctrl_resp.r_valid),
    .sep_efuse_bank_ctrl_rready_i  (u_dut.sep_efuse_bank_ctrl_req.r_ready),
    .ext_mailbox_interrupts_i (ext_mailbox_interrupts),
    .ss_config_i              (ss_config_w),
    .ss_reset_ctrl_i          (ss_reset_ctrl_w),
    .smc_shadow_regs_i        (smc_shadow_regs)
  );

  // ------------------------------------------------------------------
  // P1 families. The three DTP debug bridges and the cross-trigger
  // clock-stop inputs are nets inside `smu`, so they are read here and the
  // cov/sv modules take plain wires.
  // ------------------------------------------------------------------
  smu_clkstop_fcov u_smu_clkstop_fcov (
    .clk_smu_i               (clk_smu),
    .rst_primary_smc_clk_ni  (rst_primary_smc_clk_n_o),
    .dtp_clk_stop_req_ext_i  (u_dut.u_smu.dtp_xtrig_clk_stop_req[8:1]),
    .jtag_clock_stop_i       (u_dut.u_smu.u_dtp.jtag_clock_stop),
    .dtp_stop_clks_i         (dtp_stop_clks_o)
  );

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_dbg_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_dbg_fcov (
    .clk_smu_i                   (clk_smu),
    .rst_primary_smc_clk_ni      (rst_primary_smc_clk_n_o),
    .smc_dbg_awvalid_i           (u_dut.u_smu.dtp_axi_smc_dbg_req.aw_valid),
    .smc_dbg_arvalid_i           (u_dut.u_smu.dtp_axi_smc_dbg_req.ar_valid),
    .smc_dbg_bvalid_i            (u_dut.u_smu.dtp_axi_smc_dbg_resp.b_valid),
    .smc_dbg_bready_i            (u_dut.u_smu.dtp_axi_smc_dbg_req.b_ready),
    .smc_dbg_bresp_i             (u_dut.u_smu.dtp_axi_smc_dbg_resp.b.resp),
    .smc_dbg_rvalid_i            (u_dut.u_smu.dtp_axi_smc_dbg_resp.r_valid),
    .smc_dbg_rready_i            (u_dut.u_smu.dtp_axi_smc_dbg_req.r_ready),
    .smc_dbg_rlast_i             (u_dut.u_smu.dtp_axi_smc_dbg_resp.r.last),
    .smc_dbg_rresp_i             (u_dut.u_smu.dtp_axi_smc_dbg_resp.r.resp),
    .smc_otp_bvalid_i            (u_dut.u_smu.dtp_axil_smc_otp_jtag_resp.b_valid),
    .smc_otp_bready_i            (u_dut.u_smu.dtp_axil_smc_otp_jtag_req.b_ready),
    .smc_otp_bresp_i             (u_dut.u_smu.dtp_axil_smc_otp_jtag_resp.b.resp),
    .smc_otp_rvalid_i            (u_dut.u_smu.dtp_axil_smc_otp_jtag_resp.r_valid),
    .smc_otp_rready_i            (u_dut.u_smu.dtp_axil_smc_otp_jtag_req.r_ready),
    .smc_otp_rresp_i             (u_dut.u_smu.dtp_axil_smc_otp_jtag_resp.r.resp),
    .sep_otp_bvalid_i            (u_dut.u_smu.dtp_axil_sep_otp_jtag_resp.b_valid),
    .sep_otp_bready_i            (u_dut.u_smu.dtp_axil_sep_otp_jtag_req.b_ready),
    .sep_otp_bresp_i             (u_dut.u_smu.dtp_axil_sep_otp_jtag_resp.b.resp),
    .sep_otp_rvalid_i            (u_dut.u_smu.dtp_axil_sep_otp_jtag_resp.r_valid),
    .sep_otp_rready_i            (u_dut.u_smu.dtp_axil_sep_otp_jtag_req.r_ready),
    .sep_otp_rresp_i             (u_dut.u_smu.dtp_axil_sep_otp_jtag_resp.r.resp),
    .dbg_disable_smc_jtag2axi_i  (u_dut.u_smu.sep_dbg_disable.smc_jtag2axi),
    .dbg_disable_smc_otp_i       (u_dut.u_smu.sep_dbg_disable.smc_otp_jtag2axi),
    .dbg_disable_sep_otp_i       (u_dut.u_smu.sep_dbg_disable.sep_otp_jtag2axi)
  );

  // The SEP-to-SMC dedicated port and the crossbar SEP initiator port are
  // inside the SEP=1 generate branch, so the no-SEP profile ties the alias
  // observation nets off and the points stay unhit there.
  logic alias_awvalid_w, alias_awready_w, alias_arvalid_w, alias_arready_w;
  logic alias_bvalid_w, alias_bready_w, alias_rvalid_w, alias_rready_w, alias_rlast_w;
  logic [55:0] alias_awaddr_w, alias_araddr_w;
  logic xbar_sep_out_awvalid_w, xbar_sep_out_awready_w;
  logic xbar_sep_out_arvalid_w, xbar_sep_out_arready_w;
  logic [55:0] xbar_sep_out_awaddr_w, xbar_sep_out_araddr_w;

  assign alias_awvalid_w = u_dut.u_smu.sep_ext_to_smc_axi_req.aw_valid;
  assign alias_awready_w = u_dut.u_smu.sep_ext_to_smc_axi_resp.aw_ready;
  assign alias_awaddr_w = 56'(u_dut.u_smu.sep_ext_to_smc_axi_req.aw.addr);
  assign alias_arvalid_w = u_dut.u_smu.sep_ext_to_smc_axi_req.ar_valid;
  assign alias_arready_w = u_dut.u_smu.sep_ext_to_smc_axi_resp.ar_ready;
  assign alias_araddr_w = 56'(u_dut.u_smu.sep_ext_to_smc_axi_req.ar.addr);
  assign alias_bvalid_w = u_dut.u_smu.sep_ext_to_smc_axi_resp.b_valid;
  assign alias_bready_w = u_dut.u_smu.sep_ext_to_smc_axi_req.b_ready;
  assign alias_rvalid_w = u_dut.u_smu.sep_ext_to_smc_axi_resp.r_valid;
  assign alias_rready_w = u_dut.u_smu.sep_ext_to_smc_axi_req.r_ready;
  assign alias_rlast_w = u_dut.u_smu.sep_ext_to_smc_axi_resp.r.last;
  assign xbar_sep_out_awvalid_w = u_dut.u_smu.gen_sep.sep_out_xbar_req.aw_valid;
  assign xbar_sep_out_awready_w = u_dut.u_smu.gen_sep.sep_out_xbar_resp.aw_ready;
  assign xbar_sep_out_awaddr_w = 56'(u_dut.u_smu.gen_sep.sep_out_xbar_req.aw.addr);
  assign xbar_sep_out_arvalid_w = u_dut.u_smu.gen_sep.sep_out_xbar_req.ar_valid;
  assign xbar_sep_out_arready_w = u_dut.u_smu.gen_sep.sep_out_xbar_resp.ar_ready;
  assign xbar_sep_out_araddr_w = 56'(u_dut.u_smu.gen_sep.sep_out_xbar_req.ar.addr);

  // SEP_PRESENT drops the SEP-only points on the no-SEP elaboration.
  smu_alias_fcov #(
    .SEP_PRESENT(SmuCfg.SEP)
  ) u_smu_alias_fcov (
    .clk_smu_i                 (clk_smu),
    .rst_primary_smc_clk_ni    (rst_primary_smc_clk_n_o),
    .smc_global_base_i         (56'(u_dut.u_smu.smc_global_base_o)),
    .smc_region_size_i         (u_dut.u_smu.smc_region_size_o),
    .alias_awvalid_i           (alias_awvalid_w),
    .alias_awready_i           (alias_awready_w),
    .alias_awaddr_i            (alias_awaddr_w),
    .alias_arvalid_i           (alias_arvalid_w),
    .alias_arready_i           (alias_arready_w),
    .alias_araddr_i            (alias_araddr_w),
    .alias_bvalid_i            (alias_bvalid_w),
    .alias_bready_i            (alias_bready_w),
    .alias_rvalid_i            (alias_rvalid_w),
    .alias_rready_i            (alias_rready_w),
    .alias_rlast_i             (alias_rlast_w),
    .xbar_sep_out_awvalid_i    (xbar_sep_out_awvalid_w),
    .xbar_sep_out_awready_i    (xbar_sep_out_awready_w),
    .xbar_sep_out_awaddr_i     (xbar_sep_out_awaddr_w),
    .xbar_sep_out_arvalid_i    (xbar_sep_out_arvalid_w),
    .xbar_sep_out_arready_i    (xbar_sep_out_arready_w),
    .xbar_sep_out_araddr_i     (xbar_sep_out_araddr_w)
  );


`ifdef UVM
  // ------------------------------------------------------------------
  // SV-UVM harness (`--dut smu --framework uvm`): clocks, the shared JTAG
  // VIP interface on the primary TAP pins, the SMU-local TB interface, the
  // embedded DTP's TB interface (so the DTP bench's reference models and
  // checkers attach unchanged), a passive AXI interface mirroring the DTP's
  // SMC-fabric JTAG2AXI port, the JTAG protocol SVA, quiescent tie-offs for
  // every other cocotb-driven stimulus pin, uvm_config_db publication of the
  // virtual interfaces (u_axi_out_if lives above, in both shapes), and
  // run_test(). Compiled only when the native uvm flow defines UVM; the
  // cocotb flow sees only the ported module above.
  // ------------------------------------------------------------------
  import uvm_pkg::*;

  smu_tb_if u_tb_if ();
  dtp_tb_if u_dtp_tb_if ();
  ocah_jtag_if u_jtag_if ();

  // The model free-runs under SV-UVM (+pll_sys_period_ns selects the sys
  // period; the test cfg reads the same plusarg); the bench-side clock nets
  // mirror it. The SEP watchdog clock keeps the period the env publishes on
  // smu_tb_if; TCK is bit-banged by the VIP driver. The ESRC sample clock
  // stays static: no SV-UVM scenario drives the entropy stack.
  assign clk_smu_i    = clk_smu;
  assign clk_ref_i    = clk_ref;
  assign clk_periph_i = clk_periph;
  initial begin
    clk_sep_wdt_i             = 1'b0;
    entropy_rosc_sample_clk_i = 1'b0;
  end
  always #(u_tb_if.sep_wdt_clk_period_ns * 0.5ns) clk_sep_wdt_i = ~clk_sep_wdt_i;
  assign u_tb_if.clk_smu = clk_smu_i;
  assign u_tb_if.clk_ref = clk_ref_i;

  // Power-good, cold reset, the boot-sequence gate and the GPIO boot-stall
  // pad are test-sequenced through smu_tb_if; the reset-unit, fuse-sense,
  // lifecycle and DTP debug-control observables are mirrored back for the
  // sequences, the monitors and the reference models.
  assign powergood_i             = u_tb_if.powergood;
  assign rst_cold_ni             = u_tb_if.rst_cold_n;
  assign ext_boot_seq_done_i     = u_tb_if.ext_boot_seq_done;
  assign gpio_boot_stall_drive_i = u_tb_if.gpio_boot_stall_drive;
  assign u_tb_if.rst_cold_stable_ref_clk_n    = rst_cold_stable_ref_clk_no;
  assign u_tb_if.rst_primary_ref_clk_n        = rst_primary_ref_clk_no;
  assign u_tb_if.rst_primary_smc_clk_n        = rst_primary_smc_clk_n_o;
  assign u_tb_if.rst_primary_periph_clk_n     = rst_primary_periph_clk_no;
  assign u_tb_if.fuse_sense_done              = smc_fuse_sense_done_o;
  assign u_tb_if.fuse_reset_n_delayed         = smc_fuse_reset_n_delayed_o;
  assign u_tb_if.lc_state                     = lc_state_o;
  assign u_tb_if.jtag_boot_stall              = jtag_boot_stall;
  assign u_tb_if.jtag_boot_stall_ovrd         = jtag_boot_stall_ovrd;
  assign u_tb_if.jtag_ic_reset_ext_ovrd       = jtag_ic_reset_ext_ovrd;
  assign u_tb_if.jtag_ic_reset_ext_ctrl_n     = jtag_ic_reset_ext_ctrl_n;
  assign u_tb_if.jtag_ic_reset_smc_ovrd       = jtag_ic_reset_smc_ovrd;
  assign u_tb_if.jtag_ic_reset_smc_ctrl_n     = jtag_ic_reset_smc_ctrl_n;
  assign u_tb_if.smc_reset_ctrl_ovrd          = u_dut.u_smu.jtag_smc_reset_ctrl.ovrd;
  assign u_tb_if.smc_reset_ctrl_val           = u_dut.u_smu.jtag_smc_reset_ctrl.val;
  assign u_tb_if.smc_jtag2axi_security_disable = tb_smc_jtag2axi_security_disable;
  assign u_tb_if.dtp_stop_clks                = dtp_stop_clks_o;

  // Cold-reset assertion counter (reference models re-baseline on it).
  logic [31:0] cold_rst_assert_count = '0;
  always @(negedge rst_cold_ni) cold_rst_assert_count <= cold_rst_assert_count + 32'd1;
  assign u_tb_if.cold_rst_assert_count = cold_rst_assert_count;

  // Primary JTAG TAP: TB drives tck/tms/trst_n/tdi, DUT drives tdo/tdo_oen.
  assign jtag_tck  = u_jtag_if.tck;
  assign jtag_tms  = u_jtag_if.tms;
  assign jtag_trst = u_jtag_if.trst_n;
  assign jtag_tdi  = u_jtag_if.tdi;
  assign u_jtag_if.tdo     = jtag_tdo;
  assign u_jtag_if.tdo_oen = jtag_tdo_oen;

  // Embedded DTP through its own TB interface, wired the way the DTP bench
  // wires its top: the one-hot TAP state and decoded instruction the DUT
  // exports, the assertion counters of the DTP's system and power-on
  // resets observed on the DTP instance pins (pwr_on_rst_ni is the SMC
  // reset unit's powergood_stable; rst_n_i is the primary smc-clock reset),
  // and the debug-disable vector the SEP lifecycle controller hands the DTP,
  // which gates the JTAG2AXI bridges the reference models predict.
  logic [31:0] dtp_sys_rst_assert_count = '0;
  logic [31:0] dtp_por_assert_count     = '0;
  always @(negedge u_dut.u_smu.u_dtp.rst_n_i)
    dtp_sys_rst_assert_count <= dtp_sys_rst_assert_count + 32'd1;
  always @(negedge u_dut.u_smu.u_dtp.pwr_on_rst_ni)
    dtp_por_assert_count <= dtp_por_assert_count + 32'd1;
  assign u_dtp_tb_if.tap_state            = 16'(jtag_ptap_state);
  assign u_dtp_tb_if.inst_decoded         = jtag_ptap_inst_decoded;
  assign u_dtp_tb_if.sys_rst_assert_count = dtp_sys_rst_assert_count;
  assign u_dtp_tb_if.por_assert_count     = dtp_por_assert_count;
  always @* u_dtp_tb_if.drive_dbg_disable(u_dut.u_smu.sep_dbg_disable);

  // Clean-room JTAG protocol SVA checker (ocah_jtag_vip/sva) on the primary
  // TAP pins + the exported one-hot TAP state, enabled via smu_tb_if.
  ocah_jtag_sva #(
    .EN_STATE_RULES(1'b1)
  ) u_jtag_ptap_sva (
    .tck         (jtag_tck),
    .tms         (jtag_tms),
    .tdi         (jtag_tdi),
    .trst_n      (jtag_trst),
    .tdo         (jtag_tdo),
    .tdo_oen     (jtag_tdo_oen),
    .en_i        (u_tb_if.jtag_sva_en),
    .tap_state_i (16'(jtag_ptap_state))
  );

  // The DTP's SMC-fabric JTAG2AXI port (smu.dtp_axi_smc_dbg_req/resp, an
  // internal struct link), mirrored onto a shared-VIP interface the env
  // observes with a passive monitor; nothing drives it from here. The
  // interface keeps its default maximum widths; the env config carries the
  // port geometry.
  ocah_axi_if u_dtp_smc_dbg_if (
    .aclk    (clk_smu_i),
    .aresetn (rst_primary_smc_clk_n_o)
  );
  assign u_dtp_smc_dbg_if.awid     = 16'(u_dut.u_smu.dtp_axi_smc_dbg_req.aw.id);
  assign u_dtp_smc_dbg_if.awaddr   = 64'(u_dut.u_smu.dtp_axi_smc_dbg_req.aw.addr);
  assign u_dtp_smc_dbg_if.awlen    = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.len;
  assign u_dtp_smc_dbg_if.awsize   = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.size;
  assign u_dtp_smc_dbg_if.awburst  = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.burst;
  assign u_dtp_smc_dbg_if.awlock   = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.lock;
  assign u_dtp_smc_dbg_if.awcache  = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.cache;
  assign u_dtp_smc_dbg_if.awprot   = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.prot;
  assign u_dtp_smc_dbg_if.awqos    = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.qos;
  assign u_dtp_smc_dbg_if.awregion = u_dut.u_smu.dtp_axi_smc_dbg_req.aw.region;
  assign u_dtp_smc_dbg_if.awuser   = 16'(u_dut.u_smu.dtp_axi_smc_dbg_req.aw.user);
  assign u_dtp_smc_dbg_if.awvalid  = u_dut.u_smu.dtp_axi_smc_dbg_req.aw_valid;
  assign u_dtp_smc_dbg_if.awready  = u_dut.u_smu.dtp_axi_smc_dbg_resp.aw_ready;
  assign u_dtp_smc_dbg_if.wdata    = u_dut.u_smu.dtp_axi_smc_dbg_req.w.data;
  assign u_dtp_smc_dbg_if.wstrb    = u_dut.u_smu.dtp_axi_smc_dbg_req.w.strb;
  assign u_dtp_smc_dbg_if.wlast    = u_dut.u_smu.dtp_axi_smc_dbg_req.w.last;
  assign u_dtp_smc_dbg_if.wuser    = 16'(u_dut.u_smu.dtp_axi_smc_dbg_req.w.user);
  assign u_dtp_smc_dbg_if.wvalid   = u_dut.u_smu.dtp_axi_smc_dbg_req.w_valid;
  assign u_dtp_smc_dbg_if.wready   = u_dut.u_smu.dtp_axi_smc_dbg_resp.w_ready;
  assign u_dtp_smc_dbg_if.bid      = 16'(u_dut.u_smu.dtp_axi_smc_dbg_resp.b.id);
  assign u_dtp_smc_dbg_if.bresp    = u_dut.u_smu.dtp_axi_smc_dbg_resp.b.resp;
  assign u_dtp_smc_dbg_if.buser    = 16'(u_dut.u_smu.dtp_axi_smc_dbg_resp.b.user);
  assign u_dtp_smc_dbg_if.bvalid   = u_dut.u_smu.dtp_axi_smc_dbg_resp.b_valid;
  assign u_dtp_smc_dbg_if.bready   = u_dut.u_smu.dtp_axi_smc_dbg_req.b_ready;
  assign u_dtp_smc_dbg_if.arid     = 16'(u_dut.u_smu.dtp_axi_smc_dbg_req.ar.id);
  assign u_dtp_smc_dbg_if.araddr   = 64'(u_dut.u_smu.dtp_axi_smc_dbg_req.ar.addr);
  assign u_dtp_smc_dbg_if.arlen    = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.len;
  assign u_dtp_smc_dbg_if.arsize   = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.size;
  assign u_dtp_smc_dbg_if.arburst  = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.burst;
  assign u_dtp_smc_dbg_if.arlock   = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.lock;
  assign u_dtp_smc_dbg_if.arcache  = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.cache;
  assign u_dtp_smc_dbg_if.arprot   = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.prot;
  assign u_dtp_smc_dbg_if.arqos    = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.qos;
  assign u_dtp_smc_dbg_if.arregion = u_dut.u_smu.dtp_axi_smc_dbg_req.ar.region;
  assign u_dtp_smc_dbg_if.aruser   = 16'(u_dut.u_smu.dtp_axi_smc_dbg_req.ar.user);
  assign u_dtp_smc_dbg_if.arvalid  = u_dut.u_smu.dtp_axi_smc_dbg_req.ar_valid;
  assign u_dtp_smc_dbg_if.arready  = u_dut.u_smu.dtp_axi_smc_dbg_resp.ar_ready;
  assign u_dtp_smc_dbg_if.rid      = 16'(u_dut.u_smu.dtp_axi_smc_dbg_resp.r.id);
  assign u_dtp_smc_dbg_if.rdata    = u_dut.u_smu.dtp_axi_smc_dbg_resp.r.data;
  assign u_dtp_smc_dbg_if.rresp    = u_dut.u_smu.dtp_axi_smc_dbg_resp.r.resp;
  assign u_dtp_smc_dbg_if.rlast    = u_dut.u_smu.dtp_axi_smc_dbg_resp.r.last;
  assign u_dtp_smc_dbg_if.ruser    = 16'(u_dut.u_smu.dtp_axi_smc_dbg_resp.r.user);
  assign u_dtp_smc_dbg_if.rvalid   = u_dut.u_smu.dtp_axi_smc_dbg_resp.r_valid;
  assign u_dtp_smc_dbg_if.rready   = u_dut.u_smu.dtp_axi_smc_dbg_req.r_ready;

  // ------------------------------------------------------------------
  // Quiescent tie-offs: every other cocotb-driven stimulus pin at the idle
  // value the cocotb smu_base_test bring-up sets (drive_idle_inputs). A
  // scenario that needs one of these pins promotes it into smu_tb_if;
  // nothing here is driven from class code.
  // ------------------------------------------------------------------

  // ESRC raw noise quiet (no entropy scenario in this shape).
  assign esrc_noise_ext_i = '0;

  // External SMN AXI4 ingress: no initiator attached, request side idle
  // (single-beat INCR shape, no valids, no readies).
  assign ext_in_awvalid  = 1'b0;
  assign ext_in_awid     = '0;
  assign ext_in_awaddr   = '0;
  assign ext_in_awlen    = '0;
  assign ext_in_awsize   = 3'd3;
  assign ext_in_awburst  = 2'b01;
  assign ext_in_awuser   = '0;
  assign ext_in_awlock   = 1'b0;
  assign ext_in_awcache  = '0;
  assign ext_in_awprot   = '0;
  assign ext_in_awqos    = '0;
  assign ext_in_awregion = '0;
  assign ext_in_wuser    = '0;
  assign ext_in_wvalid   = 1'b0;
  assign ext_in_wdata    = '0;
  assign ext_in_wstrb    = '0;
  assign ext_in_wlast    = 1'b1;
  assign ext_in_bready   = 1'b0;
  assign ext_in_arvalid  = 1'b0;
  assign ext_in_arid     = '0;
  assign ext_in_araddr   = '0;
  assign ext_in_arlen    = '0;
  assign ext_in_arsize   = 3'd3;
  assign ext_in_arburst  = 2'b01;
  assign ext_in_aruser   = '0;
  assign ext_in_arlock   = 1'b0;
  assign ext_in_arcache  = '0;
  assign ext_in_arprot   = '0;
  assign ext_in_arqos    = '0;
  assign ext_in_arregion = '0;
  assign ext_in_rready   = 1'b0;

  // Cross-trigger CTM loopback and clock-stop requests idle.
  assign xtrig_ctm_dst_req  = '0;
  assign xtrig_ctm_src_ack  = '0;
  assign xtrig_clk_stop_req = 1'b0;

  // Telemetry ATB channel 0 idle.
  assign tb_telemetry_atdata  = '0;
  assign tb_telemetry_atid    = '0;
  assign tb_telemetry_atvalid = '0;
  assign tb_telemetry_afready = '0;

  // SMC boundary controls idle.
  assign tb_smc_ext_interrupts   = '0;
  assign tb_smc_ndmreset_request = '0;
  assign tb_cfg_flr_pf_active    = 1'b0;
  assign tb_mem_repair_abort     = 1'b0;
  assign tb_mbist_abort          = 1'b0;
  assign tb_mem_repair_hold      = 1'b0;
  assign tb_mbist_hold           = 1'b0;
  assign tb_ss_reset_incomplete  = '0;
  assign tb_chiplet_secondary    = 1'b0;
  assign tb_cool_reset_pin       = 1'b0;
  assign tb_secure_tm_req        = 1'b0;
  assign tb_smc_sram_auto_init_restore = 1'b0;

  // GPIO pads undriven by the bench (the boot-stall pad follows smu_tb_if).
  assign tb_gpio0_drive_en  = 1'b0;
  assign tb_gpio0_drive_val = 1'b0;
  assign tb_gpio_drive_en   = '0;
  assign tb_gpio_drive_val  = '0;

  // CT_Req_out wire-OR board: every private wire and the group wire rest
  // at the pull-up of the reset-default INVERT=0, no chiplet pulling.
  assign tb_xtrig_ctp_wire_pull       = '1;
  assign tb_xtrig_ctp_wire_ext_assert = '0;
  assign tb_xtrig_ctp_wire_group      = '0;
  assign tb_xtrig_ctp_wire_group_pull = 1'b1;
  assign tb_xtrig_ctp_req_in_din      = '0;
  assign tb_xtrig_ctp_ack_in_din      = '0;

  // Under UVM the simulator reports an assertion failure through the UVM
  // report server, where it counts as an error of the run, so the SEP checks
  // the cocotb flow ignores through [pass_fail] in smu_sim_cfg.toml are held
  // off here by the same names: the entropy source and the EDN endpoints, the
  // key manager, the secure DMA and its alert receivers (blocks the wrapper
  // leaves never program), the SPI host for the first microsecond of X before
  // its reset completes, the ValidDigestModeFlag_A of the SHA-256-only
  // prim_sha2_32 instances of the eFuse token processing, and otbn_rnd's
  // UrndNoReseedOnReset_A. Every other SEP assertion fails the run.
  `define SMU_TB_SEP u_dut.u_smu.gen_sep.u_sep
  `define SMU_TB_SEP_TOKEN_SHA(inst) \
    `SMU_TB_SEP.u_sep_crypto.u_sep_efuse_wrapper.u_efuse_interface_controller \
    .gen_mmr_reg.u_efuse_token_processing.inst.u_prim_sha2_32.gen_sha256_logic.u_prim_sha2_256
  initial begin
    $assertoff(0, `SMU_TB_SEP.u_sep_crypto.u_sep_trng);
    $assertoff(0, `SMU_TB_SEP.u_sep_crypto.u_axis_edn_crypto_s3c_scan);
    $assertoff(0, `SMU_TB_SEP.u_sep_crypto.u_axis_edn_pool_s3c_scan);
    $assertoff(0, `SMU_TB_SEP.u_sep_crypto.u_key_manager_s3c_scan);
    $assertoff(0, `SMU_TB_SEP.u_sep_dma_wrap.u_secure_dma);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_rma_sip_token).ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_rma_sip_token).u_pad.ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_rma_chiplet_token).ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_rma_chiplet_token).u_pad.ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_sec_disable_token).ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP_TOKEN_SHA(u_sha256_sec_disable_token).u_pad.ValidDigestModeFlag_A);
    $assertoff(0, `SMU_TB_SEP.u_sep_crypto.u_sep_crypto_otbn_wrapper_s3c_scan.u_otbn.u_otbn_core
                  .u_otbn_rnd.UrndNoReseedOnReset_A);
    $assertoff(0, `SMU_TB_SEP.u_sep_io.u_sep_ot_spi_wrap.u_spi_host);
    #1us;
    $asserton(0, `SMU_TB_SEP.u_sep_io.u_sep_ot_spi_wrap.u_spi_host);
  end
  for (genvar i = 0; i < secure_dma_reg_pkg::NumAlerts; i++) begin : gen_sep_dma_alert_off
    initial $assertoff(0, `SMU_TB_SEP.u_sep_dma_wrap.gen_alert_receivers[i].u_alert_receiver);
  end
  `undef SMU_TB_SEP_TOKEN_SHA
  `undef SMU_TB_SEP

  // Test classes (one per scenario) and the base test.
  `include "smu_tests.sv"

  initial begin
    uvm_config_db#(virtual smu_tb_if)::set(null, "*", "tb_vif", u_tb_if);
    uvm_config_db#(virtual dtp_tb_if)::set(null, "*", "dtp_tb_vif", u_dtp_tb_if);
    uvm_config_db#(virtual ocah_jtag_if)::set(null, "*", "jtag_vif", u_jtag_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "axi_out_vif", u_axi_out_if);
    uvm_config_db#(virtual ocah_axi_if)::set(null, "*", "dtp_smc_dbg_vif", u_dtp_smc_dbg_if);
    run_test();
  end
`endif

  assign clk_smu_o    = clk_smu;
  assign clk_ref_o    = clk_ref;
  assign clk_periph_o = clk_periph;

endmodule : smu_wrapper_uvm_top
