// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// OTP AXI-Lite JTAG2AXI scenarios — the SV analogue of the cocotb
// dtp_jtag2axi_otp_axi_test_seq. One parameterized sequence runs one
// focused scenario per pass against the OTP bridge named by `target_name`
// (smc_otp or sep_otp; both are 32/32 AXI-Lite ports answered by shared
// ocah_axi_vip slave agents):
//
//   single_write                  directed size/strobe sweep + seeded randoms
//   single_write_data_verify      write non-trivial data, read it back
//   series_write_incr             SERIES_CTRL + SERIES_DATA_INCR sweep
//   series_write_no_incr          fixed-address series data stream
//   series_write_incr_with_error  WITH_ERROR_STATUS mode, per-beat increment,
//                                 one armed fault beat
//   random_ops                    randomized single writes
//   write_security_gating         the port's disable gates the bridge
//   single_write_read             one write plus readback of the same slot
//   series_write_read_incr        incrementing series write leg then per-beat
//                                 SERIES read-back (prime + capture shifts)
//   series_write_read_no_incr     fixed-address series: every read beat
//                                 returns the last value written
//   series_write_read_incr_with_error  *_WITH_ERROR_STATUS mode, mixed
//                                 increment pattern on both legs, one armed
//                                 fault beat on the read leg
//   read_random_ops               randomized single reads of backdoor-
//                                 preloaded data
//   read_security_gating          gated read attempts produce zero request
//                                 activity; baseline/restore reads prove the
//                                 observation path is alive
//
// Series read-data pipeline: a SERIES_DATA shift in READ mode launches the
// bus read for the programmed address and RETURNS THE PREVIOUS shift's
// data, so each beat needs a priming shift (bus-activity checked) followed
// by a capture shift whose TDO carries the primed beat. Every random choice
// comes from this pass's seeded RNG (seed_scenario_rng) and is logged with
// its iteration index, so failures replay from the runner seed. JTAG status
// is checked here; response/data/strobe truth on the bus is owned by the
// shared AXI scoreboard through the intents issue_single() arms.
//
// The security-gating exact-delta proofs count completed responder bursts
// (slave agent burst counts) rather than the cocotb flow's raw valid-pulse
// deltas: the reactive slave driver holds VALID visible across handshake
// latency, so pulse counts per transaction are timing-dependent while burst
// counts are exact. The no-activity windows keep the pulse counters (zero
// is zero in either counting mode).

