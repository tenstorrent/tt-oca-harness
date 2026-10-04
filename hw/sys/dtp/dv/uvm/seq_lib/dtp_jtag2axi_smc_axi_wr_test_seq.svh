// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC fabric JTAG2AXI write-side scenarios — the SV analogue
// of the cocotb dtp_jtag2axi_smc_axi_wr_test_seq. One parameterized
// sequence, one run_* task per VPLAN scenario, dispatched on `scenario`:
//
//   single_write                  directed size/strobe sweep + seeded randoms
//   single_write_data_verify      write non-trivial data, read it back
//   series_write_incr             SERIES_CTRL + SERIES_DATA_INCR sweep
//   series_write_incr_narrow      32-bit INCR at beat offset +4
//   series_write_no_incr          fixed-address series data stream
//   series_write_incr_with_error  WITH_ERROR_STATUS mode, per-beat increment,
//                                 one armed fault beat
//   random_ops                    randomized single writes
//   write_security_gating         smc_jtag2axi disable gates the bridge
//
// Each scenario is organized as reset/setup, stimulus, observe/check,
// cleanup, and summary. Every random choice comes from this pass's seeded
// RNG (seed_scenario_rng) and is logged with its iteration index, so
// failures replay from the runner seed. JTAG status is checked here;
// response/data/strobe truth on the bus is owned by the shared AXI
// scoreboard through the intents issue_single() arms.
//
// The security-gating exact-delta proof counts completed responder bursts
// (slave agent write_burst_count) rather than the cocotb flow's raw
// valid-pulse deltas: the reactive slave driver holds VALID visible across
// handshake latency, so pulse counts per transaction are timing-dependent
// while burst counts are exact. The no-activity windows keep the pulse
// counters (zero is zero in either counting mode).

