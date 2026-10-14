// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP base test (ocah_test realization): builds the two configuration
// levels and the environment, walks the reset ladder, and runs every
// scenario as a virtual sequence on the environment's virtual sequencer
// through the library's looped-scenario runner.
//
//   1. build dtp_test_cfg: seed and random volume from the library
//      accessors, the knob-derived controls, the downstream STAP attach
//      mask and the host segment attach, then the test's
//      configure_test_cfg() hook (required scoreboard features, evidence
//      policy); srandom(seed) + randomize() draws the system-clock and TCK
//      periods;
//   2. derive dtp_env_cfg from it and publish both through uvm_config_db;
//      build dtp_env;
//   3. bring_up(): route the downstream STAP TAPs and the host segment,
//      then sequence power-on and system reset through dtp_tb_if in clock
//      cycles of the randomized period; run_looped_scenario() (ocah_test)
//      then starts create_scenario_seq() on m_env.m_vseqr once per pass
//      with scenario_seed = seed + pass.
//
// Knobs (plusargs here, environment variables in the cocotb twin
// tests/dtp_base_test.py): +<specific>=N per test, +<group>=N per group,
// +DTP_TEST_LOOPS=N suite-wide, +DTP_RANDOM_COUNT=N random volume per
// pass; the scenario knobs and negative-validation switches are read into
// dtp_test_cfg (read_knobs). The pass banner comes from ocah_test.

