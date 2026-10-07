// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP SV-UVM environment: composes, drives nothing, checks no protocol. It
// reads dtp_env_cfg and the DTP-local dtp_tb_if from uvm_config_db, sets
// the harness clock period on the TB interface, fills one shared-VIP config
// per port (interface, geometry, name_tag, evidence policy) and publishes
// it to that agent's subtree, and builds:
//
//   * the active ocah_jtag_master_env on the primary TAP (the VIP's
//     commercial-overridable unit) and the dtp_virtual_sequencer that
//     exposes its sequencer to the scenario virtual sequences;
//   * the active ocah_axi_master_env driving the XTRIG CSR AXI-Lite port;
//   * one memory-backed, fault-capable ocah_axi_slave_agent per JTAG2AXI
//     bridge (SMC OTP and SEP OTP AXI-Lite, SMC fabric AXI4), reached only
//     through the responder sequences on the virtual sequencer;
//   * one passive ocah_axi_env per observed port (monitor, reference model,
//     scoreboard, evidence; monitor-only on the XTRIG CSR port, whose
//     volatile status and reset-cleared selects the memory-shadow model
//     cannot describe: the DTP scoreboard's xtrig_csr feature owns that),
//     each bridge port's stream also feeding a dtp_axi_port_history that
//     counts the port's completed transactions and keeps the newest of each
//     direction for the JTAG2AXI sequences;
//   * one ocah_jtag_slave_agent per STAP host port as the downstream TAP the
//     tests may splice behind it (dtp_scan_if.stap_<x>_ds_en; default keeps
//     the wire loopback), with the device map from dtp_types;
//   * one dtp_<feature>_ref_model per scoreboard feature, each a subscriber
//     on the monitor stream its feature is judged on (the JTAG event and
//     scan streams, the XTRIG monitor stream, the three bridge port
//     streams) publishing expected items, and the always-on dtp_scoreboard
//     that pairs them with the observed streams; the dtp_tap_fsm_checker
//     subscriber, the scan-window monitor, the VIP scan builder, and the
//     env-owned aggregate ocah_jtag_checker finalized once in check_phase.
//
// The cocotb twin is env/dtp_env.py.