class dtp_jtag2axi_smc_axi_wr_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_smc_axi_wr_test_seq)

  localparam bit [63:0] DefaultAxiAddr = 64'h40;
  localparam bit [63:0] DefaultAxiData = 64'h0123_4567_89AB_CDEF;

  typedef struct {
    bit [63:0]   addr;
    int unsigned size;
    bit [63:0]   data;
    bit [7:0]    wstrb;
  } wr_case_t;

  // Selected by the test before start(); body() dispatches on it.
  string scenario = "single_write";

  // Settled status of the scenario's last checked operation.
  dtp_j2a_status_e status = DTP_J2A_SUCCESS;
  int unsigned operation_count = 0;

  function new(string name = "dtp_jtag2axi_smc_axi_wr_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return (scenario == "write_security_gating") ? "" : "smc_axi";
  endfunction

  // Deterministic address/size/data/strobe cases: all legal SIZE
  // encodings, walking byte-lane strobes, then seeded random cases so
  // every loop drives different values (cocotb directed_cases parity).
  function void directed_cases(dtp_j2a_target_t t, ref wr_case_t cases[$]);
    wr_case_t c;
    cases.delete();
    for (int unsigned size = 0; size <= 3; size++) begin
      c.addr  = DefaultAxiAddr + (size * 64'h40);
      c.size  = size;
      c.data  = (DefaultAxiData ^ (64'h1111_1111_1111_1111 * size)) & data_mask(size);
      c.wstrb = full_wstrb(size);
      cases.push_back(c);
    end
    c.addr  = DefaultAxiAddr + 64'h140;
    c.size  = 3;
    c.data  = 64'hA5A5_5A5A_C3C3_3C3C;
    c.wstrb = 8'h55;
    cases.push_back(c);
    c.addr  = DefaultAxiAddr + 64'h180;
    c.size  = 3;
    c.data  = 64'h5A5A_A5A5_3C3C_C3C3;
    c.wstrb = 8'hAA;
    cases.push_back(c);
    // The strobe classes below a full beat at every size: no lane, the top
    // lane alone (2 bytes and wider), and the low half of a 4-byte beat.
    for (int unsigned size = 0; size <= 3; size++) begin
      c.addr  = DefaultAxiAddr + 64'h200 + (size * 64'h40);
      c.size  = size;
      c.data  = (DefaultAxiData ^ (64'h2222_2222_2222_2222 * size)) & data_mask(size);
      c.wstrb = 8'h00;
      cases.push_back(c);
      if (size > 0) begin
        c.addr  = DefaultAxiAddr + 64'h400 + (size * 64'h40);
        c.wstrb = 8'(1 << (size_bytes(size) - 1));
        cases.push_back(c);
      end
    end
    c.addr  = DefaultAxiAddr + 64'h600;
    c.size  = 2;
    c.data  = 64'h0BAD_F00D;
    c.wstrb = 8'h03;
    cases.push_back(c);
    for (int unsigned r = 0; r < random_count; r++) begin
      c.size  = $urandom_range(3);
      c.addr  = random_upper_addr(t);
      c.addr |= random_target_aligned_addr(t, c.size);
      c.data  = {$urandom(), $urandom()} & data_mask(c.size);
      c.wstrb = 8'($urandom_range(int'(full_wstrb(c.size)), 1));
      cases.push_back(c);
    end
  endfunction

  // -- single_write: directed size and strobe sweep -----------------------
  task run_single_write(dtp_j2a_target_t t);
    wr_case_t cases[$];
    `uvm_info(get_type_name(), "SMC_AXI_SINGLE_OP Directed Write", UVM_LOW)
    directed_cases(t, cases);
    foreach (cases[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: single write addr=0x%08h size=%0d data=0x%0h wstrb=0x%02h",
                idx + 1,
                cases.size(),
                cases[idx].addr,
                cases[idx].size,
                cases[idx].data,
                cases[idx].wstrb
                ), UVM_LOW)
      write_target_single_and_check(t, cases[idx].addr, cases[idx].data, status, cases[idx].size,
                                    cases[idx].wstrb, $sformatf("single_write#%0d", idx + 1));
      operation_count++;
    end
    begin
      bit          series_reset;
      bit [63:0]   addr_after;
      int unsigned pl_depth, size_rd;
      // SINGLE_OP status polls shift a NOP image. Neither they nor the
      // SINGLE_OP completions reach the series status or its BUSY_OR_FULL flag.
      read_series_ctrl(t, 3, series_reset, addr_after, pl_depth, size_rd, status);
      check_status("single_write.series_ctrl", status, DTP_J2A_SUCCESS);
    end
  endtask

  // -- single_write_data_verify: write then read back ---------------------
  task run_single_write_data_verify(dtp_j2a_target_t t);
    `uvm_info(get_type_name(), "SMC_AXI_SINGLE_OP Write With Readback", UVM_LOW)
    write_neighbour_then_read(t, DefaultAxiAddr + 64'h200, "write_readback", status);
    operation_count += 3;
  endtask

  // -- series_write_incr: incrementing series data sweep -------------------
  task run_series_write_incr(dtp_j2a_target_t t);
    int unsigned size   = 3;
    int unsigned stride = size_bytes(size);
    int unsigned beats  = (random_count < 2) ? 2 : ((random_count > 6) ? 6 : random_count);
    bit [63:0]   base   = random_series_base(t, beats * stride, 1'b1);
    bit          series_reset;
    bit [63:0]   addr_after;
    int unsigned pl_depth, size_rd;
    `uvm_info(get_type_name(), $sformatf(
                                   "SMC_AXI_SERIES_DATA_INCR Write Sweep: base=0x%014h beats=%0d",
                                   base, beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] addr = base + (idx * stride);
      bit [63:0] data = {$urandom(), $urandom()} & data_mask(size);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: series incr write addr=0x%014h data=0x%0h", idx + 1, beats, addr, data
          ), UVM_LOW)
      series_write_beat(t, data, addr, size, 1'b1, $sformatf("series_incr#%0d", idx));
      operation_count++;
    end
    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    check_status("series_incr.status", status, DTP_J2A_SUCCESS);
    if (addr_after !== ((base + beats * stride) & bit_mask(t.addr_width)))
      `uvm_error(
          "jtag2axi_series_chk", $sformatf(
          "series_incr.addr_after: 0x%0h != expected 0x%0h", addr_after, base + beats * stride))
  endtask

  // -- series_write_incr_narrow: 32-bit INCR at beat offset +4 -------------
  task run_series_write_incr_narrow(dtp_j2a_target_t t);
    int unsigned size   = 2;
    int unsigned stride = size_bytes(size);
    int unsigned beats  = (random_count < 2) ? 2 : ((random_count > 6) ? 6 : random_count);
    // The whole 64-bit beats the stream's words touch.
    int unsigned span   = t.beat_bytes * ((4 + beats * stride + t.beat_bytes - 1) / t.beat_bytes);
    bit [63:0]   base   = random_series_base(t, span, 1'b1) + 64'd4;
    // The low word of the first beat's slot is outside the stream; a
    // sentinel there catches a beat driven on the wrong lanes.
    bit [63:0]   sentinel_addr = base - stride;
    bit [63:0]   sentinel = {$urandom(), $urandom()} & data_mask(size);
    bit [63:0]   word_addrs[$];
    bit [63:0]   words[$];
    bit          series_reset;
    bit [63:0]   addr_after;
    int unsigned pl_depth, size_rd;
    `uvm_info(get_type_name(),
              $sformatf("SMC_AXI_SERIES_DATA_INCR 32-bit Write Sweep at +4: base=0x%08h beats=%0d",
                        base, beats), UVM_LOW)
    write_target_mem_int(t, sentinel_addr, sentinel, size);
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] addr = base + (idx * stride);
      bit [63:0] data;
      run_narrow_beat(t, idx, beats, addr, size, data);
      word_addrs.push_back(addr);
      words.push_back(data);
      operation_count++;
    end
    check_narrow_footprint(t, sentinel_addr, sentinel, word_addrs, words, size);
    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    check_status("series_incr_narrow.status", status, DTP_J2A_SUCCESS);
    if (addr_after !== ((base + beats * stride) & bit_mask(t.addr_width)))
      `uvm_error("jtag2axi_series_chk", $sformatf(
                 "series_incr_narrow.addr_after: 0x%0h != expected 0x%0h",
                 addr_after,
                 base + beats * stride
                 ))
  endtask

  // One 32-bit beat of the narrow stream: seeded payload, lane intents, the
  // beat, and the SERIES_CTRL capture after it: OKAY at the advanced
  // address. A NOP SERIES_CTRL capture leaves the latched stream running.
  protected task run_narrow_beat(dtp_j2a_target_t t, int unsigned idx, int unsigned beats,
                                 bit [63:0] addr, int unsigned size, output bit [63:0] data);
    // Expected strobes: a narrow beat lands on the lanes its address selects.
    bit [7:0] wstrb = full_wstrb(size) << (addr % t.beat_bytes);
    dtp_j2a_status_e beat_status;
    data = {$urandom(), $urandom()} & data_mask(size);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "Iteration %0d/%0d: series incr narrow write addr=0x%014h data=0x%0h wstrb=0x%02h",
            idx + 1, beats, addr, data, wstrb), UVM_LOW)
    // Stimulus intents (CHK-AXI-WADDR / CHK-AXI-STRB / CHK-AXI-WDATA); the
    // data intent sits in the strobed lanes.
    if (axi_cfg != null)
      axi_cfg.arm_expected_write(addr & bit_mask(t.addr_width), data << (8 * (addr % t.beat_bytes)),
                                 wstrb);
    series_write_beat(t, data, addr, size, 1'b1, $sformatf("series_incr_narrow#%0d", idx));
    check_series_addr(t, addr + size_bytes(size), size, $sformatf("series_incr_narrow.beat#%0d", idx
                      ), beat_status);
    check_status($sformatf("series_incr_narrow.status#%0d", idx), beat_status, DTP_J2A_SUCCESS);
  endtask

  // After the stream: no beat spilled onto the sentinel word or a
  // neighbour's word.
  protected function void check_narrow_footprint(dtp_j2a_target_t t, bit [63:0] sentinel_addr,
                                                 bit [63:0] sentinel, bit [63:0] word_addrs[$],
                                                 bit [63:0] words[$], int unsigned size);
    bit [63:0] observed = read_target_mem_int(t, sentinel_addr, size);
    if (observed !== sentinel)
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "series_incr_narrow.sentinel: memory 0x%0h != sentinel 0x%0h (addr=0x%0h)",
                 observed,
                 sentinel,
                 sentinel_addr
                 ))
    foreach (words[idx]) begin
      observed = read_target_mem_int(t, word_addrs[idx], size);
      if (observed !== words[idx])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_incr_narrow.final#%0d: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                   idx,
                   observed,
                   words[idx],
                   word_addrs[idx]
                   ))
    end
  endfunction

  // -- series_write_no_incr: fixed-address series stream -------------------
  task run_series_write_no_incr(dtp_j2a_target_t t);
    int unsigned size  = 3;
    int unsigned beats = (random_count < 2) ? 2 : ((random_count > 6) ? 6 : random_count);
    bit [63:0]   upper = random_upper_addr(t);
    bit [63:0]   addr  = upper | random_target_aligned_addr(t, size);
    bit          series_reset;
    bit [63:0]   addr_after;
    int unsigned pl_depth, size_rd;
    `uvm_info(get_type_name(),
              $sformatf("SMC_AXI_SERIES_DATA_NO_INCR Write Sweep: addr=0x%014h beats=%0d", addr,
                        beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] data = {$urandom(), $urandom()} & data_mask(size);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series no-incr write addr=0x%014h data=0x%0h",
                idx + 1,
                beats,
                addr,
                data
                ), UVM_LOW)
      series_write_beat(t, data, addr, size, 1'b0, $sformatf("series_no_incr#%0d", idx));
      operation_count++;
    end
    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    check_status("series_no_incr.status", status, DTP_J2A_SUCCESS);
    if (addr_after !== (addr & bit_mask(t.addr_width)))
      `uvm_error("jtag2axi_series_chk", $sformatf(
                 "series_no_incr.addr_after: 0x%0h != expected 0x%0h", addr_after, addr))
  endtask

  // -- series_write_incr_with_error: WITH_ERROR_STATUS write mode ----------
  task run_series_write_incr_with_error(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t plan = plan_series_status(t);
    bit [63:0] words[] = new[DtpJ2aSeriesStatusBeats];
    arm_series_status_fault(t, plan, 1'b0);
    foreach (words[i]) words[i] = {$urandom(), $urandom()} & data_mask(plan.size);
    `uvm_info(
        get_type_name(),
        $sformatf(
            "SMC_AXI_SERIES_DATA_WITH_ERROR_STATUS Write Mode: base=0x%08h fault_beat=%0d resp=%s",
            plan.base, plan.fault_idx, plan.expected.name()), UVM_LOW)
    run_series_status_write(t, plan, words, "series_status");
    recover_target(t, series_status_recovery_addr(plan), {$urandom(), $urandom()}, 1'b0,
                   "series_status", status);
    operation_count += DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_incr_with_error", t, plan, operation_count);
  endtask

  // -- random_ops: randomized single writes --------------------------------
  task run_random_ops(dtp_j2a_target_t t);
    bit [7:0] image[bit [63:0]];
    `uvm_info(get_type_name(), "SMC_AXI_SINGLE_OP Randomized Writes", UVM_LOW)
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      int unsigned size = $urandom_range(3);
      bit [63:0] offset = 64'($urandom_range((t.beat_bytes >> size) - 1) << size);
      bit [63:0] upper  = random_upper_addr(t);
      bit [63:0] addr   = upper | (random_target_aligned_addr(t, size) + offset);
      bit [63:0] data   = {$urandom(), $urandom()} & data_mask(size);
      bit [7:0]  wstrb  = 8'($urandom_range(int'(full_wstrb(size)), 1));
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: random write addr=0x%08h size=%0d data=0x%0h wstrb=0x%02h",
                idx,
                random_count,
                addr,
                size,
                data,
                wstrb
                ), UVM_LOW)
      snapshot_target_word(t, image, addr, size);
      write_target_single_and_check(t, addr, data, status, size, wstrb, $sformatf(
                                    "random_write#%0d", idx));
      image_write(image, addr, data, wstrb, size);
      operation_count++;
    end
    check_memory_image(t, image, "random_write");
  endtask

  // -- write_security_gating: smc_jtag2axi disable gates the bridge --------
  task run_write_security_gating(dtp_j2a_target_t t);
    bit [63:0] addr = DefaultAxiAddr + 64'h300;
    bit [63:0] data = {$urandom(), $urandom()};
    int unsigned before_aw, before_w, before_ar;
    int unsigned after_aw, after_w, after_ar;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned wr_bursts_gate, rd_bursts_gate;
    `uvm_info(get_type_name(), "SMC_AXI_SINGLE_OP Write Security Gating", UVM_LOW)

    // Baseline write and activity proof.
    sample_activity(t, before_aw, before_w, before_ar);
    write_target_single_and_check(t, addr, data, status, 3, 8'hFF, "gate.baseline");
    sample_activity(t, after_aw, after_w, after_ar);
    if (after_aw <= before_aw)
      `uvm_error("jtag2axi_activity_chk", $sformatf(
                 "gate.baseline: expected AW activity for the baseline write (aw %0d -> %0d)",
                 before_aw,
                 after_aw
                 ))

    // Two assert/release passes of the one direct disable prove the gate
    // is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      bit [63:0] gate_addr = addr + (idx * 64'h8);
      bit [63:0] sentinel  = 64'h5EA1_0000_0000_0000 | 64'(idx);
      bit [63:0] observed;
      bit reference[], gated[], post[];
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: gate SMC fabric write with smc_jtag2axi", idx), UVM_LOW)
      gate_image_reference(t, gate_addr, reference);
      gate_target(t);
      // Preload a sentinel at the gated-attempt address: the blocked
      // write must leave memory untouched, both while gated and after
      // the disable is released (a delayed replay would overwrite it).
      write_target_mem_int(t, gate_addr, sentinel, 3);
      // Snapshot BEFORE the gated attempt: pulse counters for the
      // no-activity windows, responder burst counts for the exact-
      // delta proof across the whole gate/restore span.
      sample_activity(t, gate_aw, gate_w, gate_ar);
      wr_bursts_gate = responder(t).write_burst_count();
      rd_bursts_gate = responder(t).read_burst_count();
      // Gated raw single-op WRITE: issue_single suppresses the intent
      // arming while the target's disable is asserted.
      issue_single(t, DTP_J2A_OP_WRITE, gate_addr, data, 8'hFF, 3, 1'b0);
      last_single_capture(gated);
      wait_sys_cycles(8);
      sample_activity(t, after_aw, after_w, after_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, after_aw, after_w, after_ar,
                                  $sformatf("gate.pass%0d.no_axi", idx));
      observed = read_target_mem_int(t, gate_addr, 3);
      if (observed !== sentinel)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "gate.pass%0d.sentinel: memory 0x%0h != sentinel 0x%0h", idx, observed, sentinel
                   ))
      capture_single(t, post);
      check_gated_tdr(t, reference, gate_addr, 8'hFF, 3, gated, post, $sformatf("gate.pass%0d", idx
                      ));
      // Delayed-leak protection: counters must still be flat after the
      // disable is released, before any sanctioned traffic.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, after_aw, after_w, after_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, after_aw, after_w, after_ar,
                                  $sformatf("gate.pass%0d.post_release", idx));
      observed = read_target_mem_int(t, gate_addr, 3);
      if (observed !== sentinel)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "gate.pass%0d.sentinel_post_release: memory 0x%0h != sentinel 0x%0h",
                   idx,
                   observed,
                   sentinel
                   ))
      // Sanctioned restore write with activity proof.
      sample_activity(t, before_aw, before_w, before_ar);
      write_target_single_and_check(t, addr + (idx * 64'h40), data ^ 64'(idx), status, 3, 8'hFF,
                                    $sformatf("gate.pass%0d.restore", idx));
      sample_activity(t, after_aw, after_w, after_ar);
      if (after_aw <= before_aw)
        `uvm_error("jtag2axi_activity_chk", $sformatf(
                   "gate.pass%0d.restore: expected AW activity for the restore write", idx))
      // Exact-delta proof from BEFORE the gated attempt to AFTER the
      // restore: only the sanctioned restore write may complete
      // (write bursts +1, read bursts unchanged — the sentinel checks
      // read through the backdoor). A delayed replay anywhere in the
      // span makes write bursts >= +2 and fails.
      if (axi_evidence != null) begin
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            responder(
                t
            ).write_burst_count(),
            wr_bursts_gate + 1,
            $sformatf(
                {
                  "gate.pass%0d target=%s source=responder_burst_counts ",
                  "sanctioned=restore_write(+1)"
                },
                idx,
                t.name)
        ));
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            responder(
                t
            ).read_burst_count(),
            rd_bursts_gate,
            $sformatf(
                "gate.pass%0d target=%s source=responder_burst_counts reads", idx, t.name)
        ));
      end
      operation_count++;
    end
    `uvm_info(get_type_name(),
              $sformatf("Step 4: gate %s write with series beats queued behind one on the bus",
                        t.name), UVM_LOW)
    run_queued_write_drop(t, addr + 64'h100, "gate.queued_drop");
    recover_target(t, addr + 64'h140, data ^ 64'hA5A5, 1'b0, "gate.queued_drop", status);
    // CHK-AXI-NONVAC: the counters that stayed flat while gated
    // demonstrably move for real traffic (baseline + both restores).
    sample_activity(t, after_aw, after_w, after_ar);
    emit_nonvacuity_evidence(t, (operation_count >= 2) && (after_aw >= 3), $sformatf(
                             "gated_attempts=%0d aw_pulses=%0d expected_aw>=3 (baseline+2 restores)",
                             operation_count,
                             after_aw
                             ));
  endtask

  task body();
    dtp_j2a_target_t t = target_smc_axi();
    seed_scenario_rng();
    `uvm_info(get_type_name(),
              $sformatf("SMC fabric write-side scenario=%s scenario_seed=%0d random_count=%0d",
                        scenario, scenario_seed, random_count), UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);  // TLR -> RTI: IR/DR scans require Run-Test/Idle
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
    case (scenario)
      "single_write":                 run_single_write(t);
      "single_write_data_verify":     run_single_write_data_verify(t);
      "series_write_incr":            run_series_write_incr(t);
      "series_write_incr_narrow":     run_series_write_incr_narrow(t);
      "series_write_no_incr":         run_series_write_no_incr(t);
      "series_write_incr_with_error": run_series_write_incr_with_error(t);
      "random_ops":                   run_random_ops(t);
      "write_security_gating":        run_write_security_gating(t);
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown write-side JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    // Scenario-level stream minimum (cocotb CHK-AXI-STREAM-MIN parity).
    emit_nonvacuity_evidence(t, operation_count >= 2, $sformatf(
                             "scenario=%s operations=%0d min_ops=2", scenario, operation_count));
    `uvm_info(get_type_name(),
              $sformatf(
                  "SMC fabric write-side scenario complete: scenario=%s operations=%0d status=%s",
                  scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_smc_axi_wr_test_seq
