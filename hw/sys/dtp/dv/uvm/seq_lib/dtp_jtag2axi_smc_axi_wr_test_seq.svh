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
// The series, with-error and security-gating flows are the family layer's
// (dtp_jtag2axi_base_test_seq), shared with the OTP bridges. The
// security-gating exact-delta proof counts completed responder bursts
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
    log_step("1", "Run deterministic size and strobe sweep");
    directed_cases(t, cases);
    foreach (cases[idx]) begin
      log_iteration(idx + 1, cases.size(), $sformatf(
                    "single write addr=0x%08h size=%0d data=0x%0h wstrb=0x%02h",
                    cases[idx].addr,
                    cases[idx].size,
                    cases[idx].data,
                    cases[idx].wstrb
                    ));
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
      log_step("2", "Capture SERIES_CTRL after SINGLE_OP polls");
      read_series_ctrl(t, 3, series_reset, addr_after, pl_depth, size_rd, status);
      check_status(t, "single_write.series_ctrl", status, DTP_J2A_SUCCESS);
    end
  endtask

  // -- single_write_data_verify: write then read back ---------------------
  task run_single_write_data_verify(dtp_j2a_target_t t);
    `uvm_info(get_type_name(), "SMC_AXI_SINGLE_OP Write With Readback", UVM_LOW)
    log_step("1", "Write non-trivial data, then read it back through JTAG2AXI");
    write_neighbour_then_read(t, DefaultAxiAddr + 64'h200, "write_readback", status);
    operation_count += 3;
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
    `uvm_info(get_type_name(),
              $sformatf("SMC_AXI_SERIES_DATA_INCR 32-bit Write Sweep at +4: base=0x%08h beats=%0d",
                        base, beats), UVM_LOW)
    log_step("1", "Program SERIES_CTRL for 32-bit incrementing writes at +4");
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
    log_step("2", "Verify the stream footprint: every word intact, sentinel untouched");
    check_narrow_footprint(t, sentinel_addr, sentinel, word_addrs, words, size);
    check_series_addr(t, base + beats * stride, size, "series_incr_narrow", status);
    check_status(t, "series_incr_narrow.status", status, DTP_J2A_SUCCESS);
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
    log_iteration(idx + 1, beats, $sformatf(
                  "series incr narrow write addr=0x%014h data=0x%0h wstrb=0x%02h", addr, data, wstrb
                  ));
    // Stimulus intents (CHK-AXI-WADDR / CHK-AXI-STRB / CHK-AXI-WDATA); the
    // data intent sits in the strobed lanes.
    axi_cfg.arm_expected_write(addr & bit_mask(t.addr_width), data << (8 * (addr % t.beat_bytes)),
                               wstrb);
    series_write_beat(t, data, addr, size, 1'b1, $sformatf("series_incr_narrow#%0d", idx));
    check_series_addr(t, addr + size_bytes(size), size, $sformatf("series_incr_narrow.beat#%0d", idx
                      ), beat_status);
    check_status(t, $sformatf("series_incr_narrow.status#%0d", idx), beat_status, DTP_J2A_SUCCESS);
  endtask

  // After the stream: no beat spilled onto the sentinel word or a
  // neighbour's word.
  protected function void check_narrow_footprint(dtp_j2a_target_t t, bit [63:0] sentinel_addr,
                                                 bit [63:0] sentinel, bit [63:0] word_addrs[$],
                                                 bit [63:0] words[$], int unsigned size);
    check_target_memory(t, sentinel_addr, sentinel, size, "series_incr_narrow.sentinel");
    foreach (words[idx])
    check_target_memory(t, word_addrs[idx], words[idx], size, $sformatf(
                        "series_incr_narrow.final#%0d", idx));
  endfunction

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
      log_iteration(
          idx, random_count, $sformatf(
          "random write addr=0x%08h size=%0d data=0x%0h wstrb=0x%02h", addr, size, data, wstrb));
      snapshot_target_word(t, image, addr, size);
      write_target_single_and_check(t, addr, data, status, size, wstrb, $sformatf(
                                    "random_write#%0d", idx));
      image_write(image, addr, data, wstrb, size);
      operation_count++;
    end
    check_memory_image(t, image, "random_write");
  endtask

  task body();
    dtp_j2a_target_t t = target_smc_axi();
    seed_scenario_rng();
    use_target(t);
    `uvm_info(get_type_name(),
              $sformatf("SMC fabric write-side scenario=%s scenario_seed=%0d random_count=%0d",
                        scenario, scenario_seed, random_count), UVM_LOW)
    enable_all_debug();
    reset_to_rti();
    case (scenario)
      "single_write":                 run_single_write(t);
      "single_write_data_verify":     run_single_write_data_verify(t);
      "series_write_incr":            run_series_write_incr(t);
      "series_write_incr_narrow":     run_series_write_incr_narrow(t);
      "series_write_no_incr":         run_series_write_no_incr(t);
      "series_write_incr_with_error": run_series_write_incr_with_error(t);
      "random_ops":                   run_random_ops(t);
      "write_security_gating":        run_write_security_gating(t, DefaultAxiAddr + 64'h300);
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown write-side JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    // Scenario-level operation minimum (cocotb CHK-AXI-STREAM-MIN parity);
    // +DTP_RANDOM_COUNT=1 leaves random_ops one operation per pass.
    emit_nonvacuity_evidence(t, operation_count >= 1, $sformatf(
                             "scenario=%s operations=%0d min_ops=1", scenario, operation_count));
    `uvm_info(get_type_name(),
              $sformatf(
                  "SMC fabric write-side scenario complete: scenario=%s operations=%0d status=%s",
                  scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_smc_axi_wr_test_seq
