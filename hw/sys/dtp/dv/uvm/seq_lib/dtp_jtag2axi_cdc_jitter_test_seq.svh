// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Cross-bridge JTAG2AXI write traffic and system-reset recovery under CDC
// jitter, the SV analogue of the cocotb dtp_jtag2axi_cdc_jitter_test_seq.
// The scenario's testlist entry passes +cdc_instrumentation_enabled=1, so
// every synchronizer of the bridges' clock crossings may hold a changing
// input for one more destination cycle, and -xlrm hier_inst_seed, which
// gives each synchronizer its own draws: a write's AW and W beats reach the
// ACLK side in different cycles, and a system reset's isolate requests reach
// the five TCK-side crossings in different TCK cycles.
//
//   * Step 1 runs the random-ops write traffic of the per-bridge random-ops
//     tests on one bridge per pass, the bridges in turn: seeded SINGLE_OP
//     writes into a byte image, then seeded series write programmings into
//     the same image. CHK-AXI-WMEM and CHK-J2A-MEM-IMAGE judge every write
//     against its stimulus: a write whose AW and W reach the ACLK side in
//     different cycles lands once with its own data. Every bridge's evidence
//     needs three passes.
//   * Step 2 runs one series-read reset abort per bridge and pass, judged by
//     the PTAP system-reset recovery rules: after a clear with no traffic
//     since, a pl_depth 0 SERIES_DATA_NO_INCR read is shifted in and a
//     system reset lands a seeded number of TCK edges after its Update-DR.
//     The discarded read reaches no port, SERIES_CTRL reads DECERR at its
//     programmed address, and a second pl_depth 0 read shifted in without
//     reprogramming SERIES_CTRL reaches the port and returns the word at
//     that address.

