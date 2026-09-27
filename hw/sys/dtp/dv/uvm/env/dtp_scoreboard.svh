// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DTP scoreboard: always on, in every test, and comparing only. Every
// feature is judged on two streams the env wires in connect_phase: the
// observed VIP monitor stream (<feature>_observed_export) and the expected
// items its dtp_<feature>_ref_model publishes (<feature>_expected_export).
// The base pairs the two in order per lane and hands each pair to
// compare_pair(), which extracts the observed value from the monitor item
// and records the verdict; an expected item without a contract pairs and
// drops silently, so a reference model can publish one item per observed
// item. Expected values never originate here.
//
//   ir_decode        expected: dtp_ir_decode_ref_model on the JTAG event and
//                    IR-scan streams. Observed: dtp_tb_if.inst_decoded,
//                    sampled when the expected item arrives (the cycle the
//                    instruction becomes active).
//   idcode, bypass   expected: dtp_idcode_ref_model, dtp_bypass_ref_model.
//                    Observed: the reconstructed DR scan's TDO bits.
//   xtrig_csr        expected: dtp_xtrig_csr_ref_model. Observed: the read
//   xtrig_decode     data, or the response code, of the XTRIG AXI-Lite
//                    monitor's item.
//   jtag2axi_req     expected: dtp_jtag2axi_req_ref_model, one AXI item per
//                    launched bridge transaction on the lane of its port.
//                    Observed: the passive monitor items of the three bridge
//                    ports (direction, address, size on AXI4, strobes, and
//                    the strobed write data must match; every transaction
//                    must have been predicted and every prediction must
//                    land). A system or power-on reset cancels the
//                    predictions still pending.
//   jtag2axi_status  expected: dtp_jtag2axi_status_ref_model. Observed: the
//                    status field, and after a completed read the data
//                    field, of the SINGLE_OP or SERIES_CTRL capture.
//
// A required feature (dtp_test_cfg.required_features through the env cfg)
// that ends with zero comparisons fails the run. The cocotb DtpScoreboard
// checks inline on the driver's completed-item stream (DTP_TB_ARCH,
// realization table).