class dtp_jtag2axi_otp_axi_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_otp_axi_test_seq)

  // OTP address plan (mirrors the cocotb layout inside the 64 KiB
  // responder window).
  localparam bit [63:0] DefaultOtpAddr = 64'h80;
  localparam bit [63:0] DefaultOtpData = 64'h0123_4567;

  typedef struct {
    bit [63:0]   addr;
    int unsigned size;
    bit [63:0]   data;
    bit [7:0]    wstrb;
  } otp_case_t;

  // Selected by the test before start(); body() dispatches on them.
  string target_name = "smc_otp";
  string scenario    = "single_write";

  // Settled status of the scenario's last checked operation.
  dtp_j2a_status_e status = DTP_J2A_SUCCESS;
  int unsigned operation_count = 0;

  function new(string name = "dtp_jtag2axi_otp_axi_test_seq");
    super.new(name);
  endfunction

  protected function dtp_j2a_target_t target();
    case (target_name)
      "smc_otp": return target_smc_otp();
      "sep_otp": return target_sep_otp();
      default: begin
        `uvm_fatal(get_type_name(), $sformatf("unsupported OTP JTAG2AXI target %s", target_name))
        return target_smc_otp();
      end
    endcase
  endfunction

  // TAP reset ending in Run-Test/Idle (scan contract).
  protected task reset_and_idle();
    tap_reset();
    step(1'b0);  // TLR -> RTI
    check_state(RUN_TEST_IDLE, "jtag2axi_scan_chk", "after TLR->RTI step");
  endtask

  // Series beats per pass: at least 2, at most 6, tracking +DTP_RANDOM_COUNT.
  protected function int unsigned series_beats();
    if (random_count < 2) return 2;
    if (random_count > 6) return 6;
    return random_count;
  endfunction

  // Capture shift for the read-series pipeline: returns the payload of the
  // PREVIOUS (priming) SERIES_DATA_INCR/NO_INCR shift.
  protected task series_capture(dtp_j2a_target_t t, dtp_jtag_instr_e instr, input int unsigned size,
                                output bit [63:0] observed);
    bit [63:0] raw;
    series_data_shift(t, instr, '0, size, -1, raw);
    observed = raw & data_mask(size);
  endtask

  // Deterministic AXI-Lite address/size/data/strobe cases: all legal OTP
  // SIZE encodings, two walking-strobe words, then seeded random cases so
  // every loop drives different values (cocotb directed_cases parity).
  function void directed_cases(dtp_j2a_target_t t, ref otp_case_t cases[$]);
    otp_case_t c;
    cases.delete();
    for (int unsigned size = 0; size <= 2; size++) begin
      c.addr  = DefaultOtpAddr + (size * 64'h20);
      c.size  = size;
      c.data  = (DefaultOtpData ^ (64'h1111_1111 * size)) & data_mask(size);
      c.wstrb = full_wstrb(size);
      cases.push_back(c);
    end
    c.addr  = DefaultOtpAddr + 64'h80;
    c.size  = 2;
    c.data  = 64'hA5A5_5A5A;
    c.wstrb = 8'h5;
    cases.push_back(c);
    c.addr  = DefaultOtpAddr + 64'hA0;
    c.size  = 2;
    c.data  = 64'h5A5A_A5A5;
    c.wstrb = 8'hA;
    cases.push_back(c);
    for (int unsigned r = 0; r < random_count; r++) begin
      c.size  = $urandom_range(2);
      c.addr  = random_target_aligned_addr(t, c.size);
      c.data  = 64'($urandom) & data_mask(c.size);
      c.wstrb = 8'($urandom_range(int'(full_wstrb(c.size)), 1));
      cases.push_back(c);
    end
  endfunction

  // -- single_write: directed size and strobe sweep -----------------------
  task run_single_write(dtp_j2a_target_t t);
    otp_case_t cases[$];
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Directed Write", t.name), UVM_LOW)
    directed_cases(t, cases);
    foreach (cases[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: single write addr=0x%08h size=%0d data=0x%0h wstrb=0x%01h",
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
  endtask

  // -- single_write_data_verify: write then read back ---------------------
  task run_single_write_data_verify(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [63:0] addr = DefaultOtpAddr + 64'h100;
    bit [63:0] data = 64'($urandom) & data_mask(size);
    `uvm_info(get_type_name(), $sformatf(
                                   "%s SINGLE_OP Write With Readback: addr=0x%08h data=0x%08h",
                                   t.name, addr, data), UVM_LOW)
    write_target_single_and_check(t, addr, data, status, size, full_wstrb(size),
                                  "write_readback.write");
    read_target_single_and_check(t, addr, data, status, size, "write_readback.read");
    operation_count += 2;
  endtask

  // -- single_write_read: one write plus readback of the same slot ---------
  task run_single_write_read(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [63:0] addr = DefaultOtpAddr + 64'h300;
    bit [63:0] data = 64'($urandom) & data_mask(size);
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Single Write-Read: addr=0x%08h data=0x%08h",
                                         t.name, addr, data), UVM_LOW)
    write_target_single_and_check(t, addr, data, status, size, full_wstrb(size),
                                  "single_wr_rd.write");
    read_target_single_and_check(t, addr, data, status, size, "single_wr_rd.read");
    operation_count += 2;
  endtask

  // -- series_write_incr: incrementing series data sweep -------------------
  task run_series_write_incr(dtp_j2a_target_t t);
    int unsigned size   = t.default_size;
    int unsigned stride = t.beat_bytes;
    int unsigned beats  = series_beats();
    bit [63:0]   base   = random_target_aligned_addr(t, size);
    bit          series_reset;
    bit [63:0]   addr_after;
    int unsigned pl_depth, size_rd;
    int unsigned before_aw, before_w, before_ar;
    int unsigned wb0;
    `uvm_info(get_type_name(), $sformatf("%s SERIES_DATA_INCR Write Sweep: base=0x%08h beats=%0d",
                                         t.name, base, beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, base, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] addr = base + (idx * stride);
      bit [63:0] data = 64'($urandom) & data_mask(size);
      bit [63:0] observed;
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: series incr write addr=0x%08h data=0x%0h", idx + 1, beats, addr, data
          ), UVM_LOW)
      sample_activity(t, before_aw, before_w, before_ar);
      wb0 = write_bursts_now(t);
      series_data_incr(t, data, size);
      wait_for_target_activity(t, before_aw, before_w, before_ar, 1'b0, $sformatf(
                               "series_incr.axi#%0d", idx));
      wait_for_write_completion(t, wb0, $sformatf("series_incr.commit#%0d", idx));
      observed = read_target_mem_int(t, addr, size);
      if (observed !== data)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_incr.mem#%0d: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                   idx,
                   observed,
                   data,
                   addr
                   ))
      operation_count++;
    end
    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    check_status("series_incr.status", status, DTP_J2A_SUCCESS);
    if (addr_after !== ((base + beats * stride) & bit_mask(t.addr_width)))
      `uvm_error(
          "jtag2axi_series_chk", $sformatf(
          "series_incr.addr_after: 0x%0h != expected 0x%0h", addr_after, base + beats * stride))
  endtask

  // -- series_write_no_incr: fixed-address series stream -------------------
  task run_series_write_no_incr(dtp_j2a_target_t t);
    int unsigned size  = t.default_size;
    int unsigned beats = series_beats();
    bit [63:0]   addr  = random_target_aligned_addr(t, size);
    bit [63:0]   last_data = '0;
    bit          series_reset;
    bit [63:0]   addr_after;
    int unsigned pl_depth, size_rd;
    int unsigned before_aw, before_w, before_ar;
    int unsigned wb0;
    `uvm_info(get_type_name(), $sformatf(
                                   "%s SERIES_DATA_NO_INCR Write Sweep: addr=0x%08h beats=%0d",
                                   t.name, addr, beats), UVM_LOW)
    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      bit [63:0] observed;
      last_data = 64'($urandom) & data_mask(size);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series no-incr write addr=0x%08h data=0x%0h",
                idx + 1,
                beats,
                addr,
                last_data
                ), UVM_LOW)
      sample_activity(t, before_aw, before_w, before_ar);
      wb0 = write_bursts_now(t);
      series_data_no_incr(t, last_data, size);
      wait_for_target_activity(t, before_aw, before_w, before_ar, 1'b0, $sformatf(
                               "series_no_incr.axi#%0d", idx));
      wait_for_write_completion(t, wb0, $sformatf("series_no_incr.commit#%0d", idx));
      observed = read_target_mem_int(t, addr, size);
      if (observed !== last_data)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_no_incr.mem#%0d: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                   idx,
                   observed,
                   last_data,
                   addr
                   ))
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
    foreach (words[i]) words[i] = 64'($urandom) & data_mask(plan.size);
    `uvm_info(get_type_name(),
              $sformatf(
                  "%s SERIES_DATA_WITH_ERROR_STATUS Write Mode: base=0x%08h fault_beat=%0d resp=%s",
                  t.name, plan.base, plan.fault_idx, plan.expected.name()), UVM_LOW)
    run_series_status_write(t, plan, words, "series_status");
    recover_target(t, series_status_recovery_addr(plan), 64'($urandom), 1'b0, "series_status",
                   status);
    operation_count += DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_incr_with_error", t, plan, operation_count);
  endtask

  task run_random_ops(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [7:0] image[bit [63:0]];
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Randomized Writes", t.name), UVM_LOW)
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      bit [63:0] addr = random_target_aligned_addr(t, size);
      bit [63:0] data = 64'($urandom) & data_mask(size);
      // Any non-empty legal strobe pattern; the per-write check judges the
      // enabled lanes, the end-state image every lane.
      bit [7:0] wstrb = 8'($urandom_range(int'(full_wstrb(size)), 1));
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: random write addr=0x%08h data=0x%0h wstrb=0x%01h",
                idx,
                random_count,
                addr,
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

  // -- read_random_ops: randomized single reads of preloaded data ----------
  task run_read_random_ops(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Randomized Reads", t.name), UVM_LOW)
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      bit [63:0] addr = random_target_aligned_addr(t, size);
      bit [63:0] data = 64'($urandom) & data_mask(size);
      // Backdoor preload (mirrored into the passive reference model)
      // keeps the read independent of any front-door write path.
      write_target_mem_int(t, addr, data, size);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: random read addr=0x%08h data=0x%0h", idx, random_count, addr, data),
          UVM_LOW)
      read_target_single_and_check(t, addr, data, status, size, $sformatf("random_read#%0d", idx));
      operation_count++;
    end
  endtask

  // -- series_write_read_incr: write leg then per-beat read-back ----------
  task run_series_write_read_incr(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    int unsigned stride = t.beat_bytes;
    int unsigned beats = series_beats();
    bit [63:0] base_addr;
    bit [63:0] expected_q[$];
    bit [63:0] data, mem, obs, addr, addr_after;
    bit series_reset;
    int unsigned pl_depth, size_rd;
    int unsigned aw0, w0, ar0;
    int unsigned wb0;
    `uvm_info(get_type_name(), $sformatf("%s Series Write-Read Incrementing", t.name), UVM_LOW)
    base_addr = random_target_aligned_addr(t, size);

    series_ctrl_op(t, DTP_J2A_OP_WRITE, base_addr, size);
    for (int unsigned idx = 0; idx < beats; idx++) begin
      data = 64'($urandom) & data_mask(size);
      expected_q.push_back(data);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series incr write addr=0x%08h data=0x%0h",
                idx + 1,
                beats,
                base_addr + idx * stride,
                data
                ), UVM_LOW)
      sample_activity(t, aw0, w0, ar0);
      wb0 = write_bursts_now(t);
      series_data_incr(t, data, size);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b0, $sformatf(
                               "series_wr_rd_incr.write_axi#%0d", idx));
      wait_for_write_completion(t, wb0, $sformatf("series_wr_rd_incr.commit#%0d", idx));
      mem = read_target_mem_int(t, base_addr + idx * stride, size);
      if (mem !== data)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_wr_rd_incr.mem#%0d: memory 0x%0h != written 0x%0h (addr=0x%0h)",
                   idx,
                   mem,
                   data,
                   base_addr + idx * stride
                   ))
    end

    foreach (expected_q[idx]) begin
      addr = base_addr + idx * stride;
      series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
      sample_activity(t, aw0, w0, ar0);
      series_data_incr(t, '0, size);  // prime: launches the bus read
      wait_for_target_activity(t, aw0, w0, ar0, 1'b1, $sformatf(
                               "series_wr_rd_incr.read_axi#%0d", idx));
      series_capture(t, t.series_data_incr_instr, size, obs);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: series read incr addr=0x%08h obs=0x%0h", idx + 1, beats, addr, obs),
          UVM_LOW)
      if (obs !== expected_q[idx])
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "series_wr_rd_incr.rdata#%0d: read 0x%0h != expected 0x%0h (addr=0x%0h)",
                   idx,
                   obs,
                   expected_q[idx],
                   addr
                   ))
      operation_count++;
    end

    // The last primed incrementing read advanced the series address by one
    // stride past the last beat.
    check_series_addr(t, addr + stride, size, "series_wr_rd_incr.final", status);
    check_status("series_wr_rd_incr.final", status, DTP_J2A_SUCCESS);
  endtask

  // -- series_write_read_no_incr: fixed-address write/read legs ------------
  task run_series_write_read_no_incr(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    int unsigned beats = series_beats();
    bit [63:0] addr, addr_after, obs, expected;
    bit [63:0] values_q[$];
    bit        series_reset;
    int unsigned pl_depth, size_rd;
    int unsigned aw0, w0, ar0;
    `uvm_info(get_type_name(), $sformatf("%s Series Write-Read No-Increment", t.name), UVM_LOW)
    addr = random_target_aligned_addr(t, size);

    for (int unsigned idx = 0; idx < beats; idx++)
      values_q.push_back(64'($urandom) & data_mask(size));

    series_ctrl_op(t, DTP_J2A_OP_WRITE, addr, size);
    foreach (values_q[idx]) begin
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: series no-incr write addr=0x%08h data=0x%0h",
                idx + 1,
                beats,
                addr,
                values_q[idx]
                ), UVM_LOW)
      sample_activity(t, aw0, w0, ar0);
      series_data_no_incr(t, values_q[idx], size);
      wait_for_target_activity(t, aw0, w0, ar0, 1'b0, $sformatf(
                               "series_wr_rd_no_incr.write_axi#%0d", idx + 1));
    end

    // Every read beat returns the LAST value written to the fixed address.
    expected = values_q[$];
    for (int unsigned idx = 1; idx <= beats; idx++) begin
      series_ctrl_op(t, DTP_J2A_OP_READ, addr, size);
      sample_activity(t, aw0, w0, ar0);
      series_data_no_incr(t, '0, size);  // prime: launches the bus read
      wait_for_target_activity(t, aw0, w0, ar0, 1'b1, $sformatf(
                               "series_wr_rd_no_incr.read_axi#%0d", idx));
      series_capture(t, t.series_data_no_incr_instr, size, obs);
      `uvm_info(
          get_type_name(), $sformatf(
          "Iteration %0d/%0d: series no-incr read addr=0x%08h obs=0x%0h", idx, beats, addr, obs),
          UVM_LOW)
      if (obs !== expected)
        `uvm_error(
            "jtag2axi_data_chk", $sformatf(
            "series_wr_rd_no_incr.rdata#%0d: read 0x%0h != expected 0x%0h", idx, obs, expected))
      operation_count++;
    end

    read_series_ctrl(t, size, series_reset, addr_after, pl_depth, size_rd, status);
    if (addr_after !== (addr & bit_mask(t.addr_width)))
      `uvm_error("jtag2axi_data_chk", $sformatf(
                 "series_wr_rd_no_incr.addr_after: 0x%0h != fixed addr 0x%0h", addr_after, addr))
    check_status("series_wr_rd_no_incr.final", status, DTP_J2A_SUCCESS);
  endtask

  // -- series_write_read_incr_with_error: WITH_ERROR_STATUS both legs ------
  task run_series_write_read_incr_with_error(dtp_j2a_target_t t);
    dtp_j2a_series_status_plan_t plan = plan_series_status(t);
    bit [63:0] words[] = new[DtpJ2aSeriesStatusBeats];
    bit [63:0] expected[];
    dtp_j2a_status_e status;
    foreach (words[i]) words[i] = 64'($urandom) & data_mask(plan.size);
    `uvm_info(get_type_name(), $sformatf("%s Series Write-Read With Error-Status Mode: base=0x%08h",
                                         t.name, plan.base), UVM_LOW)
    run_series_status_write(t, plan, words, "series_wr_rd_status.write");
    dtp_j2a_series_status_final_words(plan, words, expected);
    arm_series_status_fault(t, plan, 1'b1);
    `uvm_info(get_type_name(), $sformatf("read leg: fault_beat=%0d resp=%s", plan.fault_idx,
                                         plan.expected.name()), UVM_LOW)
    run_series_status_read(t, plan, expected, "series_wr_rd_status.read");
    recover_target(t, series_status_recovery_addr(plan), 64'($urandom), 1'b1, "series_wr_rd_status",
                   status);
    operation_count += 2 * DtpJ2aSeriesStatusBeats + 1;
    emit_series_status_nonvacuity("series_write_read_incr_with_error", t, plan, operation_count);
  endtask

  // -- write_security_gating: the port's disable gates the bridge ----------
  task run_write_security_gating(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [63:0] addr = DefaultOtpAddr + 64'h200;
    bit [63:0] data = 64'($urandom) & data_mask(size);
    int unsigned before_aw, before_w, before_ar;
    int unsigned after_aw, after_w, after_ar;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned wr_bursts_gate, rd_bursts_gate;
    `uvm_info(get_type_name(), $sformatf("%s Write Security Gating", t.name), UVM_LOW)

    // Baseline write and activity proof.
    sample_activity(t, before_aw, before_w, before_ar);
    write_target_single_and_check(t, addr, data, status, size, full_wstrb(size), "gate.baseline");
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
      bit [63:0] gate_addr = addr + (idx * t.beat_bytes);
      bit [63:0] sentinel  = 64'h5EA1_0000 | 64'(idx);
      bit [63:0] observed;
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/2: gate %s write with its lifecycle disable", idx, t.name), UVM_LOW)
      gate_target(t);
      // Preload a sentinel at the gated-attempt address: the blocked
      // write must leave memory untouched, both while gated and after
      // the disable is released (a delayed replay would overwrite it).
      write_target_mem_int(t, gate_addr, sentinel, size);
      // Snapshot BEFORE the gated attempt: pulse counters for the
      // no-activity windows, responder burst counts for the exact-
      // delta proof across the whole gate/restore span.
      sample_activity(t, gate_aw, gate_w, gate_ar);
      wr_bursts_gate = write_bursts_now(t);
      rd_bursts_gate = read_bursts_now(t);
      // Gated raw single-op WRITE: issue_single suppresses the intent
      // arming while the target's disable is asserted.
      issue_single(t, DTP_J2A_OP_WRITE, gate_addr, data ^ 64'(idx), full_wstrb(size), size, 1'b0);
      wait_sys_cycles(8);
      sample_activity(t, after_aw, after_w, after_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, after_aw, after_w, after_ar,
                                  $sformatf("gate.pass%0d.no_axi", idx));
      observed = read_target_mem_int(t, gate_addr, size);
      if (observed !== sentinel)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "gate.pass%0d.sentinel: memory 0x%0h != sentinel 0x%0h", idx, observed, sentinel
                   ))
      // Delayed-leak protection: counters must still be flat after the
      // disable is released, before any sanctioned traffic.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, after_aw, after_w, after_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, after_aw, after_w, after_ar,
                                  $sformatf("gate.pass%0d.post_release", idx));
      observed = read_target_mem_int(t, gate_addr, size);
      if (observed !== sentinel)
        `uvm_error("jtag2axi_data_chk", $sformatf(
                   "gate.pass%0d.sentinel_post_release: memory 0x%0h != sentinel 0x%0h",
                   idx,
                   observed,
                   sentinel
                   ))
      // Sanctioned restore write with activity proof.
      sample_activity(t, before_aw, before_w, before_ar);
      write_target_single_and_check(t, addr + (idx * 64'h20), data ^ (64'(idx) << 8), status, size,
                                    full_wstrb(size), $sformatf("gate.pass%0d.restore", idx));
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
            write_bursts_now(
                t
            ),
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
            read_bursts_now(
                t
            ),
            rd_bursts_gate,
            $sformatf(
                "gate.pass%0d target=%s source=responder_burst_counts reads", idx, t.name)
        ));
      end
      operation_count++;
    end
    // CHK-AXI-NONVAC: the counters that stayed flat while gated
    // demonstrably move for real traffic (baseline + both restores).
    sample_activity(t, after_aw, after_w, after_ar);
    emit_nonvacuity_evidence(t, (operation_count >= 2) && (after_aw >= 3), $sformatf(
                             "gated_attempts=%0d aw_pulses=%0d expected_aw>=3 (baseline+2 restores)",
                             operation_count,
                             after_aw
                             ));
  endtask

  // -- read_security_gating: gated reads produce zero request activity -----
  task run_read_security_gating(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [63:0] addr = DefaultOtpAddr + 64'h400;
    bit [63:0] data = 64'($urandom) & data_mask(size);
    int unsigned base_aw, base_w, base_ar;
    int unsigned gate_aw, gate_w, gate_ar;
    int unsigned now_aw, now_w, now_ar;
    int unsigned rd_bursts_gate, wr_bursts_gate;
    `uvm_info(get_type_name(), $sformatf("%s Read Security Gating", t.name), UVM_LOW)
    write_target_mem_int(t, addr, data, size);

    // Baseline read proves the observation path is alive (positive control).
    sample_activity(t, base_aw, base_w, base_ar);
    read_target_single_and_check(t, addr, data, status, size, "read_gate.baseline");
    sample_activity(t, now_aw, now_w, now_ar);
    if (!(now_ar > base_ar))
      `uvm_error("jtag2axi_activity_chk", $sformatf(
                 "read_gate.baseline: expected AR activity for the baseline read (ar %0d -> %0d)",
                 base_ar,
                 now_ar
                 ))

    // Two assert/release passes of the one direct disable prove the gate
    // is repeatable, not a one-shot POR effect.
    for (int unsigned idx = 1; idx <= 2; idx++) begin
      `uvm_info(get_type_name(), $sformatf(
                "Step %0d: gate %s read with its lifecycle disable (pass %0d)", idx + 1, t.name, idx
                ), UVM_LOW)
      gate_target(t);
      // Snapshot BEFORE the gated attempt so a request pulse leaked at
      // shift time is caught: pulse counters for the flat windows,
      // responder burst counts for the exact-delta proof.
      sample_activity(t, gate_aw, gate_w, gate_ar);
      rd_bursts_gate = read_bursts_now(t);
      wr_bursts_gate = write_bursts_now(t);
      issue_single(t, DTP_J2A_OP_READ, addr + idx * t.beat_bytes);  // gated: no intent armed
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, $sformatf(
                                  "read_gate.pass%0d window=gated_attempt+8cyc", idx));
      // Delayed-leak protection: counters must still be flat after the
      // disable releases, before any sanctioned traffic.
      enable_all_debug();
      wait_sys_cycles(8);
      sample_activity(t, now_aw, now_w, now_ar);
      expect_no_activity_evidence(t, gate_aw, gate_w, gate_ar, now_aw, now_w, now_ar, $sformatf(
                                  "read_gate.pass%0d.post_reenable", idx));
      // Restore read, then the exact-delta proof from BEFORE the gated
      // attempt to AFTER the restore: only the sanctioned restore read
      // may complete (read bursts +1, write bursts unchanged); a
      // delayed replay anywhere in the span makes read bursts >= +2.
      read_target_single_and_check(t, addr, data, status, size, $sformatf(
                                   "read_gate.pass%0d.restore", idx));
      sample_activity(t, now_aw, now_w, now_ar);
      if (!(now_ar > gate_ar))
        `uvm_error("jtag2axi_activity_chk", $sformatf(
                   "read_gate.pass%0d.restore: expected AR activity", idx))
      if (axi_evidence != null) begin
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            read_bursts_now(
                t
            ),
            rd_bursts_gate + 1,
            $sformatf(
                {
                  "read_gate.pass%0d target=%s ",
                  "source=responder_burst_counts sanctioned=restore_read(+1)"
                },
                idx,
                t.name)
        ));
        void'(axi_evidence.expect_equal(
            "CHK-AXI-GATE-EXACT",
            write_bursts_now(
                t
            ),
            wr_bursts_gate,
            $sformatf(
                "read_gate.pass%0d target=%s source=responder_burst_counts writes", idx, t.name)
        ));
      end
      operation_count++;
    end

    // CHK-AXI-NONVAC: the counters that stayed flat while gated
    // demonstrably move for real traffic (baseline + both restores).
    sample_activity(t, now_aw, now_w, now_ar);
    emit_nonvacuity_evidence(t, operation_count >= 2 && now_ar >= 3, $sformatf(
                             "gated_attempts=%0d ar_pulses=%0d expected_ar>=3 (baseline+2 restores)",
                             operation_count,
                             now_ar
                             ));
  endtask

  task body();
    dtp_j2a_target_t t = target();
    seed_scenario_rng();
    operation_count = 0;
    `uvm_info(get_type_name(),
              $sformatf("OTP AXI-Lite scenario=%s target=%s scenario_seed=%0d random_count=%0d",
                        scenario, t.name, scenario_seed, random_count), UVM_LOW)
    enable_all_debug();
    reset_and_idle();
    case (scenario)
      "single_write":                      run_single_write(t);
      "single_write_data_verify":          run_single_write_data_verify(t);
      "series_write_incr":                 run_series_write_incr(t);
      "series_write_no_incr":              run_series_write_no_incr(t);
      "series_write_incr_with_error":      run_series_write_incr_with_error(t);
      "random_ops":                        run_random_ops(t);
      "write_security_gating":             run_write_security_gating(t);
      "single_write_read":                 run_single_write_read(t);
      "series_write_read_incr":            run_series_write_read_incr(t);
      "series_write_read_no_incr":         run_series_write_read_no_incr(t);
      "series_write_read_incr_with_error": run_series_write_read_incr_with_error(t);
      "read_random_ops":                   run_read_random_ops(t);
      "read_security_gating":              run_read_security_gating(t);
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown OTP JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    // Scenario-level stream minimum (cocotb CHK-AXI-STREAM-MIN parity).
    emit_nonvacuity_evidence(
        t, operation_count >= 2, $sformatf(
        "scenario=%s target=%s operations=%0d min_ops=2", scenario, t.name, operation_count));
    `uvm_info(get_type_name(),
              $sformatf(
                  "OTP AXI-Lite scenario complete: target=%s scenario=%s operations=%0d status=%s",
                  t.name, scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_otp_axi_test_seq