class dtp_jtag2axi_cdc_jitter_test_seq extends dtp_jtag2axi_robustness_test_seq;
  `uvm_object_utils(dtp_jtag2axi_cdc_jitter_test_seq)

  // The reset leg's read: one 0x400 slot per bridge from the robustness base.
  localparam int unsigned JitterReadSlot = 24;
  // TCK edges stepped after the issue scan's Update-DR before the system
  // reset. The scan's request reaches the series request FIFO on the second
  // edge after Update-DR and the state machine's address state on the third,
  // and a reset with TCK idle reaches the TCK side of a crossing two or, with
  // jitter, three edges after it. One edge therefore lands the first isolate
  // request on the address state; zero edges land it on the queued request.
  localparam int unsigned JitterResetEdgeSpan = 2;
  // TCK edges after the system reset that are logged one by one, covering
  // the state machine's path from Update-DR to the abort.
  localparam int unsigned JitterTraceTck = 6;
  // TCK edges in Run-Test/Idle within which the resumed read reaches the
  // port.
  localparam int unsigned JitterResumeTck = 16;

  function new(string name = "dtp_jtag2axi_cdc_jitter_test_seq");
    super.new(name);
    scenario = "cdc_jitter_all_bridges";
  endfunction

  // Seeded SINGLE_OP writes, then seeded series programmings, into one byte
  // image. The AXI4 fabric bridge draws every size with a size-aligned lane
  // offset; an AXI4-Lite OTP bridge writes at its bus width.
  protected task random_write_traffic(dtp_j2a_target_t t);
    bit [7:0] image[bit [63:0]];
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      int unsigned size = (t.bus_type == 0) ? $urandom_range(3) : t.default_size;
      bit [63:0] offset =
          (t.bus_type == 0) ? 64'($urandom_range((t.beat_bytes >> size) - 1) << size) : '0;
      bit [63:0] upper = random_upper_addr(t);
      bit [63:0] addr = upper | (random_target_aligned_addr(t, size) + offset);
      bit [63:0] data = mask_target_data(t, {$urandom(), $urandom()}) & data_mask(size);
      bit [7:0] wstrb = 8'($urandom_range(int'(full_wstrb(size)), 1));
      log_iteration(idx, random_count, $sformatf(
                    "target=%s random write addr=0x%014h size=%0d data=0x%0h wstrb=0x%02h",
                    t.name,
                    addr,
                    size,
                    data,
                    wstrb
                    ));
      snapshot_target_word(t, image, addr, size);
      write_target_single_and_check(t, addr, data, status, size, wstrb, $sformatf(
                                    "jitter_write#%0d", idx));
      image_write(image, addr, data, wstrb, size);
      operation_count++;
    end
    check_memory_image(t, image, "jitter_write");
    run_random_series(t, image);
  endtask

  // Shift a SERIES_DATA_NO_INCR read request in and hold the TAP in
  // Update-DR with TCK idle.
  protected task scan_series_read_to_update_dr(dtp_j2a_target_t t, int unsigned size);
    int unsigned len = 8 * size_bytes(dtp_j2a_axsize(t, size));
    bit tms[];
    bit tdi[];
    load_ir(IrWidth'(t.series_data_no_incr_instr));
    // Select-DR, Capture-DR, Shift-DR, the zero image with its last bit
    // moving to Exit1-DR, then Update-DR.
    tms = new[len + 4];
    tdi = new[len + 4];
    tms[0] = 1'b1;
    for (int unsigned i = 0; i < len; i++) tms[3+i] = (i == len - 1);
    tms[len+3] = 1'b1;
    raw_walk(tms, tdi);
    check_state(UPDATE_DR, "jtag2axi_scan_chk", "SERIES_DATA held in Update-DR");
    check_last_scan_length(1'b0, len, $sformatf("%s series_data held in Update-DR", t.name));
    note_scan(1'b0, len);
  endtask

  // Step JitterTraceTck edges in Run-Test/Idle after the reset, logging the
  // state machine after each, one character per edge (I idle, R read path).
  protected task trace_abort(dtp_j2a_target_t t, string context_s);
    string trace = "";
    repeat (JitterTraceTck) begin
      step(1'b0);
      trace = {trace, bridge_fsm_on_path(t, 1'b1) ? "R" : "I"};
    end
    `uvm_info(get_type_name(), $sformatf("%s state machine after the reset, per TCK edge: %s",
                                         context_s, trace), UVM_LOW)
  endtask

  // Shift a pl_depth 0 SERIES_DATA_NO_INCR read in without reprogramming
  // SERIES_CTRL: the read reaches the port within JitterResumeTck TCK edges
  // and the next shift captures `word`.
  protected task resume_series_read(dtp_j2a_target_t t, bit [63:0] addr, bit [63:0] word,
                                    int unsigned size, string context_s);
    int unsigned completed = port_history(t.name).count(1'b1);
    int unsigned aw0, w0, ar0;
    int unsigned aw1, w1, ar1;
    bit [63:0] raw;
    bit issued;
    bit done;
    sample_activity(t, aw0, w0, ar0);
    series_data_shift(t, t.series_data_no_incr_instr, '0, size, -1, raw);
    sample_activity(t, aw1, w1, ar1);
    issued = ar1 > ar0;
    for (int unsigned i = 0; i < JitterResumeTck && !issued; i++) begin
      step(1'b0);
      sample_activity(t, aw1, w1, ar1);
      issued = ar1 > ar0;
    end
    if (!record_abort_check(
            DtpJ2aAbortRecoveryCheckId,
            {
              context_s, ".resumed_read_issued"
            },
            64'(issued),
            64'd1,
            $sformatf(
                "AR at the port within %0d TCK edges of the shift", JitterResumeTck)
        ))
      return;
    wait_port_count(t, 1'b1, completed, done);
    if (!done) record_wait_timeout(t, PortWaitCycles, {context_s, ".resumed_read"});
    series_data_shift(t, t.series_data_no_incr_instr, '0, size, -1, raw);
    check_returned_rdata(t, raw & data_mask(dtp_j2a_axsize(t, size)), word, {
                         context_s, ".resumed_read"});
  endtask

  // System reset `edges` TCK edges after the Update-DR of a series read's
  // issue scan. SERIES_CTRL is programmed and a system reset clears the idle
  // bridge first, so the reset under test meets every crossing empty. With
  // the status already OKAY, the discarded read makes SERIES_CTRL read
  // DECERR (PTAP document, system reset recovery); no AR reaches the port,
  // since the reset holds the ACLK side isolated from its assertion until
  // the clear completes; and SERIES_CTRL keeps its address.
  protected task series_read_reset_abort(dtp_j2a_target_t t, int unsigned edges, string context_s);
    int unsigned size = t.default_size;
    bit [63:0] addr = robust_addr(t, JitterReadSlot);
    bit [63:0] word = rand_nonzero_data(t);
    int unsigned aw0, w0, ar0;
    int unsigned aw1, w1, ar1;
    dtp_j2a_status_e st;
    bit fsm_idle;
    bit recovered;
    write_target_mem_int(t, addr, word, size);
    series_ctrl_op(t, DTP_J2A_OP_NOP, '0, size, 0, 1'b1);
    series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
    clear_cdc_clear_seen();
    pulse_system_reset($urandom_range(3, 1));
    repeat (AbortSettleTck) step(1'b0);
    void'(record_cdc_clear(
        t, {context_s, ".idle_cdc_clear"}, "clear of the idle bridge before the read"
    ));
    check_series_addr(t, addr, size, {context_s, ".idle"}, st);
    void'(record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {
          context_s, ".idle_series_status"
        },
        64'(st),
        64'(DTP_J2A_SUCCESS),
        "no series operation in flight at the idle reset"
    ));
    scan_series_read_to_update_dr(t, size);
    repeat (edges) step(1'b0);
    clear_cdc_clear_seen();
    pulse_system_reset($urandom_range(3, 1));
    // The reset clears the port's request counters: quiet means no request
    // counted since the pulse.
    sample_activity(t, aw0, w0, ar0);
    trace_abort(t, context_s);
    repeat (AbortSettleTck) step(1'b0);
    fsm_idle = bridge_fsm_idle(t);
    void'(record_abort_check(
        DtpJ2aAbortFsmCheckId,
        {
          context_s, ".fsm_idle"
        },
        64'(fsm_idle),
        64'd1,
        "after the series-read reset"
    ));
    void'(record_cdc_clear(t, {context_s, ".cdc_clear"}, "tck-side isolate-and-clear"));
    sample_activity(t, aw1, w1, ar1);
    void'(record_abort_check(
        DtpJ2aAbortEscapeCheckId,
        {
          context_s, ".no_request"
        },
        64'(ar1 - ar0),
        64'd0,
        $sformatf(
            "AR requests at the port since the reset, edges=%0d", edges)
    ));
    check_series_addr(t, addr, size, {context_s, ".kept"}, st);
    recovered = record_abort_check(
        DtpJ2aAbortRecoveryCheckId,
        {context_s, ".series_status"},
        64'(st),
        64'(DTP_J2A_DECERR),
        $sformatf("SERIES_CTRL status=%s after the reset", st.name())
    );
    status = st;
    if (recovered) resume_series_read(t, addr, word, size, context_s);
    operation_count++;
  endtask

  protected task run_cdc_jitter_all_bridges();
    dtp_j2a_target_t writer = select_target(loop_index % NumTargets);
    `uvm_info(get_type_name(), "JTAG2AXI traffic and system-reset recovery under CDC jitter",
              UVM_LOW)
    log_step("1", $sformatf("Random-ops write traffic on %s / every write lands once", writer.name
             ));
    random_write_traffic(writer);
    log_step("2",
             "Series-read reset abort on every bridge / DECERR, no AR, the resumed read returns");
    for (int unsigned i = 0; i < NumTargets; i++) begin
      dtp_j2a_target_t t = select_target(i);
      int unsigned edges = (scenario_seed + i + 1) % JitterResetEdgeSpan;
      log_iteration(
          i + 1, NumTargets, $sformatf(
          "target=%s system reset %0d TCK edges after the issue scan's Update-DR", t.name, edges));
      series_read_reset_abort(t, edges, $sformatf("jitter_reset.%s", t.name));
    end
  endtask

  task body();
    seed_scenario_rng();
    begin_all_bridges_pass();
    if (scenario != "cdc_jitter_all_bridges")
      `uvm_fatal(get_type_name(), $sformatf("unknown JTAG2AXI CDC-jitter scenario %s", scenario))
    run_cdc_jitter_all_bridges();
    emit_all_bridges_nonvacuity(scenario);
    enable_all_debug();
    `uvm_info(get_type_name(),
              $sformatf(
                  "JTAG2AXI CDC-jitter scenario complete: scenario=%s operations=%0d status=%s",
                  scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_cdc_jitter_test_seq
