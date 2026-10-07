// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Debug-disable matrix over the three JTAG2AXI bridge gate fields — the SV
// analogue of the cocotb dtp_jtag2axi_dbg_disable_matrix_test_seq.
// Deterministic one-hot rows, the all-clear and all-disabled boundary
// masks, and seeded multi-hot masks. Every row proves, per bridge: an
// allowed bridge completes a write+readback with exactly that traffic; a
// blocked bridge produces zero request activity, keeps the SINGLE_OP image
// captured before the disable while gated, and leaves a preloaded RAM
// sentinel untouched, both while gated and after the disable is released
// (no delayed replay), and then recovers with exactly one sanctioned write
// and read.
//
// Rows: all_clear, one per bridge gate field, multi_hot_rows seeded
// multi-hot masks (+DTP_DBG_DISABLE_MULTI_HOT_ROWS), all_disabled. The
// family layer's select_target() points the evidence handles at one bridge
// at a time. The cocotb flow's Python DtpDbgDisableFcov ledger is
// cocotb-only.

class dtp_jtag2axi_dbg_disable_matrix_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_dbg_disable_matrix_test_seq)

  localparam bit [63:0] MatrixBaseAddr = 64'h4800;

  int unsigned multi_hot_rows = 11;

  // One gated write: its slot, the sentinel preloaded there, and the
  // request counters and responder burst counts before it.
  typedef struct {
    bit [63:0]   addr;
    bit [63:0]   sentinel;
    int unsigned aw;
    int unsigned w;
    int unsigned ar;
    int unsigned write_bursts;
    int unsigned read_bursts;
  } gated_attempt_t;

  function new(string name = "dtp_jtag2axi_dbg_disable_matrix_test_seq");
    super.new(name);
  endfunction

  protected function bit [63:0] row_addr(dtp_j2a_target_t t, int unsigned row_idx);
    return MatrixBaseAddr + row_idx * 8 * t.beat_bytes;
  endfunction

  protected function sep_lifecycle_ctrl_pkg::dbg_disable_t bridge_mask_from_bits(
      bit [NumTargets-1:0] bits);
    sep_lifecycle_ctrl_pkg::dbg_disable_t d = '0;
    for (int unsigned i = 0; i < NumTargets; i++)
    if (bits[i]) dtp_dbg_path_set(d, targets[i].dbg_path);
    return d;
  endfunction

  // CHK-AXI-GATE-EXACT: the responder behind `t` completed exactly the
  // expected write and read bursts.
  protected function void expect_exact_bursts(dtp_j2a_target_t t, int unsigned writes,
                                              int unsigned reads, string context_s);
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        write_bursts_now(
            t
        ),
        writes,
        $sformatf(
            "%s target=%s source=responder_burst_counts writes", context_s, t.name)
    ));
    void'(axi_evidence.expect_equal(
        "CHK-AXI-GATE-EXACT",
        read_bursts_now(
            t
        ),
        reads,
        $sformatf(
            "%s target=%s source=responder_burst_counts reads", context_s, t.name)
    ));
  endfunction

  // Allowed bridge: write+readback with request-activity proof, each
  // completing exactly its own burst.
  protected task check_allowed(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                               string context_s);
    dtp_j2a_status_e op_status;
    int unsigned aw0, w0, ar0;
    int unsigned size = t.default_size;
    int unsigned wb0 = write_bursts_now(t);
    int unsigned rb0 = read_bursts_now(t);
    sample_activity(t, aw0, w0, ar0);
    write_target_single_and_check(t, addr, data & data_mask(size), op_status, size, full_wstrb(size
                                  ), {context_s, ".write"});
    expect_request_activity(t, 1'b0, aw0, {context_s, ".write"});
    expect_exact_bursts(t, wb0 + 1, rb0, {context_s, ".write"});
    sample_activity(t, aw0, w0, ar0);
    read_target_single_and_check(t, addr, data & data_mask(size), op_status, size, {
                                 context_s, ".read"});
    expect_request_activity(t, 1'b1, ar0, {context_s, ".read"});
    expect_exact_bursts(t, wb0 + 1, rb0 + 1, {context_s, ".read"});
    operation_count++;
  endtask

  // Blocked bridge: the gated attempt produces no request activity, the RAM
  // sentinel stays untouched, and the SINGLE_OP captures while gated equal
  // `reference`.
  protected task check_blocked(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] data,
                               bit reference[], string context_s, output gated_attempt_t attempt);
    int unsigned aw1, w1, ar1;
    int unsigned size = t.default_size;
    bit gated[], post[];
    attempt.addr     = addr;
    attempt.sentinel = (64'h5EA1_0000 | (addr & 64'hFFFF)) & data_mask(size);
    write_target_mem_int(t, addr, attempt.sentinel, size);
    sample_activity(t, attempt.aw, attempt.w, attempt.ar);
    attempt.write_bursts = write_bursts_now(t);
    attempt.read_bursts  = read_bursts_now(t);
    // Gated attempt: issue_single suppresses the scoreboard intents
    // while the target's disable is asserted (the write must never
    // reach the bus, so no credit may be armed for it).
    issue_single(t, DTP_J2A_OP_WRITE, addr, data & data_mask(size), full_wstrb(size), size,
                 .use_default_size(1'b0));
    last_single_capture(gated);
    wait_sys_cycles(8);
    sample_activity(t, aw1, w1, ar1);
    expect_no_activity_evidence(t, attempt.aw, attempt.w, attempt.ar, aw1, w1, ar1, {
                                context_s, ".no_activity"});
    check_target_memory(t, addr, attempt.sentinel, size, {context_s, ".sentinel"});
    capture_single(t, post);
    check_gated_tdr(t, reference, addr, full_wstrb(size), size, gated, post, context_s);
    operation_count++;
  endtask

  task body();
    bit [NumTargets-1:0] row_bits[$];
    string row_labels[$];
    sep_lifecycle_ctrl_pkg::dbg_disable_t d;
    seed_scenario_rng();
    begin_all_bridges_pass();

    row_bits.push_back('0);
    row_labels.push_back("all_clear");
    for (int unsigned i = 0; i < NumTargets; i++) begin
      row_bits.push_back(NumTargets'(1) << i);
      row_labels.push_back({"one_hot_", targets[i].name});
    end
    for (int unsigned idx = 0; idx < multi_hot_rows; idx++) begin
      bit [NumTargets-1:0] bits;
      do bits = NumTargets'($urandom); while ($countones(bits) != 2);
      row_bits.push_back(bits);
      row_labels.push_back($sformatf("multi_hot_%0d", idx));
    end
    row_bits.push_back('1);
    row_labels.push_back("all_disabled");

    foreach (row_bits[r]) begin
      gated_attempt_t gated[int];
      bit references[NumTargets][];
      log_iteration(r + 1, row_bits.size(), $sformatf(
                    "row=%s mask=0b%03b", row_labels[r], row_bits[r]));
      d = bridge_mask_from_bits(row_bits[r]);
      // Each gated bridge's SINGLE_OP image, captured before the row's
      // disables.
      for (int unsigned i = 0; i < NumTargets; i++) begin
        if (row_bits[r][i]) begin
          dtp_j2a_target_t t = select_target(i);
          gate_reference(t, references[i]);
        end
      end
      set_dbg_disable(d);

      for (int unsigned i = 0; i < NumTargets; i++) begin
        dtp_j2a_target_t t = select_target(i);
        bit [63:0] addr = row_addr(t, r);
        bit [63:0] data = 64'h0000_0000_C0DE_0000 | (64'(r) << 8);
        if (row_bits[r][i])
          check_blocked(t, addr, data, references[i], $sformatf("%s.%s", row_labels[r], t.name),
                        gated[i]);
        else check_allowed(t, addr, data, $sformatf("%s.%s", row_labels[r], t.name));
      end

      if (gated.size() > 0) begin
        // Release without reset: nothing queued may replay, then a
        // sanctioned operation recovers on every previously-gated
        // bridge.
        enable_all_debug();
        wait_sys_cycles(8);
        foreach (gated[i]) begin
          dtp_j2a_target_t t = select_target(i);
          string ctx = $sformatf("%s.%s", row_labels[r], t.name);
          int unsigned now_aw, now_w, now_ar;
          sample_activity(t, now_aw, now_w, now_ar);
          expect_no_activity_evidence(t, gated[i].aw, gated[i].w, gated[i].ar, now_aw, now_w,
                                      now_ar, {ctx, ".post_release"});
          check_target_memory(t, gated[i].addr, gated[i].sentinel, t.default_size, {
                              ctx, ".sentinel_post_release"});
        end
        foreach (gated[i]) begin
          dtp_j2a_target_t t = select_target(i);
          string ctx = $sformatf("%s.%s", row_labels[r], t.name);
          check_allowed(t, gated[i].addr + 4 * t.beat_bytes,
                        64'h0000_0000_FEED_0000 | (64'(r) << 4), {ctx, ".recovery"});
          // From the gated attempt through the recovery the bridge carries
          // exactly the recovery write and read.
          expect_exact_bursts(t, gated[i].write_bursts + 1, gated[i].read_bursts + 1, {
                              ctx, ".recovery.from_gated_attempt"});
          check_target_memory(t, gated[i].addr, gated[i].sentinel, t.default_size, {
                              ctx, ".sentinel_post_recovery"});
        end
      end
    end

    emit_all_bridges_nonvacuity("jtag2axi_dbg_disable_matrix");
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      clear_target_error(t);
    end
    enable_all_debug();
    `uvm_info(get_type_name(),
              $sformatf("Debug-disable JTAG2AXI matrix complete: rows=%0d operations=%0d",
                        row_bits.size(), operation_count), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_dbg_disable_matrix_test_seq