class dtp_base_test extends ocah_test;
  `uvm_component_utils(dtp_base_test)

  dtp_test_cfg test_cfg;
  dtp_env_cfg  env_cfg;
  dtp_env      m_env;

  function new(string name = "dtp_base_test", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    test_cfg = dtp_test_cfg::type_id::create("test_cfg");
    test_cfg.seed         = base_seed();
    test_cfg.random_count = random_count();
    test_cfg.read_knobs();
    test_cfg.stap_ds_attach_mask = stap_ds_attach_mask();
    test_cfg.stap_host_segment_attach = stap_host_segment_attach();
    configure_test_cfg(test_cfg);
    // The one draw before run_phase: the bench-level dimensions (clock
    // and TCK periods) come from the runner seed through srandom(), so a
    // run replays from the seed alone.
    test_cfg.srandom(test_cfg.seed);
    if (!test_cfg.randomize()) `uvm_fatal(get_type_name(), "dtp_test_cfg randomize() failed")
    `uvm_info(get_type_name(), {"test cfg: ", test_cfg.convert2string()}, UVM_LOW)
    env_cfg = dtp_env_cfg::from_test_cfg(test_cfg);
    uvm_config_db#(dtp_test_cfg)::set(this, "*", "test_cfg", test_cfg);
    uvm_config_db#(dtp_env_cfg)::set(this, "*", "env_cfg", env_cfg);
    m_env = dtp_env::type_id::create("m_env", this);
  endfunction

  // ------------------------------------------------------------------
  // Configuration hooks.
  // ------------------------------------------------------------------

  // Scenario tests add their required scoreboard features and the
  // required evidence IDs of the recorders they exercise.
  virtual function void configure_test_cfg(dtp_test_cfg cfg);
  endfunction

  // Downstream STAP TAP attachment (cocotb dtp_base_test.stap_ds_attach
  // parity): bit i selects the STAP host port in dtp_stap_ds_name() order
  // (io, smc, sep, extra0) that gets the shared ocah_jtag_vip slave device
  // spliced behind it for this test. Default: every port keeps its wire
  // loopback; the STAP-selection and zero-length-bypass scenarios attach all
  // four.
  virtual function bit [DtpStapCount-1:0] stap_ds_attach_mask();
    return '0;
  endfunction

  // Extended STAP host segment (cocotb dtp_base_test.stap_host_segment
  // parity): 1 places the tb_top host segment behind the extended STAP host
  // scan interface for this test. Default: the host scan loopback; the
  // extended-STAP scenario attaches it.
  virtual function bit stap_host_segment_attach();
    return 1'b0;
  endfunction

  virtual function string suite_loops_knob();
    return "DTP_TEST_LOOPS";
  endfunction

  virtual function string random_count_knob();
    return "DTP_RANDOM_COUNT";
  endfunction

  // ------------------------------------------------------------------
  // Looped-scenario hooks.
  // ------------------------------------------------------------------

  virtual function uvm_sequencer_base scenario_sequencer();
    return m_env.m_vseqr;
  endfunction

  // Standard handle plumbing for every scenario pass; scenario-specific
  // handles are added by the thin tests, which call super first.
  virtual function void plumb_scenario_seq(ocah_sequence seq);
    dtp_base_test_seq dtp_seq;
    dtp_scan_base_test_seq scan_seq;
    dtp_jtag2axi_base_test_seq j2a_seq;
    if (!$cast(dtp_seq, seq))
      `uvm_fatal(get_type_name(), "scenario sequence is not a dtp_base_test_seq")
    dtp_seq.tb_vif       = m_env.tb_vif;
    dtp_seq.scan_vif     = m_env.scan_vif;
    dtp_seq.xtrig_vif    = m_env.xtrig_vif;
    dtp_seq.test_cfg     = test_cfg;
    dtp_seq.evidence     = m_env.m_jtag_checker;
    dtp_seq.scan_builder = m_env.m_scan_builder;
    dtp_seq.scan_window  = m_env.m_scan_window;
    dtp_seq.fsm_checker  = m_env.m_fsm_checker;
    if ($cast(scan_seq, seq)) plumb_stap_ds(scan_seq);
    if ($cast(j2a_seq, seq)) plumb_jtag2axi(j2a_seq);
  endfunction

  // Hand a JTAG2AXI sequence every bridge's port history and evidence
  // bundle, keyed by bridge name; the sequence selects the bridge it judges.
  virtual function void plumb_jtag2axi(dtp_jtag2axi_base_test_seq seq);
    seq.axi_ports = m_env.m_axi_port_history;
    foreach (m_env.m_axi_port_history[name]) begin
      ocah_axi_uvm_pkg::ocah_axi_config    cfg;
      ocah_axi_uvm_pkg::ocah_axi_checker   evidence;
      ocah_axi_uvm_pkg::ocah_axi_ref_model ref_model;
      m_env.axi_bundle(name, cfg, evidence, ref_model);
      seq.target_cfgs[name]       = cfg;
      seq.target_evidence[name]   = evidence;
      seq.target_ref_models[name] = ref_model;
    end
  endfunction

  // Hand a scan sequence the downstream device configurations the scan
  // reference model is seeded from, which ports are attached, and whether
  // the host segment is; the responder sequences come from the virtual
  // sequencer.
  virtual function void plumb_stap_ds(dtp_scan_base_test_seq seq);
    for (int unsigned i = 0; i < DtpStapCount; i++) begin
      seq.stap_ds_cfg[i]      = m_env.m_stap_ds_cfg[i];
      seq.stap_ds_attached[i] = test_cfg.stap_ds_attach_mask[i];
    end
    seq.stap_host_segment_attached = test_cfg.stap_host_segment_attach;
  endfunction

  // Fresh scan-reconstruction window per pass: the builder's bounded
  // history would otherwise saturate across passes and freeze
  // the newest-scan-length evidence on a stale item (the cocotb flow
  // likewise starts a fresh monitor per pass).
  virtual function void pre_scenario_pass(int unsigned idx);
    m_env.m_scan_builder.clear_scan_history();
  endfunction

  // Clock/reset bring-up (cocotb bring_up parity): route the downstream
  // STAP TAPs, then sequence POR and system reset through dtp_tb_if with
  // the startup dbg_disable vector cleared while POR is still asserted, so
  // scenario passes begin with full debug access and assert the disables
  // they gate explicitly. The reset ladder holds the only wall-clock waits
  // in test code, derived from the randomized clock period.
  virtual task bring_up();
    attach_stap_ds();
    m_env.tb_vif.drive_dbg_disable('0);
    m_env.tb_vif.por_rst_n   <= 1'b0;
    m_env.tb_vif.sys_rst_n   <= 1'b0;
    wait_clk_cycles(dtp_base_test_seq::PorHoldCycles);
    m_env.tb_vif.por_rst_n <= 1'b1;
    wait_clk_cycles(dtp_base_test_seq::SysResetHoldCycles);
    m_env.tb_vif.sys_rst_n <= 1'b1;
    wait_clk_cycles(dtp_base_test_seq::PostResetCycles);
  endtask

  // Route each selected STAP host port to its downstream device and the
  // extended STAP host scan to the host segment (the dtp_scan_if enables
  // feed the tb_top muxes) before bring-up, so the attachment is static for
  // the whole run.
  protected function void attach_stap_ds();
    bit [DtpStapCount-1:0] mask = test_cfg.stap_ds_attach_mask;
    m_env.scan_vif.stap_io_ds_en     = mask[0];
    m_env.scan_vif.stap_smc_ds_en    = mask[1];
    m_env.scan_vif.stap_sep_ds_en    = mask[2];
    m_env.scan_vif.stap_extra0_ds_en = mask[3];
    m_env.scan_vif.stap_host_seg_en  = test_cfg.stap_host_segment_attach;
    if (mask != '0)
      `uvm_info(get_type_name(), $sformatf(
                "downstream STAP TAPs attached: mask=0b%04b (io,smc,sep,extra0)", mask), UVM_LOW)
    if (test_cfg.stap_host_segment_attach)
      `uvm_info(get_type_name(), "host segment attached behind the extended STAP host scan",
                UVM_LOW)
  endfunction

  protected task wait_clk_cycles(int unsigned cycles);
    #(cycles * env_cfg.clk_period_ns * 1ns);
  endtask

endclass : dtp_base_test