class dtp_env extends ocah_env;
  `uvm_component_utils(dtp_env)

  dtp_env_cfg                   cfg;
  virtual dtp_tb_if             tb_vif;
  virtual dtp_scan_if           scan_vif;
  virtual dtp_xtrig_if          xtrig_vif;

  // Primary TAP: shared VIP master env on the ocah_jtag_if published by tb_top.
  ocah_jtag_master_config       m_jtag_cfg;
  ocah_jtag_master_env          m_jtag_env;

  // Always-on checking: one reference model per scoreboard feature, the
  // scoreboard that pairs them, TAP FSM subscriber, scan-window monitor,
  // VIP scan reconstruction, aggregate JTAG evidence.
  dtp_ir_decode_ref_model       m_ir_decode_ref_model;
  dtp_idcode_ref_model          m_idcode_ref_model;
  dtp_bypass_ref_model          m_bypass_ref_model;
  dtp_xtrig_csr_ref_model       m_xtrig_csr_ref_model;
  dtp_xtrig_decode_ref_model    m_xtrig_decode_ref_model;
  dtp_jtag2axi_req_ref_model    m_jtag2axi_req_ref_model;
  dtp_jtag2axi_status_ref_model m_jtag2axi_status_ref_model;
  dtp_scoreboard                m_scoreboard;
  dtp_tap_fsm_checker           m_fsm_checker;
  dtp_scan_window_monitor       m_scan_window;
  dtp_jtag_scan_builder         m_scan_builder;
  ocah_jtag_checker             m_jtag_checker;

  // Virtual sequencer every scenario pass runs on.
  dtp_virtual_sequencer         m_vseqr;

  // Passive shared-VIP AXI observation, one cfg+env per observed port.
  ocah_axi_config               m_smc_otp_axi_cfg;
  ocah_axi_env                  m_smc_otp_axi_env;
  ocah_axi_config               m_sep_otp_axi_cfg;
  ocah_axi_env                  m_sep_otp_axi_env;
  ocah_axi_config               m_smc_axi_cfg;
  ocah_axi_env                  m_smc_axi_env;
  ocah_axi_config               m_xtrig_axi_cfg;
  ocah_axi_env                  m_xtrig_axi_env;

  // Completed-transaction history per bridge port, keyed by target name.
  dtp_axi_port_history          m_axi_port_history[string];

  // Active shared-VIP AXI master: the XTRIG CSR AXI-Lite initiator.
  ocah_axi_master_config        m_xtrig_master_cfg;
  ocah_axi_master_env           m_xtrig_master_env;

  // Active shared-VIP slave agents: the memory-backed responders.
  ocah_axi_slave_config         m_smc_otp_slave_cfg;
  ocah_axi_slave_agent          m_smc_otp_slave_agent;
  ocah_axi_slave_config         m_sep_otp_slave_cfg;
  ocah_axi_slave_agent          m_sep_otp_slave_agent;
  ocah_axi_slave_config         m_smc_axi_slave_cfg;
  ocah_axi_slave_agent          m_smc_axi_slave_agent;

  // Downstream STAP TAP devices, indexed per dtp_stap_ds_name().
  ocah_jtag_slave_config        m_stap_ds_cfg               [DtpStapCount];
  ocah_jtag_slave_agent         m_stap_ds_agent             [DtpStapCount];

  function new(string name = "dtp_env", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(dtp_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "dtp_env_cfg `env_cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual dtp_tb_if)::get(this, "", "tb_vif", tb_vif))
      `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not found in uvm_config_db")
    if (!uvm_config_db#(virtual dtp_scan_if)::get(this, "", "scan_vif", scan_vif))
      `uvm_fatal(get_type_name(), "virtual dtp_scan_if `scan_vif` not found in uvm_config_db")
    if (!uvm_config_db#(virtual dtp_xtrig_if)::get(this, "", "xtrig_vif", xtrig_vif))
      `uvm_fatal(get_type_name(), "virtual dtp_xtrig_if `xtrig_vif` not found in uvm_config_db")
    tb_vif.clk_period_ns = cfg.clk_period_ns;
    `uvm_info(get_type_name(), {"env cfg: ", cfg.convert2string()}, UVM_MEDIUM)
    // The transcribed port count and the generated CT_DST_SELECT field must
    // describe the same matrix: one select bit per CTM port.
    if (DtpCtmSelectMask !== 32'((64'h1 << DtpXtrigNumCtmPorts) - 64'h1))
      `uvm_fatal(get_type_name(), $sformatf(
                 "CT_DST_SELECT mask 0x%0h does not cover %0d CTM ports",
                 DtpCtmSelectMask,
                 DtpXtrigNumCtmPorts
                 ))

    build_jtag_master();
    build_checking();
    m_vseqr = dtp_virtual_sequencer::type_id::create("m_vseqr", this);

    m_smc_otp_axi_cfg = build_bridge_port("smc_otp");
    m_smc_otp_axi_env = ocah_axi_env::type_id::create("m_smc_otp_axi_env", this);
    m_sep_otp_axi_cfg = build_bridge_port("sep_otp");
    m_sep_otp_axi_env = ocah_axi_env::type_id::create("m_sep_otp_axi_env", this);
    m_smc_axi_cfg = build_bridge_port("smc_axi");
    m_smc_axi_env = ocah_axi_env::type_id::create("m_smc_axi_env", this);
    // Monitor only: the memory-shadow reference model cannot describe the
    // XTRIG CSR block (volatile status reads, reset-cleared selects,
    // DECERR on unmapped decode); the DTP scoreboard's xtrig_csr feature
    // owns the readback contract on this stream.
    m_xtrig_axi_cfg = build_passive_axi(
        '{
            name: "m_xtrig_axi",
            vif_key: "xtrig_axil_vif",
            name_tag: "dtp_xtrig_axil",
            protocol: OCAH_AXI_PROTO_AXI4_LITE,
            addr_width: DtpXtrigCsrAddrWidth,
            data_width: DtpXtrigCsrDataWidth,
            id_width: 0
        },
        cfg.axi_policy_for(
            "xtrig"
        ),
        .en_scoreboard(1'b0)
    );
    m_xtrig_axi_env = ocah_axi_env::type_id::create("m_xtrig_axi_env", this);

    build_xtrig_master();

    m_smc_otp_slave_cfg = build_axi_slave(dtp_j2a_port("smc_otp", 1'b1));
    m_smc_otp_slave_agent = ocah_axi_slave_agent::type_id::create("m_smc_otp_slave_agent", this);
    m_sep_otp_slave_cfg = build_axi_slave(dtp_j2a_port("sep_otp", 1'b1));
    m_sep_otp_slave_agent = ocah_axi_slave_agent::type_id::create("m_sep_otp_slave_agent", this);
    m_smc_axi_slave_cfg = build_axi_slave(dtp_j2a_port("smc_axi", 1'b1));
    m_smc_axi_slave_agent = ocah_axi_slave_agent::type_id::create("m_smc_axi_slave_agent", this);
    // The bridge carries response USER across its CDC and never reads it,
    // so any value is legal; seeded draws toggle every bit of that path.
    m_smc_axi_slave_cfg.randomize_resp_user(cfg.resp_user_seed);

    for (int unsigned i = 0; i < DtpStapCount; i++) build_stap_ds(i);
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    // Virtual sequencer: agent sequencers and responder sequences.
    m_vseqr.m_jtag_seqr         = m_jtag_env.m_sequencer;
    m_vseqr.m_xtrig_seqr        = m_xtrig_master_env.m_sequencer;
    m_vseqr.m_smc_otp_slave_seq = m_smc_otp_slave_agent.seq;
    m_vseqr.m_sep_otp_slave_seq = m_sep_otp_slave_agent.seq;
    m_vseqr.m_smc_axi_slave_seq = m_smc_axi_slave_agent.seq;
    for (int unsigned i = 0; i < DtpStapCount; i++) begin
      m_vseqr.m_stap_ds_seq[i] =
          ocah_jtag_slave_sequence::type_id::create({"m_stap_", dtp_stap_ds_name(i), "_ds_seq"});
      m_vseqr.m_stap_ds_seq[i].responder = m_stap_ds_agent[i].m_driver;
      m_vseqr.m_stap_ds_seq[i].evidence = m_jtag_checker;
    end
    // Monitor streams into the always-on subscribers.
    m_jtag_env.event_ap.connect(m_fsm_checker.analysis_export);
    m_jtag_env.event_ap.connect(m_scan_builder.analysis_export);
    m_jtag_env.event_ap.connect(m_scan_window.analysis_export);
    connect_scoreboard();
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    m_fsm_checker.report_evidence();
    m_jtag_checker.finalize(cfg.jtag_policy.require_checks);
  endfunction

  // The passive cfg, evidence recorder, and reference model of the bridge
  // port named `target` (smc_otp, sep_otp, smc_axi).
  function void axi_bundle(string target, output ocah_axi_config cfg,
                           output ocah_axi_checker evidence, output ocah_axi_ref_model ref_model);
    ocah_axi_env port_env;
    case (target)
      "smc_otp": begin
        cfg      = m_smc_otp_axi_cfg;
        port_env = m_smc_otp_axi_env;
      end
      "sep_otp": begin
        cfg      = m_sep_otp_axi_cfg;
        port_env = m_sep_otp_axi_env;
      end
      "smc_axi": begin
        cfg      = m_smc_axi_cfg;
        port_env = m_smc_axi_env;
      end
      default: `uvm_fatal(get_type_name(), {"unknown JTAG2AXI bridge ", target})
    endcase
    evidence  = port_env.m_checker;
    ref_model = port_env.m_ref_model;
  endfunction

  // ------------------------------------------------------------------
  // Composition helpers (build_phase).
  // ------------------------------------------------------------------

  protected function void build_jtag_master();
    m_jtag_cfg = ocah_jtag_master_config::type_id::create("m_jtag_cfg");
    if (!uvm_config_db#(virtual ocah_jtag_if)::get(this, "", "jtag_vif", m_jtag_cfg.vif))
      `uvm_fatal(get_type_name(), "virtual ocah_jtag_if `jtag_vif` not found in uvm_config_db")
    m_jtag_cfg.is_active       = UVM_ACTIVE;
    m_jtag_cfg.en_monitor      = 1'b1;  // DTP checking rides the OCAH event stream
    m_jtag_cfg.tck_half_period = cfg.tck_half_period_ns * 1ns;
    uvm_config_db#(ocah_jtag_master_config)::set(this, "m_jtag_env*", "cfg", m_jtag_cfg);
    m_jtag_env = ocah_jtag_master_env::type_id::create("m_jtag_env", this);
  endfunction

  protected function void build_checking();
    m_jtag_checker              = ocah_jtag_checker::type_id::create("m_jtag_checker");
    m_jtag_checker.name_tag     = "dtp_jtag";
    m_jtag_checker.required_ids = cfg.jtag_policy.required_ids;

    build_reference_models();
    m_scoreboard = dtp_scoreboard::type_id::create("m_scoreboard", this);
    m_scoreboard.tb_vif = tb_vif;

    m_fsm_checker = dtp_tap_fsm_checker::type_id::create("m_fsm_checker", this);
    m_fsm_checker.tb_vif = tb_vif;
    m_fsm_checker.evidence = m_jtag_checker;
    m_fsm_checker.require_activity = cfg.jtag_activity_required;

    m_scan_window = dtp_scan_window_monitor::type_id::create("m_scan_window", this);
    m_scan_window.scan_vif   = scan_vif;
    m_scan_window.tb_vif     = tb_vif;
    m_scan_window.jtag_vif   = m_jtag_cfg.vif;
    m_scan_window.tck_period = 2 * m_jtag_cfg.tck_half_period;

    begin
      dtp_jtag_scan_builder builder = dtp_jtag_scan_builder::type_id::create(
          "m_scan_builder", this
      );
      builder.tb_vif = tb_vif;
      m_scan_builder = builder;
    end

    m_axi_port_history["smc_otp"] =
        dtp_axi_port_history::type_id::create("m_smc_otp_port_history", this);
    m_axi_port_history["sep_otp"] =
        dtp_axi_port_history::type_id::create("m_sep_otp_port_history", this);
    m_axi_port_history["smc_axi"] =
        dtp_axi_port_history::type_id::create("m_smc_axi_port_history", this);
  endfunction

  // One reference model per scoreboard feature; each reads the TB
  // interface for the observables and reset counters it re-baselines on.
  protected function void build_reference_models();
    m_ir_decode_ref_model = dtp_ir_decode_ref_model::type_id::create("m_ir_decode_ref_model", this);
    m_ir_decode_ref_model.tb_vif = tb_vif;
    m_idcode_ref_model = dtp_idcode_ref_model::type_id::create("m_idcode_ref_model", this);
    m_idcode_ref_model.tb_vif = tb_vif;
    m_bypass_ref_model = dtp_bypass_ref_model::type_id::create("m_bypass_ref_model", this);
    m_bypass_ref_model.tb_vif = tb_vif;
    m_xtrig_csr_ref_model = dtp_xtrig_csr_ref_model::type_id::create("m_xtrig_csr_ref_model", this);
    m_xtrig_csr_ref_model.tb_vif = tb_vif;
    m_xtrig_csr_ref_model.negative = cfg.xtrig_csr_ref_model_negative;
    m_xtrig_decode_ref_model =
        dtp_xtrig_decode_ref_model::type_id::create("m_xtrig_decode_ref_model", this);
    m_xtrig_decode_ref_model.negative = cfg.xtrig_decode_ref_model_negative;
    m_jtag2axi_req_ref_model =
        dtp_jtag2axi_req_ref_model::type_id::create("m_jtag2axi_req_ref_model", this);
    m_jtag2axi_req_ref_model.tb_vif = tb_vif;
    m_jtag2axi_req_ref_model.negative = cfg.jtag2axi_ref_model_negative;
    if (cfg.jtag2axi_ref_model_negative)
      `uvm_info(get_type_name(),
                "NEGATIVE VALIDATION: jtag2axi_req reference model predicts corrupted addresses",
                UVM_LOW)
    m_jtag2axi_status_ref_model =
        dtp_jtag2axi_status_ref_model::type_id::create("m_jtag2axi_status_ref_model", this);
    m_jtag2axi_status_ref_model.tb_vif = tb_vif;
  endfunction

  // Every scoreboard feature: the observed monitor stream into its
  // reference model and into the scoreboard's observed export, the
  // reference model's expected items into the scoreboard's expected
  // export. The bridge models also learn which monitor publishes each
  // bridge port and consume every completion those monitors publish.
  protected function void connect_scoreboard();
    // ir_decode: events commit the instruction; IR scans supply it; the
    // observation is dtp_tb_if.inst_decoded, sampled by the scoreboard.
    m_jtag_env.event_ap.connect(m_ir_decode_ref_model.analysis_export);
    m_scan_builder.scan_ap.connect(m_ir_decode_ref_model.scan_export);
    m_ir_decode_ref_model.expected_ap.connect(m_scoreboard.ir_decode_expected_export);
    // idcode, bypass: DR scans judged under the tracked instruction.
    m_scan_builder.scan_ap.connect(m_idcode_ref_model.analysis_export);
    m_jtag_env.event_ap.connect(m_idcode_ref_model.event_export);
    m_idcode_ref_model.expected_ap.connect(m_scoreboard.idcode_expected_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.idcode_observed_export);
    m_scan_builder.scan_ap.connect(m_bypass_ref_model.analysis_export);
    m_jtag_env.event_ap.connect(m_bypass_ref_model.event_export);
    m_bypass_ref_model.expected_ap.connect(m_scoreboard.bypass_expected_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.bypass_observed_export);
    // xtrig_csr, xtrig_decode: the XTRIG CSR port's monitor stream.
    m_xtrig_axi_env.item_ap.connect(m_xtrig_csr_ref_model.analysis_export);
    m_xtrig_csr_ref_model.expected_ap.connect(m_scoreboard.xtrig_csr_expected_export);
    m_xtrig_axi_env.item_ap.connect(m_scoreboard.xtrig_csr_observed_export);
    m_xtrig_axi_env.item_ap.connect(m_xtrig_decode_ref_model.analysis_export);
    m_xtrig_decode_ref_model.expected_ap.connect(m_scoreboard.xtrig_decode_expected_export);
    m_xtrig_axi_env.item_ap.connect(m_scoreboard.xtrig_decode_observed_export);
    // jtag2axi_req, jtag2axi_status: requests from the scan stream, the
    // instruction from the event stream, completions from the bridge
    // ports.
    m_scan_builder.scan_ap.connect(m_jtag2axi_req_ref_model.analysis_export);
    m_jtag_env.event_ap.connect(m_jtag2axi_req_ref_model.event_export);
    m_jtag2axi_req_ref_model.expected_ap.connect(m_scoreboard.jtag2axi_req_expected_export);
    m_scan_builder.scan_ap.connect(m_jtag2axi_status_ref_model.analysis_export);
    m_jtag_env.event_ap.connect(m_jtag2axi_status_ref_model.event_export);
    m_jtag2axi_status_ref_model.expected_ap.connect(m_scoreboard.jtag2axi_status_expected_export);
    m_scan_builder.scan_ap.connect(m_scoreboard.jtag2axi_status_observed_export);
    connect_bridge_port("smc_otp", m_smc_otp_axi_env);
    connect_bridge_port("sep_otp", m_sep_otp_axi_env);
    connect_bridge_port("smc_axi", m_smc_axi_env);
  endfunction

  protected function void connect_bridge_port(string target, ocah_axi_env port_env);
    string source = port_env.m_monitor.get_full_name();
    m_jtag2axi_req_ref_model.bind_port(target, source);
    m_jtag2axi_status_ref_model.bind_port(target, source);
    m_scoreboard.bind_port(target, source);
    port_env.item_ap.connect(m_jtag2axi_req_ref_model.axi_export);
    port_env.item_ap.connect(m_jtag2axi_status_ref_model.axi_export);
    port_env.item_ap.connect(m_scoreboard.jtag2axi_req_observed_export);
    port_env.item_ap.connect(m_axi_port_history[target].analysis_export);
  endfunction

  // One passive shared-VIP AXI observer: geometry, identity, evidence
  // policy, and its interface, published to the `<name>_env*` subtree.
  protected function ocah_axi_config build_passive_axi(
      dtp_axi_port_t port, dtp_evidence_policy_t policy, bit en_scoreboard = 1'b1);
    ocah_axi_config c = ocah_axi_config::type_id::create({port.name, "_cfg"});
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", port.vif_key, c.vif))
      `uvm_fatal(get_type_name(), {
                 "virtual ocah_axi_if `", port.vif_key, "` not found in uvm_config_db"})
    c.protocol       = port.protocol;
    c.addr_width     = port.addr_width;
    c.data_width     = port.data_width;
    c.id_width       = port.id_width;
    c.name_tag       = port.name_tag;
    c.en_scoreboard  = en_scoreboard;
    c.require_checks = policy.require_checks;
    c.required_ids   = policy.required_ids;
    uvm_config_db#(ocah_axi_config)::set(this, {port.name, "_env*"}, "cfg", c);
    return c;
  endfunction

  // The passive observer of JTAG2AXI bridge `target`'s port.
  protected function ocah_axi_config build_bridge_port(string target);
    return build_passive_axi(dtp_j2a_port(target, 1'b0), cfg.axi_policy_for(target));
  endfunction

  // One memory-backed responder: the TB wires the master-driven signals
  // into its interface and the agent's driver answers.
  protected function ocah_axi_slave_config build_axi_slave(dtp_axi_port_t port);
    ocah_axi_slave_config c = ocah_axi_slave_config::type_id::create({port.name, "_cfg"});
    if (!uvm_config_db#(virtual ocah_axi_if)::get(this, "", port.vif_key, c.vif))
      `uvm_fatal(get_type_name(), {
                 "virtual ocah_axi_if `", port.vif_key, "` not found in uvm_config_db"})
    c.protocol   = port.protocol;
    c.addr_width = port.addr_width;
    c.data_width = port.data_width;
    c.id_width   = port.id_width;
    c.mem_bytes  = cfg.axi_mem_bytes;
    c.name_tag   = port.name_tag;
    uvm_config_db#(ocah_axi_slave_config)::set(this, {port.name, "_agent*"}, "slave_cfg", c);
    return c;
  endfunction

  protected function void build_xtrig_master();
    m_xtrig_master_cfg = ocah_axi_master_config::type_id::create("m_xtrig_master_cfg");
    if (!uvm_config_db#(virtual ocah_axi_if)::get(
            this, "", "xtrig_master_vif", m_xtrig_master_cfg.vif
        ))
      `uvm_fatal(get_type_name(),
                 "virtual ocah_axi_if `xtrig_master_vif` not found in uvm_config_db")
    m_xtrig_master_cfg.protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    m_xtrig_master_cfg.addr_width = DtpXtrigCsrAddrWidth;
    m_xtrig_master_cfg.data_width = DtpXtrigCsrDataWidth;
    m_xtrig_master_cfg.id_width   = 0;
    m_xtrig_master_cfg.name_tag   = "dtp_xtrig_master";
    uvm_config_db#(ocah_axi_master_config)::set(this, "m_xtrig_master_env*", "cfg",
                                                m_xtrig_master_cfg);
    m_xtrig_master_env = ocah_axi_master_env::type_id::create("m_xtrig_master_env", this);
  endfunction

  // One downstream STAP TAP device on the ocah_jtag_if tb_top wires from
  // the port's forwarded tck/tms/trst_n and TDO. No passive monitor: the
  // composed-chain scans span the whole network, so per-device scan
  // reconstruction carries no checkable width; the evidence is the
  // device's own state and Update-DR history through its slave sequence.
  protected function void build_stap_ds(int unsigned i);
    string nm = dtp_stap_ds_name(i);
    m_stap_ds_cfg[i] = ocah_jtag_slave_config::type_id::create({"m_stap_", nm, "_ds_cfg"});
    if (!uvm_config_db#(virtual ocah_jtag_if)::get(
            this, "", {"stap_", nm, "_ds_vif"}, m_stap_ds_cfg[i].vif
        ))
      `uvm_fatal(get_type_name(), $sformatf(
                 "virtual ocah_jtag_if `stap_%s_ds_vif` not found in uvm_config_db", nm))
    m_stap_ds_cfg[i].is_active     = UVM_ACTIVE;
    m_stap_ds_cfg[i].en_monitor    = 1'b0;
    m_stap_ds_cfg[i].ir_width      = DtpStapDsIrWidth;
    m_stap_ds_cfg[i].idcode        = dtp_stap_ds_idcode(i);
    // The STAP host port has no downstream tdo_oen input.
    m_stap_ds_cfg[i].drive_tdo_oen = 1'b0;
    m_stap_ds_cfg[i].add_reg(DtpStapDsTdrName, DtpStapDsTdrOpcode, dtp_stap_ds_tdr_width(i), 1'b1);
    uvm_config_db#(ocah_jtag_slave_config)::set(this, {"m_stap_", nm, "_ds_agent*"}, "slave_cfg",
                                                m_stap_ds_cfg[i]);
    m_stap_ds_agent[i] = ocah_jtag_slave_agent::type_id::create({"m_stap_", nm, "_ds_agent"}, this);
  endfunction

endclass : dtp_env
