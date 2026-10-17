// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge model: the JTAG-visible state of the three bridges (SMC
// OTP, SEP OTP, SMC fabric), rebuilt from the decoded DR scans on the
// primary TAP and the AXI completions the passive monitors observed, after
// the jtag2axi update, capture, and completion rules:
//
//   SINGLE_OP    Update-DR with op READ/WRITE launches one transaction with
//                the host-packed address, strobes, and data, and the size
//                limited to one full beat, unless an operation is still
//                pending (then it is rejected: status BUSY_OR_FULL, sticky
//                full). Capture-DR presents BUSY_OR_FULL while pending,
//                else the last completion status, and the last read data
//                after a read.
//   SERIES_CTRL  Update-DR with op != NOP latches op, size (limited to one
//                full beat), pipeline depth and address and restarts the
//                read budget; the reset bit clears the sticky status.
//                Capture-DR presents the sticky status: BUSY_OR_FULL while
//                full, else the first series error since the reset bit,
//                else SUCCESS; a system reset that discarded a series
//                operation counts as a DECERR error. SINGLE_OP completions
//                do not reach it.
//   SERIES_DATA  Update-DR launches one transaction at the series address
//                on the byte lanes that address selects; a read is issued
//                only within the budget of pipeline_depth + 1 per CTRL
//                programming. INCR (or the with-status increment bit)
//                advances the address by the transfer size on completion.
//                The scan is refused, setting the sticky full flag, while
//                pipeline_depth + 1 series requests wait behind the
//                transaction in flight, or for a read while pipeline_depth
//                + 1 series reads are in flight; a refused with-status scan
//                also sets the SINGLE_OP status to BUSY_OR_FULL. A read past
//                the budget that is not refused is dropped silently; one
//                that is refused leaves the SERIES_CTRL status, and for a
//                with-status scan the SINGLE_OP status, without a contract
//                until the status is next set, since the PTAP document does
//                not say whether such a scan reports BUSY_OR_FULL.
//
// A gated update (the lifecycle disable of the bridge asserted) changes
// nothing but clears the read budget, and a completion while the disable is
// asserted leaves the bridge idle and disabled, which drops every request
// queued behind it (DTP JTAG document, "Debug Disable": buffered requests
// are dropped). A TAP reset resets the JTAG-visible state and leaves the
// bridge's AXI side running: every request launched before it and not yet
// completed stays on the fabric, and the AXI side consumes its response, so
// that completion changes no state and pairs with no later request.
// Completions are applied at the capture or update time that follows them,
// so a capture during a shift sees the state of its own Capture-DR. Plain
// class held by dtp_jtag2axi_req_ref_model and
// dtp_jtag2axi_status_ref_model; no reporting. Not modelled: the series
// read-data FIFO a SERIES_DATA capture returns (and so the DECERR a system
// reset reports for its unread entries). The oldest outstanding transaction
// is the one in flight, and the series requests behind it wait in the request
// queue. The cocotb twin is env/dtp_jtag2axi_model.py.

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
    // The SINGLE_OP or SERIES_CTRL status carries no contract until it is
    // next set.
    bit              single_uncertain;
    bit              series_uncertain;
    // SINGLE_OP may read DECERR with a zero data field, or SERIES_CTRL
    // DECERR, in place of the status the model holds, until a capture shows
    // which.
    bit              single_alt;
    bit              series_alt;
    bit              completion_seen;
    time             last_completion;
    // TCK edges counted when the newest applied completion reached the
    // port, whether it set the SINGLE_OP or the series status, and the
    // series status before it.
    int unsigned     last_completion_tck;
    bit              last_completion_single;
    bit              last_completion_series;
    dtp_j2a_status_e sticky_before_completion;
    // Completions the AXI side consumes after a TAP reset, indexed by is_read.
    int unsigned     orphans[2];
  } bridge_t;

  // CDC window after a completion during which a capture carries no
  // contract (set by the holder from the TCK period).
  time settle_window = 0;

  // TCK edges from a system reset to the edge on which its CDC clear aborts
  // the bridges' operations: two through the clear synchronizer, then the
  // abort.
  localparam int unsigned ClearAbortTck = 3;
  // TCK edges after a response handshake at a bridge port before the
  // bridge's state machine has certainly taken the response: three through
  // the CDC pointer synchronizer, one into the destination spill register,
  // one for the state machine's handshake, and one for the crossing's phase.
  localparam int unsigned CdcResponseTck = 6;
  protected int unsigned m_abort_in;
  // TCK cycle count that stamps each completion and system reset.
  int unsigned tck;

  protected bridge_t      m_bridge[string];
  protected issued_t      m_issued_q[string][$];     // launched, awaiting completion
  protected ocah_axi_item m_completed_q[string][$];  // observed, not yet applied
  protected int unsigned  m_completed_tck_q[string][$];  // tck at each completion

  function new();
    reset();
  endfunction

  // TAP reset: every bridge back to its TCK-domain reset state. The requests
  // launched and not yet completed become orphans of their direction: the
  // AXI side consumes their completions.
  function void reset();
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    foreach (names[i]) begin
      bridge_t      b;
      issued_t      no_issued[$];
      ocah_axi_item no_completed[$];
      foreach (b.orphans[read]) begin
        b.orphans[read] = m_bridge.exists(names[i]) ?
            m_bridge[names[i]].orphans[read] + outstanding(names[i], bit'(read)) : 0;
      end
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
      b.single_uncertain      = 1'b0;
      b.series_uncertain      = 1'b0;
      b.single_alt            = 1'b0;
      b.series_alt            = 1'b0;
      b.completion_seen       = 1'b0;
      b.last_completion       = 0;
      b.last_completion_tck   = 0;
      b.last_completion_single = 1'b0;
      b.last_completion_series = 1'b0;
      b.sticky_before_completion = DTP_J2A_SUCCESS;
      m_bridge[names[i]]      = b;
      m_issued_q[names[i]]    = no_issued;
      m_completed_q[names[i]] = no_completed;
      m_completed_tck_q[names[i]].delete();
    end
  endfunction

  // A system reset: its clear aborts the bridges' operations on the third
  // TCK edge after it, so a scan latched on the first two is aborted with
  // them.
  function void system_reset();
    m_abort_in = ClearAbortTck;
  endfunction

  // A system reset's clear is on its way to the bridges: a request latched
  // now never reaches the bus.
  function bit abort_pending();
    return m_abort_in != 0;
  endfunction

  // One TCK cycle, before the scan whose Update-DR it leaves takes effect.
  function void tck_step();
    tck++;
    if (m_abort_in == 0) return;
    m_abort_in--;
    if (m_abort_in == 0) abort_in_flight(1'b1, (tck > ClearAbortTck) ? tck - ClearAbortTck : 0);
  endfunction

  // System reset: every operation launched and not yet completed is
  // discarded. A discarded single or with-status operation reads DECERR on
  // SINGLE_OP; a discarded series operation reads DECERR on the sticky
  // status unless it already holds a series error. Every other status and
  // the SERIES_CTRL configuration keep their values. The reset also clears
  // the AXI side, so no orphan of an earlier TAP reset remains. Called on
  // the TCK edge the reset's clear reaches the bridges, so every queued
  // completion precedes it. With `timed`, a completion that reached the port
  // fewer than CdcResponseTck TCK edges before the reset (`reset_tck`) may
  // not have reached the bridge's state machine, which then discards the
  // operation: the status it set may read DECERR instead, as a discarded
  // operation's would, and the next capture of it shows which.
  function void abort_in_flight(bit timed = 1'b0, int unsigned reset_tck = 0);
    foreach (m_bridge[n]) begin
      issued_t no_issued[$];
      bit      single_lost;
      bit      series_lost;
      apply_completions(n, $time);
      if (timed && m_bridge[n].completion_seen &&
          (m_bridge[n].last_completion_tck + CdcResponseTck > reset_tck)) begin
        m_bridge[n].single_alt = m_bridge[n].last_completion_single;
        m_bridge[n].series_alt = m_bridge[n].last_completion_series &&
                                 (m_bridge[n].sticky_before_completion == DTP_J2A_SUCCESS);
      end
      single_lost = m_bridge[n].single_pending;
      series_lost = 1'b0;
      foreach (m_issued_q[n][i]) begin
        if (m_issued_q[n][i].with_status) single_lost = 1'b1;
        if (!m_issued_q[n][i].single) series_lost = 1'b1;
      end
      m_issued_q[n] = no_issued;
      m_bridge[n].orphans             = '{0, 0};
      m_bridge[n].single_pending      = 1'b0;
      m_bridge[n].series_reads_pushed = 0;
      if (single_lost) begin
        m_bridge[n].last_single_status = DTP_J2A_DECERR;
        m_bridge[n].last_read_data     = '0;
      end
      if (series_lost && m_bridge[n].sticky_status == DTP_J2A_SUCCESS) begin
        m_bridge[n].sticky_status = DTP_J2A_DECERR;
      end
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
  // capture or update that follows it in time. An orphan of a TAP reset is
  // consumed and changes nothing. `disabled`: the bridge's lifecycle
  // disable is asserted, so the requests issued behind the observed
  // completions are dropped.
  function void complete(string target, ocah_axi_item obs, bit disabled = 1'b0);
    bit is_read = (obs.direction == OCAH_AXI_DIR_READ);
    if (m_bridge[target].orphans[is_read] > 0) begin
      m_bridge[target].orphans[is_read]--;
      return;
    end
    m_completed_q[target].push_back(obs);
    m_completed_tck_q[target].push_back(tck);
    if (!disabled) return;
    while (m_issued_q[target].size() > m_completed_q[target].size())
    void'(m_issued_q[target].pop_back());
  endfunction

  // Expected capture of a SINGLE_OP or SERIES_CTRL scan whose Capture-DR
  // happened at `capture_time`; a completion inside settle_window before
  // it has not crossed into the TCK domain yet, so the capture carries no
  // contract. Where a completion reached the port fewer than CdcResponseTck
  // (six) TCK edges before a system reset, the prediction reads the DUT's
  // captured status, `observed_status`, bounded to two values: the
  // completion's status or DECERR. The first compared capture of that status
  // settles the race, DECERR taking the discarded operation's status and any
  // other value held to the completion's, so a reset at offset five from the
  // handshake still accepts DECERR.
  function void predict_capture(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, time capture_time,
                                dtp_j2a_status_e observed_status, dtp_jtag2axi_status_item exp);
    string n = t.name;
    bit decerr = (observed_status == DTP_J2A_DECERR);
    apply_completions(n, capture_time);
    exp.target  = n;
    exp.kind    = kind;
    exp.compare = 1'b1;
    if (m_bridge[n].completion_seen &&
            ((capture_time - m_bridge[n].last_completion) < settle_window))
      exp.compare = 1'b0;
    if (kind == DTP_J2A_SCAN_SINGLE_OP) begin
      if (m_bridge[n].single_uncertain) exp.compare = 1'b0;
      if (exp.compare && m_bridge[n].single_alt && !m_bridge[n].single_pending) begin
        m_bridge[n].single_alt = 1'b0;
        exp.context_s = {exp.context_s, " (or DECERR: the response raced a system reset)"};
        if (decerr) begin
          m_bridge[n].last_single_status = DTP_J2A_DECERR;
          m_bridge[n].last_read_data     = '0;
        end
      end
      exp.status = m_bridge[n].single_pending ? DTP_J2A_BUSY_OR_FULL
                                                    : m_bridge[n].last_single_status;
      exp.compare_rdata = !m_bridge[n].single_pending && m_bridge[n].last_single_was_read &&
                                (m_bridge[n].last_single_status == DTP_J2A_SUCCESS);
      exp.rdata_mask = ocah_rng::bit_mask(t.data_width);
      exp.rdata      = m_bridge[n].last_read_data & exp.rdata_mask;
      return;
    end
    if (m_bridge[n].series_uncertain) exp.compare = 1'b0;
    if (exp.compare && m_bridge[n].series_alt && !m_bridge[n].sticky_full) begin
      m_bridge[n].series_alt = 1'b0;
      exp.context_s = {exp.context_s, " (or DECERR: the response raced a system reset)"};
      if (decerr) m_bridge[n].sticky_status = DTP_J2A_DECERR;
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
    m_bridge[n].single_uncertain     = 1'b0;
    m_bridge[n].single_alt           = 1'b0;
    m_bridge[n].last_single_was_read = (r.op == DTP_J2A_OP_READ);
    e.single      = 1'b1;
    e.is_read     = (r.op == DTP_J2A_OP_READ);
    e.incr        = 1'b0;
    e.with_status = 1'b0;
    e.size        = dtp_j2a_axsize(t, r.size);
    m_issued_q[n].push_back(e);
    exp = make_item(t, e.is_read ? OCAH_AXI_DIR_READ : OCAH_AXI_DIR_WRITE, r.addr, e.size);
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
      m_bridge[n].series_size           = dtp_j2a_axsize(t, r.size);
      // Series read requests one CTRL programming may enqueue: pl_depth + 1,
      // where pl_depth ranges up to the bridge's rd_pl_depth (PTAP document,
      // "*_AXI_SERIES_CTRL").
      m_bridge[n].series_pipeline_depth = (r.pipeline_depth > t.rd_pl_depth)
                                                ? t.rd_pl_depth : r.pipeline_depth;
      m_bridge[n].series_addr           = r.addr & ocah_rng::bit_mask(t.addr_width);
      m_bridge[n].series_reads_pushed   = 0;
    end
    if (r.series_reset) begin
      m_bridge[n].sticky_status    = DTP_J2A_SUCCESS;
      m_bridge[n].sticky_full      = 1'b0;
      m_bridge[n].series_uncertain = 1'b0;
      m_bridge[n].series_alt       = 1'b0;
    end
  endfunction

  protected function bit update_series_data(dtp_j2a_target_t t, dtp_j2a_request_t r,
                                            output ocah_axi_item exp);
    string       n    = t.name;
    int unsigned size = m_bridge[n].series_size;
    bit [63:0]   addr = m_bridge[n].series_addr;
    int unsigned entries = m_bridge[n].series_pipeline_depth + 1;
    int unsigned queued = 0;
    bit          is_read = (m_bridge[n].series_op == DTP_J2A_OP_READ);
    int unsigned reads_in_flight;
    issued_t     e;
    e.single      = 1'b0;
    e.incr        = r.incr;
    e.with_status = (r.kind == DTP_J2A_SCAN_SERIES_DATA_WITH_STATUS);
    e.size        = size;
    if (m_bridge[n].series_op != DTP_J2A_OP_READ && m_bridge[n].series_op != DTP_J2A_OP_WRITE)
      return 1'b0;
    foreach (m_issued_q[n][i]) if (i > 0 && !m_issued_q[n][i].single) queued++;
    reads_in_flight = int'((m_issued_q[n].size() > 0) && !m_issued_q[n][0].single &&
                           m_issued_q[n][0].is_read);
    if (queued >= entries || (is_read && reads_in_flight >= entries)) begin
      if (is_read && m_bridge[n].series_reads_pushed >= entries) begin
        m_bridge[n].series_uncertain = 1'b1;
        if (e.with_status) m_bridge[n].single_uncertain = 1'b1;
        return 1'b0;
      end
      m_bridge[n].sticky_full = 1'b1;
      if (e.with_status) m_bridge[n].last_single_status = DTP_J2A_BUSY_OR_FULL;
      return 1'b0;
    end
    if (m_bridge[n].series_op == DTP_J2A_OP_WRITE) begin
      e.is_read = 1'b0;
      m_issued_q[n].push_back(e);
      exp = make_item(t, OCAH_AXI_DIR_WRITE, addr, size);
      exp.data_words.push_back(dtp_j2a_series_wdata(t, r.data, addr, size));
      exp.strobes.push_back(dtp_j2a_series_wstrb(t, addr, size));
      return 1'b1;
    end
    if (m_bridge[n].series_op == DTP_J2A_OP_READ) begin
      // Past the budget the bridge drops the push silently.
      if (m_bridge[n].series_reads_pushed >= entries) return 1'b0;
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

  // Launched requests of one direction that no observed completion has
  // matched.
  protected function int unsigned outstanding(string n, bit is_read);
    int unsigned launched = 0;
    int unsigned landed = 0;
    foreach (m_issued_q[n][i]) if (m_issued_q[n][i].is_read == is_read) launched++;
    foreach (m_completed_q[n][i]) begin
      if ((m_completed_q[n][i].direction == OCAH_AXI_DIR_READ) == is_read) landed++;
    end
    return (launched > landed) ? launched - landed : 0;
  endfunction

  protected function void apply_completions(string n, time before_time);
    while (m_completed_q[n].size() > 0 && (m_completed_q[n][0].end_time <= before_time)) begin
      ocah_axi_item obs = m_completed_q[n].pop_front();
      int unsigned  obs_tck = m_completed_tck_q[n].pop_front();
      apply_completion(n, obs, obs_tck);
    end
  endfunction

  protected function void apply_completion(string n, ocah_axi_item obs, int unsigned obs_tck);
    dtp_j2a_target_t t  = dtp_j2a_target_by_name(n);
    dtp_j2a_status_e st = dtp_j2a_axi_resp_to_status(obs.worst_resp());
    issued_t         e;
    m_bridge[n].completion_seen = 1'b1;
    m_bridge[n].last_completion = obs.end_time;
    m_bridge[n].last_completion_tck = obs_tck;
    m_bridge[n].last_completion_single = 1'b0;
    m_bridge[n].last_completion_series = 1'b0;
    // A completion nothing launched: the scoreboard reports it as an
    // unpredicted transaction; the bridge state has no entry to update.
    if (m_issued_q[n].size() == 0) return;
    e = m_issued_q[n].pop_front();
    m_bridge[n].last_completion_single = e.single || e.with_status;
    m_bridge[n].last_completion_series = !e.single;
    m_bridge[n].sticky_before_completion = m_bridge[n].sticky_status;
    if (!e.single && m_bridge[n].sticky_status == DTP_J2A_SUCCESS) m_bridge[n].sticky_status = st;
    if (e.single || e.with_status) m_bridge[n].last_single_status = st;
    if (e.single) begin
      m_bridge[n].single_pending = 1'b0;
      if (e.is_read)
        m_bridge[n].last_read_data = obs.first_data() & ocah_rng::bit_mask(t.data_width);
    end else if (e.with_status && e.is_read)
      m_bridge[n].last_read_data = dtp_j2a_series_rdata(t, obs.first_data(), obs.address, e.size);
    if (!e.single && e.incr)
      m_bridge[n].series_addr = (m_bridge[n].series_addr + dtp_j2a_size_bytes(
          e.size
      )) & ocah_rng::bit_mask(
          t.addr_width
      );
  endfunction

endclass : dtp_jtag2axi_model
