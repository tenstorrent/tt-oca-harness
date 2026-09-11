// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge model: the JTAG-visible state of the three bridges (SMC
// OTP, SEP OTP, SMC fabric), rebuilt from the decoded DR scans on the
// primary TAP and the AXI completions the passive monitors observed, after
// the jtag2axi update, capture, and completion rules:
//
//   SINGLE_OP    Update-DR with op READ/WRITE launches one transaction with
//                the host-packed address, size, strobes, and data unless an
//                operation is still pending (then it is rejected: status
//                BUSY_OR_FULL, sticky full). Capture-DR presents
//                BUSY_OR_FULL while pending, else the last completion
//                status, and the last read data after a read.
//   SERIES_CTRL  Update-DR with op != NOP latches op, size, pipeline depth
//                and address and restarts the read budget; the reset bit
//                clears the sticky status. Capture-DR presents the sticky
//                status (the latest completion, BUSY_OR_FULL while full).
//   SERIES_DATA  Update-DR launches one transaction at the series address
//                on the byte lanes that address selects; a read is issued
//                only within the budget of pipeline_depth + 1 per CTRL
//                programming. INCR (or the with-status increment bit)
//                advances the address by the transfer size on completion.
//
// A gated update (the lifecycle disable of the bridge asserted) changes
// nothing but clears the read budget. Completions are applied at the
// capture or update time that follows them, so a capture during a shift
// sees the state of its own Capture-DR. Plain class held by
// dtp_jtag2axi_req_ref_model and dtp_jtag2axi_status_ref_model; no
// reporting. Not modelled: the series read-data FIFO a SERIES_DATA capture
// returns, and true request-FIFO backpressure. No cocotb twin.