`uvm_analysis_imp_decl(_dtp_ir_decode_expected)
`uvm_analysis_imp_decl(_dtp_idcode_observed)
`uvm_analysis_imp_decl(_dtp_idcode_expected)
`uvm_analysis_imp_decl(_dtp_bypass_observed)
`uvm_analysis_imp_decl(_dtp_bypass_expected)
`uvm_analysis_imp_decl(_dtp_xtrig_csr_observed)
`uvm_analysis_imp_decl(_dtp_xtrig_csr_expected)
`uvm_analysis_imp_decl(_dtp_xtrig_decode_observed)
`uvm_analysis_imp_decl(_dtp_xtrig_decode_expected)
`uvm_analysis_imp_decl(_dtp_jtag2axi_req_observed)
`uvm_analysis_imp_decl(_dtp_jtag2axi_req_expected)
`uvm_analysis_imp_decl(_dtp_jtag2axi_status_observed)
`uvm_analysis_imp_decl(_dtp_jtag2axi_status_expected)

class dtp_scoreboard extends ocah_scoreboard;
  `uvm_component_utils(dtp_scoreboard)

  dtp_env_cfg cfg;
  // Handed by dtp_env: the decoded-instruction observable and the reset
  // assertion counters.
  virtual dtp_tb_if tb_vif;

  uvm_analysis_imp_dtp_ir_decode_expected #(dtp_expected_item, dtp_scoreboard)
        ir_decode_expected_export;
  uvm_analysis_imp_dtp_idcode_observed #(ocah_jtag_scan_item, dtp_scoreboard)
        idcode_observed_export;
  uvm_analysis_imp_dtp_idcode_expected #(dtp_expected_item, dtp_scoreboard)
        idcode_expected_export;
  uvm_analysis_imp_dtp_bypass_observed #(ocah_jtag_scan_item, dtp_scoreboard)
        bypass_observed_export;
  uvm_analysis_imp_dtp_bypass_expected #(dtp_expected_item, dtp_scoreboard)
        bypass_expected_export;
  uvm_analysis_imp_dtp_xtrig_csr_observed #(ocah_axi_item, dtp_scoreboard)
        xtrig_csr_observed_export;
  uvm_analysis_imp_dtp_xtrig_csr_expected #(dtp_expected_item, dtp_scoreboard)
        xtrig_csr_expected_export;
  uvm_analysis_imp_dtp_xtrig_decode_observed #(ocah_axi_item, dtp_scoreboard)
        xtrig_decode_observed_export;
  uvm_analysis_imp_dtp_xtrig_decode_expected #(dtp_expected_item, dtp_scoreboard)
        xtrig_decode_expected_export;
  uvm_analysis_imp_dtp_jtag2axi_req_observed #(ocah_axi_item, dtp_scoreboard)
        jtag2axi_req_observed_export;
  uvm_analysis_imp_dtp_jtag2axi_req_expected #(ocah_axi_item, dtp_scoreboard)
        jtag2axi_req_expected_export;
  uvm_analysis_imp_dtp_jtag2axi_status_observed #(ocah_jtag_scan_item, dtp_scoreboard)
        jtag2axi_status_observed_export;
  uvm_analysis_imp_dtp_jtag2axi_status_expected #(dtp_jtag2axi_status_item, dtp_scoreboard)
        jtag2axi_status_expected_export;

  protected bit [31:0] m_sys_rst_seen;
  protected bit [31:0] m_por_seen;

  function new(string name = "dtp_scoreboard", uvm_component parent = null);
    super.new(name, parent);
    name_tag = "dtp_scoreboard";
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(dtp_env_cfg)::get(this, "", "env_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "dtp_env_cfg `env_cfg` not found in uvm_config_db")
    if (tb_vif == null) `uvm_fatal(get_type_name(), "virtual dtp_tb_if `tb_vif` not set by the env")
    ir_decode_expected_export       = new("ir_decode_expected_export", this);
    idcode_observed_export          = new("idcode_observed_export", this);
    idcode_expected_export          = new("idcode_expected_export", this);
    bypass_observed_export          = new("bypass_observed_export", this);
    bypass_expected_export          = new("bypass_expected_export", this);
    xtrig_csr_observed_export       = new("xtrig_csr_observed_export", this);
    xtrig_csr_expected_export       = new("xtrig_csr_expected_export", this);
    xtrig_decode_observed_export    = new("xtrig_decode_observed_export", this);
    xtrig_decode_expected_export    = new("xtrig_decode_expected_export", this);
    jtag2axi_req_observed_export    = new("jtag2axi_req_observed_export", this);
    jtag2axi_req_expected_export    = new("jtag2axi_req_expected_export", this);
    jtag2axi_status_observed_export = new("jtag2axi_status_observed_export", this);
    jtag2axi_status_expected_export = new("jtag2axi_status_expected_export", this);
    add_feature(DtpFeatureIrDecode);
    add_feature(DtpFeatureIdcode);
    add_feature(DtpFeatureBypass);
    add_feature(DtpFeatureXtrigCsr);
    add_feature(DtpFeatureXtrigDecode);
    add_feature(DtpFeatureJtag2axiReq);
    add_feature(DtpFeatureJtag2axiStatus);
    foreach (cfg.required_features[i]) require_feature(cfg.required_features[i]);
  endfunction

  // ------------------------------------------------------------------
  // ir_decode: the observation is a TB-interface observable, sampled in
  // the time step the instruction became active.
  // ------------------------------------------------------------------

  function void write_dtp_ir_decode_expected(dtp_expected_item t);
    if ($isunknown(tb_vif.inst_decoded)) begin
      record_compare(DtpFeatureIrDecode, 1'b0, $sformatf("0x%0h", t.expected & t.mask), "X",
                     t.context_s);
      return;
    end
    void'(compare_equal(
        DtpFeatureIrDecode, 64'(tb_vif.inst_decoded) & t.mask, t.expected & t.mask, t.context_s
    ));
  endfunction

  // ------------------------------------------------------------------
  // Stream features: enqueue on the feature's lane; the base pairs.
  // ------------------------------------------------------------------

  function void write_dtp_idcode_observed(ocah_jtag_scan_item t);
    push_observed(DtpFeatureIdcode, t);
  endfunction

  function void write_dtp_idcode_expected(dtp_expected_item t);
    push_expected(DtpFeatureIdcode, t);
  endfunction

  function void write_dtp_bypass_observed(ocah_jtag_scan_item t);
    push_observed(DtpFeatureBypass, t);
  endfunction

  function void write_dtp_bypass_expected(dtp_expected_item t);
    push_expected(DtpFeatureBypass, t);
  endfunction

  function void write_dtp_xtrig_csr_observed(ocah_axi_item t);
    push_observed(DtpFeatureXtrigCsr, t);
  endfunction

  function void write_dtp_xtrig_csr_expected(dtp_expected_item t);
    push_expected(DtpFeatureXtrigCsr, t);
  endfunction

  function void write_dtp_xtrig_decode_observed(ocah_axi_item t);
    push_observed(DtpFeatureXtrigDecode, t);
  endfunction

  function void write_dtp_xtrig_decode_expected(dtp_expected_item t);
    push_expected(DtpFeatureXtrigDecode, t);
  endfunction

  // Bridge transactions pair per port: the item's source names the
  // monitor that published it, and the reference model stamps the same
  // source on its predictions.
  function void write_dtp_jtag2axi_req_observed(ocah_axi_item t);
    sync_reset();
    push_observed(DtpFeatureJtag2axiReq, t, t.source);
  endfunction

  function void write_dtp_jtag2axi_req_expected(ocah_axi_item t);
    sync_reset();
    push_expected(DtpFeatureJtag2axiReq, t, t.source);
  endfunction

  function void write_dtp_jtag2axi_status_observed(ocah_jtag_scan_item t);
    push_observed(DtpFeatureJtag2axiStatus, t);
  endfunction

  function void write_dtp_jtag2axi_status_expected(dtp_jtag2axi_status_item t);
    push_expected(DtpFeatureJtag2axiStatus, t);
  endfunction

  // ------------------------------------------------------------------
  // Pair verdicts.
  // ------------------------------------------------------------------

  virtual function void compare_pair(string feature, uvm_object observed, uvm_object expected);
    if (feature == DtpFeatureIdcode || feature == DtpFeatureBypass)
      compare_scan_value(feature, expected, observed);
    else if (feature == DtpFeatureXtrigCsr) compare_axi_data(feature, expected, observed);
    else if (feature == DtpFeatureXtrigDecode) compare_axi_resp(feature, expected, observed);
    else if (feature == DtpFeatureJtag2axiReq) compare_jtag2axi_req(expected, observed);
    else if (feature == DtpFeatureJtag2axiStatus) compare_jtag2axi_status(expected, observed);
    else super.compare_pair(feature, observed, expected);
  endfunction

  // The scan's shifted-out bits under the expected mask.
  protected function void compare_scan_value(string feature, uvm_object expected,
                                             uvm_object observed);
    dtp_expected_item   exp = cast_expected(expected);
    ocah_jtag_scan_item obs;
    if (!$cast(obs, observed))
      `uvm_fatal(get_type_name(), {feature, ": observed item is not an ocah_jtag_scan_item"})
    if (!exp.compare) return;
    void'(compare_equal(
        feature, obs.tdo_value() & exp.mask, exp.expected & exp.mask, exp.context_s
    ));
  endfunction

  // The transaction's first data word under the expected mask.
  protected function void compare_axi_data(string feature, uvm_object expected,
                                           uvm_object observed);
    dtp_expected_item exp = cast_expected(expected);
    ocah_axi_item     obs = cast_axi(feature, observed);
    if (!exp.compare) return;
    void'(compare_equal(
        feature, obs.first_data() & exp.mask, exp.expected & exp.mask, exp.context_s
    ));
  endfunction

  // The transaction's worst response code.
  protected function void compare_axi_resp(string feature, uvm_object expected,
                                           uvm_object observed);
    dtp_expected_item exp = cast_expected(expected);
    ocah_axi_item     obs = cast_axi(feature, observed);
    if (!exp.compare) return;
    void'(compare_equal(
        feature, 64'(obs.worst_resp()) & exp.mask, exp.expected & exp.mask, exp.context_s
    ));
  endfunction

  // One verdict per bridge transaction: direction, address, size (AXI4
  // only; AXI-Lite carries none), one beat, and for writes the strobes
  // and the data on the strobed lanes.
  protected function void compare_jtag2axi_req(uvm_object expected, uvm_object observed);
    ocah_axi_item exp  = cast_axi(DtpFeatureJtag2axiReq, expected);
    ocah_axi_item obs  = cast_axi(DtpFeatureJtag2axiReq, observed);
    string        diff = "";
    if (exp.direction != obs.direction) diff = {diff, " direction"};
    if (exp.address !== obs.address) diff = {diff, " address"};
    if ((exp.protocol == OCAH_AXI_PROTO_AXI4) && (exp.size != obs.size)) diff = {diff, " size"};
    if (obs.beat_count() != 1) diff = {diff, " beats"};
    if (exp.direction == OCAH_AXI_DIR_WRITE) begin
      bit [7:0]  strb_e = (exp.strobes.size() != 0) ? exp.strobes[0] : 8'h00;
      bit [7:0]  strb_o = (obs.strobes.size() != 0) ? obs.strobes[0] : 8'h00;
      bit [63:0] lanes  = strobe_lanes(strb_e);
      if (strb_e !== strb_o) diff = {diff, " strobes"};
      if ((exp.first_data() & lanes) !== (obs.first_data() & lanes)) diff = {diff, " data"};
    end
    record_compare(DtpFeatureJtag2axiReq, diff == "", request_string(exp), request_string(obs), {
                   "port=", obs.source, (diff == "") ? "" : {" mismatch:", diff}});
  endfunction

  // The request-side fields this feature judges. The response code is the
  // AXI recorder's verdict (CHK-AXI-RESP, CHK-AXI-ERR-INJ) and stays out of
  // this record.
  protected function string request_string(ocah_axi_item item);
    string s = $sformatf("%s addr=0x%0h", item.direction.name(), item.address);
    if (item.protocol == OCAH_AXI_PROTO_AXI4) s = {s, $sformatf(" size=%0d", item.size)};
    s = {s, $sformatf(" beats=%0d", item.beat_count())};
    if (item.direction == OCAH_AXI_DIR_WRITE)
      s = {
        s,
        $sformatf(
            " strb=0x%02h data=0x%0h",
            (item.strobes.size() != 0) ? item.strobes[0] : 8'h00,
            item.first_data()
        )
      };
    return s;
  endfunction

  // One verdict per bridge capture: the status field, and the data field
  // after a completed OKAY read.
  protected function void compare_jtag2axi_status(uvm_object expected, uvm_object observed);
    dtp_jtag2axi_status_item exp;
    ocah_jtag_scan_item      obs;
    dtp_j2a_target_t         t;
    dtp_j2a_status_e         status_e;
    bit [63:0]               status_o;
    bit [63:0]               rdata_o = '0;
    string                   diff    = "";
    if (!$cast(exp, expected))
      `uvm_fatal(get_type_name(), "jtag2axi_status: expected item type mismatch")
    if (!$cast(obs, observed))
      `uvm_fatal(get_type_name(), "jtag2axi_status: observed item is not an ocah_jtag_scan_item")
    if (!exp.compare) return;
    t        = dtp_j2a_target_by_name(exp.target);
    status_o = dtp_bits_field(obs.tdo_bits, 0, 2);
    if (status_o !== 64'(exp.status)) diff = {diff, " status"};
    if (exp.compare_rdata) begin
      int unsigned data_off = 2 + t.size_bits + t.wstrb_bits;
      rdata_o = dtp_bits_field(obs.tdo_bits, data_off, t.data_width) & exp.rdata_mask;
      if (rdata_o !== (exp.rdata & exp.rdata_mask)) diff = {diff, " rdata"};
    end
    status_e = dtp_j2a_status_e'(int'(status_o));
    record_compare(
        DtpFeatureJtag2axiStatus, diff == "", exp.convert2string(), $sformatf(
        "status=%s%s", status_e.name(), exp.compare_rdata ? $sformatf(" rdata=0x%0h", rdata_o) : ""
        ), {exp.context_s, (diff == "") ? "" : {" mismatch:", diff}});
  endfunction

  // ------------------------------------------------------------------
  // Helpers.
  // ------------------------------------------------------------------

  // A system or power-on reset aborts the bridge transactions in flight,
  // so the predictions still waiting for them are withdrawn.
  protected function void sync_reset();
    int unsigned dropped;
    if ((tb_vif.sys_rst_assert_count === m_sys_rst_seen) &&
            (tb_vif.por_assert_count === m_por_seen))
      return;
    m_sys_rst_seen = tb_vif.sys_rst_assert_count;
    m_por_seen     = tb_vif.por_assert_count;
    dropped        = flush_expected(DtpFeatureJtag2axiReq);
    if (dropped != 0)
      `uvm_info(get_type_name(), $sformatf(
                "reset withdrew %0d predicted bridge transaction(s)", dropped), UVM_MEDIUM)
  endfunction

  protected function dtp_expected_item cast_expected(uvm_object expected);
    dtp_expected_item exp;
    if (!$cast(exp, expected))
      `uvm_fatal(get_type_name(), "expected item is not a dtp_expected_item")
    return exp;
  endfunction

  protected function ocah_axi_item cast_axi(string feature, uvm_object item);
    ocah_axi_item axi;
    if (!$cast(axi, item)) `uvm_fatal(get_type_name(), {feature, ": item is not an ocah_axi_item"})
    return axi;
  endfunction

  // Data-bit mask of the byte lanes a strobe selects.
  protected static function bit [63:0] strobe_lanes(bit [7:0] strb);
    bit [63:0] lanes = '0;
    for (int unsigned lane = 0; lane < 8; lane++) if (strb[lane]) lanes[8*lane+:8] = 8'hFF;
    return lanes;
  endfunction

endclass : dtp_scoreboard
