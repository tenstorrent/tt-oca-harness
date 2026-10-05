// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// In-order expected/observed pairing scoreboard with named CHK-* evidence.
//
// The monitor's observed stream and the reference model's expected stream
// arrive in the same completion order, so pairing is strictly in order; a
// try-compare runs whenever both queues are non-empty (analysis subscriber
// invocation order is unordered, so either stream may arrive first).
//
// Per pair:
//   CHK-AXI-RESP        worst observed response equals the model expectation
//                       (an armed non-OKAY appears here as expected=observed)
//   CHK-AXI-ERR-INJ     an armed expectation was consumed by a real non-OKAY
//                       (negative-path non-vacuity; tests add it to
//                       required_ids)
//   CHK-AXI-RDATA       read data equals the model's predicted readback
//                       (expected-OKAY reads only)
//   CHK-AXI-BEATS       observed beat count equals AxLEN+1
//   CHK-AXI-ADDR-ALIGN  address aligned to the transfer size
//
// check_phase drains (unpaired items are errors) and finalizes the evidence
// core exactly once (zero-check rejection gated by cfg.require_checks).

`uvm_analysis_imp_decl(_ocah_axi_observed)
`uvm_analysis_imp_decl(_ocah_axi_expected)

class ocah_axi_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(ocah_axi_scoreboard)

  ocah_axi_config cfg;
  ocah_axi_checker m_checker;

  uvm_analysis_imp_ocah_axi_observed #(ocah_axi_item, ocah_axi_scoreboard) observed_export;
  uvm_analysis_imp_ocah_axi_expected #(ocah_axi_item, ocah_axi_scoreboard) expected_export;

  protected ocah_axi_item m_observed_q[$];
  protected ocah_axi_item m_expected_q[$];
  int unsigned pair_count;

  function new(string name = "ocah_axi_scoreboard", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_config `cfg` not found in uvm_config_db")
    observed_export = new("observed_export", this);
    expected_export = new("expected_export", this);
    m_checker = ocah_axi_checker::type_id::create("m_checker");
    m_checker.name_tag = cfg.name_tag;
  endfunction

  function void write_ocah_axi_observed(ocah_axi_item t);
    m_observed_q.push_back(t);
    try_compare();
  endfunction

  function void write_ocah_axi_expected(ocah_axi_item t);
    m_expected_q.push_back(t);
    try_compare();
  endfunction

  protected function void try_compare();
    while (m_observed_q.size() > 0 && m_expected_q.size() > 0) begin
      ocah_axi_item observed = m_observed_q.pop_front();
      ocah_axi_item expected = m_expected_q.pop_front();
      compare_pair(observed, expected);
    end
  endfunction

  protected function bit [63:0] strb_lane_mask(bit [7:0] strb);
    bit [63:0] mask = '0;
    for (int unsigned lane = 0; lane < 8; lane++) begin
      if (strb[lane]) mask[8*lane+:8] = 8'hFF;
    end
    return mask;
  endfunction

  protected function string pair_context(ocah_axi_item observed);
    return $sformatf(
        "%s %s addr=0x%0h beats=%0d id=0x%0h",
        observed.protocol.name(),
        observed.direction.name(),
        observed.address,
        observed.beat_count(),
        observed.transaction_id
    );
  endfunction

  protected function void compare_pair(ocah_axi_item observed, ocah_axi_item expected);
    string context_s = pair_context(observed);
    bit [63:0] observed_resps[$];
    bit [63:0] expected_resps[$];
    bit [63:0] observed_strobes[$];
    bit [63:0] intent_strobes[$];
    bit [63:0] lane_mask;
    bit [63:0] intent_raddr;
    ocah_axi_config::ocah_axi_write_intent_t intent;
    pair_count++;

    // Per-beat, position-exact response comparison.
    foreach (observed.resp_list[i]) observed_resps.push_back(64'(observed.resp_list[i]));
    foreach (expected.resp_list[i]) expected_resps.push_back(64'(expected.resp_list[i]));
    void'(m_checker.expect_equal_words("CHK-AXI-RESP", observed_resps, expected_resps, context_s));

    // Stimulus-intent write comparison (address/data/strobes the sequence
    // programmed; independent of the observed bus). Matched by observed
    // beat-aligned address so cross-ID B reordering cannot mispair;
    // single-beat contract (the DTP single-op flow) — a multi-beat write
    // leaves its intent pending, which fails at check_phase.
    if (observed.direction == OCAH_AXI_DIR_WRITE
            && observed.beat_count() == 1
            && cfg.consume_expected_write(
            observed.address, intent
        )) begin
      void'(m_checker.expect_equal(
          "CHK-AXI-WADDR", observed.address, intent.addr, {context_s, " source=stimulus"}
      ));
      foreach (observed.strobes[i]) observed_strobes.push_back(64'(observed.strobes[i]));
      intent_strobes.push_back(64'(intent.strb));
      void'(m_checker.expect_equal_words(
          "CHK-AXI-STRB", observed_strobes, intent_strobes, {context_s, " source=stimulus-wstrb"}
      ));
      lane_mask = strb_lane_mask(intent.strb);
      void'(m_checker.expect_equal(
          "CHK-AXI-WDATA",
          observed.first_data() & lane_mask,
          intent.data & lane_mask,
          {
            context_s, " source=stimulus lanes=strobed"
          }
      ));
    end

    // Stimulus-intent read-address comparison (address-matched).
    if (observed.direction == OCAH_AXI_DIR_READ && cfg.consume_expected_read(
            observed.address, intent_raddr
        )) begin
      void'(m_checker.expect_equal("CHK-AXI-RADDR", observed.address, intent_raddr,
                                   {context_s, " source=stimulus"}));
    end

    if (expected.expected_armed) begin
      void'(m_checker.expect_true(
          "CHK-AXI-ERR-INJ",
          observed.worst_resp() == expected.worst_resp()
                    && observed.worst_resp() != OCAH_AXI_RESP_OKAY,
          {
            context_s, " armed-error-consumed"
          }
      ));
    end

    if (observed.direction == OCAH_AXI_DIR_READ
            && expected.worst_resp() == OCAH_AXI_RESP_OKAY
            && observed.worst_resp() == expected.worst_resp()) begin
      void'(m_checker.expect_equal_words("CHK-AXI-RDATA", observed.data_words, expected.data_words,
                                         context_s));
    end

    void'(m_checker.expect_equal(
        "CHK-AXI-BEATS", 64'(observed.beat_count()), 64'(observed.expected_beats), context_s
    ));

    void'(m_checker.expect_true(
        "CHK-AXI-ADDR-ALIGN",
        (observed.address % (64'd1 << observed.size)) == 0,
        $sformatf(
            "%s size=%0d", context_s, observed.size)
    ));
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    // Snapshot required IDs at finalization time: tests populate
    // cfg.required_ids after this component's build_phase.
    m_checker.required_ids = cfg.required_ids;
    if (m_observed_q.size() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d observed transaction(s) never paired with an expectation", m_observed_q.size()
                 ))
    if (m_expected_q.size() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d expected transaction(s) never paired with an observation", m_expected_q.size()
                 ))
    if (cfg.pending_expected_resp() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d armed expected response(s) never consumed", cfg.pending_expected_resp()))
    if (cfg.pending_expected_writes() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d armed expected write intent(s) never consumed", cfg.pending_expected_writes()
                 ))
    if (cfg.pending_expected_reads() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d armed expected read intent(s) never consumed", cfg.pending_expected_reads()))
    m_checker.finalize(cfg.require_checks);
  endfunction

endclass : ocah_axi_scoreboard