class dtp_jtag2axi_model;

  typedef struct {
    bit          single;       // from the SINGLE_OP buffer, else a series entry
    bit          is_read;
    bit          incr;         // series: advance the address on completion
    bit          with_status;  // series: SERIES_DATA_WITH_STATUS entry
    int unsigned size;
  } issued_t;

  typedef struct {
    bit              single_pending;
    dtp_j2a_status_e last_single_status;
    bit              last_single_was_read;
    bit [63:0]       last_read_data;
    dtp_j2a_op_e     series_op;
    int unsigned     series_size;
    int unsigned     series_pipeline_depth;
    bit [63:0]       series_addr;
    int unsigned     series_reads_pushed;
    dtp_j2a_status_e sticky_status;
    bit              sticky_full;
    bit              completion_seen;
    time             last_completion;
  } bridge_t;

  // CDC window after a completion during which a capture carries no
  // contract (set by the holder from the TCK period).
  time settle_window = 0;

  protected bridge_t      m_bridge[string];
  protected issued_t      m_issued_q[string][$];     // launched, awaiting completion
  protected ocah_axi_item m_completed_q[string][$];  // observed, not yet applied

  function new();
    reset();
  endfunction

  // TAP reset: every bridge back to its TCK-domain reset state.
  function void reset();
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    foreach (names[i]) begin
      bridge_t      b;
      issued_t      no_issued[$];
      ocah_axi_item no_completed[$];
      b.single_pending        = 1'b0;
      b.last_single_status    = DTP_J2A_SUCCESS;
      b.last_single_was_read  = 1'b0;
      b.last_read_data        = '0;
      b.series_op             = DTP_J2A_OP_NOP;
      b.series_size           = 0;
      b.series_pipeline_depth = 0;
      b.series_addr           = '0;
      b.series_reads_pushed   = 0;
      b.sticky_status         = DTP_J2A_SUCCESS;
      b.sticky_full           = 1'b0;
      b.completion_seen       = 1'b0;
      b.last_completion       = 0;
      m_bridge[names[i]]      = b;
      m_issued_q[names[i]]    = no_issued;
      m_completed_q[names[i]] = no_completed;
    end
  endfunction

  // System reset: the AXI side drops its in-flight transaction and the
  // pending operation completes nowhere; the JTAG-side registers keep
  // their values.
  function void abort_in_flight();
    foreach (m_bridge[n]) begin
      issued_t      no_issued[$];
      ocah_axi_item no_completed[$];
      m_issued_q[n]    = no_issued;
      m_completed_q[n] = no_completed;
      m_bridge[n].single_pending = 1'b0;
    end
  endfunction

  // A gated update changes nothing; the idle, disabled bridge clears its
  // series read budget.
  function void gated(string target);
    m_bridge[target].series_reads_pushed = 0;
  endfunction

  // Which JTAG2AXI register a DR scan under instruction `ir` addressed,
  // and its decoded request; SCAN_NONE when it is none of them or the
  // scan length does not fit the register.
  function dtp_j2a_scan_kind_e decode(bit [DtpIrWidth-1:0] ir, ocah_jtag_scan_item scan,
                                      output dtp_j2a_target_t t, output dtp_j2a_request_t r);
    dtp_j2a_scan_kind_e kind = dtp_j2a_classify_instr(ir, t);
    r.kind = DTP_J2A_SCAN_NONE;
    case (kind)
      DTP_J2A_SCAN_SINGLE_OP: begin
        if (scan.bit_count != dtp_j2a_single_op_len(t)) return DTP_J2A_SCAN_NONE;
        dtp_j2a_decode_single_op(t, scan.tdi_bits, r);
      end
      DTP_J2A_SCAN_SERIES_CTRL: begin
        if (scan.bit_count != dtp_j2a_series_ctrl_len(t)) return DTP_J2A_SCAN_NONE;
        dtp_j2a_decode_series_ctrl(t, scan.tdi_bits, r);
      end
      DTP_J2A_SCAN_SERIES_DATA_INCR,
            DTP_J2A_SCAN_SERIES_DATA_NO_INCR,
            DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS: begin
        int unsigned size = m_bridge[t.name].series_size;
        if (scan.bit_count != dtp_j2a_series_data_len(kind, size)) return DTP_J2A_SCAN_NONE;
        dtp_j2a_decode_series_data(kind, size, scan.tdi_bits, r);
      end
      default: return DTP_J2A_SCAN_NONE;
    endcase
    return kind;
  endfunction

  // Update-DR of a decoded request at `update_time`. Returns 1 and fills
  // `exp` (direction, address, size, data, strobes) when the bridge
  // launches an AXI transaction for it.
  function bit update(dtp_j2a_target_t t, dtp_j2a_request_t r, time update_time,
                      output ocah_axi_item exp);
    apply_completions(t.name, update_time);
    case (r.kind)
      DTP_J2A_SCAN_SINGLE_OP:   return update_single_op(t, r, exp);
      DTP_J2A_SCAN_SERIES_CTRL: begin
                update_series_ctrl(t, r);
                return 1'b0;
            end
      DTP_J2A_SCAN_SERIES_DATA_INCR,
            DTP_J2A_SCAN_SERIES_DATA_NO_INCR,
            DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS:
                return update_series_data(t, r, exp);
      default: return 1'b0;
    endcase
  endfunction

  // An AXI completion observed on a bridge port, applied at the next
  // capture or update that follows it in time.
  function void complete(string target, ocah_axi_item obs);
    m_completed_q[target].push_back(obs);
  endfunction

  // Expected capture of a SINGLE_OP or SERIES_CTRL scan whose Capture-DR
  // happened at `capture_time`; a completion inside settle_window before
  // it has not crossed into the TCK domain yet, so the capture carries no
  // contract.
  function void predict_capture(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, time capture_time,
                                dtp_jtag2axi_status_item exp);
    string n = t.name;
    apply_completions(n, capture_time);
    exp.target  = n;
    exp.kind    = kind;
    exp.compare = 1'b1;
    if (m_bridge[n].completion_seen &&
            ((capture_time - m_bridge[n].last_completion) < settle_window))
      exp.compare = 1'b0;
    if (kind == DTP_J2A_SCAN_SINGLE_OP) begin
      exp.status = m_bridge[n].single_pending ? DTP_J2A_BUSY_OR_FULL
                                                    : m_bridge[n].last_single_status;
      exp.compare_rdata = !m_bridge[n].single_pending && m_bridge[n].last_single_was_read &&
                                (m_bridge[n].last_single_status == DTP_J2A_SUCCESS);
      exp.rdata_mask = ocah_rng::bit_mask(t.data_width);
      exp.rdata      = m_bridge[n].last_read_data & exp.rdata_mask;
      return;
    end
    exp.status = m_bridge[n].sticky_full ? DTP_J2A_BUSY_OR_FULL : m_bridge[n].sticky_status;
    exp.compare_rdata = 1'b0;
  endfunction

  // ------------------------------------------------------------------
  // Update rules.
  // ------------------------------------------------------------------

  protected function bit update_single_op(dtp_j2a_target_t t, dtp_j2a_request_t r,
                                          output ocah_axi_item exp);
    string   n = t.name;
    issued_t e;
    if (r.op != DTP_J2A_OP_READ && r.op != DTP_J2A_OP_WRITE) return 1'b0;
    if (m_bridge[n].single_pending) begin
      // Rejected: the prior operation still completes and then
      // overwrites this status.
      m_bridge[n].sticky_full        = 1'b1;
      m_bridge[n].last_single_status = DTP_J2A_BUSY_OR_FULL;
      m_bridge[n].single_pending     = 1'b0;
      return 1'b0;
    end
    m_bridge[n].single_pending       = 1'b1;
    m_bridge[n].last_single_was_read = (r.op == DTP_J2A_OP_READ);
    e.single      = 1'b1;
    e.is_read     = (r.op == DTP_J2A_OP_READ);
    e.incr        = 1'b0;
    e.with_status = 1'b0;
    e.size        = r.size;
    m_issued_q[n].push_back(e);
    exp = make_item(t, e.is_read ? OCAH_AXI_DIR_READ : OCAH_AXI_DIR_WRITE, r.addr, r.size);
    if (!e.is_read) begin
      exp.data_words.push_back(r.data & ocah_rng::bit_mask(t.data_width));
      exp.strobes.push_back(r.wstrb & 8'(ocah_rng::bit_mask(t.wstrb_bits)));
    end
    return 1'b1;
  endfunction

  protected function void update_series_ctrl(dtp_j2a_target_t t, dtp_j2a_request_t r);
    string n = t.name;
    if (r.op != DTP_J2A_OP_NOP) begin
      m_bridge[n].series_op             = r.op;
      m_bridge[n].series_size           = r.size;
      m_bridge[n].series_pipeline_depth = (r.pipeline_depth > DtpJ2aMaxPipelineDepth)
                                                ? DtpJ2aMaxPipelineDepth : r.pipeline_depth;
      m_bridge[n].series_addr           = r.addr & ocah_rng::bit_mask(t.addr_width);
      m_bridge[n].series_reads_pushed   = 0;
    end
    if (r.series_reset) begin
      m_bridge[n].sticky_status = DTP_J2A_SUCCESS;
      m_bridge[n].sticky_full   = 1'b0;
    end
  endfunction

  protected function bit update_series_data(dtp_j2a_target_t t, dtp_j2a_request_t r,
                                            output ocah_axi_item exp);
    string       n    = t.name;
    int unsigned size = m_bridge[n].series_size;
    bit [63:0]   addr = m_bridge[n].series_addr;
    issued_t     e;
    e.single      = 1'b0;
    e.incr        = r.incr;
    e.with_status = (r.kind == DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS);
    e.size        = size;
    if (m_bridge[n].series_op == DTP_J2A_OP_WRITE) begin
      e.is_read = 1'b0;
      m_issued_q[n].push_back(e);
      exp = make_item(t, OCAH_AXI_DIR_WRITE, addr, size);
      exp.data_words.push_back(dtp_j2a_series_wdata(t, r.data, addr));
      exp.strobes.push_back(dtp_j2a_series_wstrb(t, addr, size));
      return 1'b1;
    end
    if (m_bridge[n].series_op == DTP_J2A_OP_READ) begin
      // Past the budget the bridge drops the push silently.
      if (m_bridge[n].series_reads_pushed >= m_bridge[n].series_pipeline_depth + 1) return 1'b0;
      if (!e.with_status) m_bridge[n].series_reads_pushed++;
      e.is_read = 1'b1;
      m_issued_q[n].push_back(e);
      exp = make_item(t, OCAH_AXI_DIR_READ, addr, size);
      return 1'b1;
    end
    return 1'b0;
  endfunction

  // One single-beat expected transaction; the caller adds the write
  // payload.
  protected function ocah_axi_item make_item(dtp_j2a_target_t t, ocah_axi_dir_e dir,
                                             bit [63:0] addr, int unsigned size);
    ocah_axi_item item = ocah_axi_item::type_id::create("item");
    item.protocol       = t.protocol;
    item.direction      = dir;
    item.address        = addr & ocah_rng::bit_mask(t.addr_width);
    item.size           = size;
    item.expected_beats = 1;
    return item;
  endfunction

  // ------------------------------------------------------------------
  // Completion rules.
  // ------------------------------------------------------------------

  protected function void apply_completions(string n, time before_time);
    while (m_completed_q[n].size() > 0 && (m_completed_q[n][0].end_time <= before_time)) begin
      ocah_axi_item obs = m_completed_q[n].pop_front();
      apply_completion(n, obs);
    end
  endfunction

  protected function void apply_completion(string n, ocah_axi_item obs);
    dtp_j2a_target_t t  = dtp_j2a_target_by_name(n);
    dtp_j2a_status_e st = dtp_j2a_axi_resp_to_status(obs.worst_resp());
    issued_t         e;
    m_bridge[n].completion_seen = 1'b1;
    m_bridge[n].last_completion = obs.end_time;
    // A completion nothing launched: the scoreboard reports it as an
    // unpredicted transaction; the bridge state has no entry to update.
    if (m_issued_q[n].size() == 0) return;
    e = m_issued_q[n].pop_front();
    m_bridge[n].sticky_status = st;
    if (e.single || e.with_status) m_bridge[n].last_single_status = st;
    if (e.single) begin
      m_bridge[n].single_pending = 1'b0;
      if (e.is_read)
        m_bridge[n].last_read_data = obs.first_data() & ocah_rng::bit_mask(t.data_width);
    end else if (e.with_status && e.is_read)
      m_bridge[n].last_read_data = dtp_j2a_series_rdata(t, obs.first_data(), obs.address);
    if (!e.single && e.incr)
      m_bridge[n].series_addr = (m_bridge[n].series_addr + dtp_j2a_size_bytes(
          e.size
      )) & ocah_rng::bit_mask(
          t.addr_width
      );
  endfunction

endclass : dtp_jtag2axi_model
