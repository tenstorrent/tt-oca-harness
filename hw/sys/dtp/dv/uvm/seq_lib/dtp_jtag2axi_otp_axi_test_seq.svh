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
//   random_ops                    randomized single writes at the bus width
//   write_security_gating         the port's disable gates the bridge
//   single_write_read             one write plus readback of the same slot
//   series_write_read_incr        incrementing series write leg then per-beat
//                                 SERIES read-back (prime + capture shifts)
//   series_write_read_incr_oversize  series_write_read_incr with the size
//                                 field at its maximum, above the bus width:
//                                 every beat is one full bus-width beat
//   series_write_read_no_incr     fixed-address series: every read beat
//                                 returns the last value written
//   series_write_read_incr_with_error  *_WITH_ERROR_STATUS mode, mixed
//                                 increment pattern on both legs, one armed
//                                 fault beat on the read leg
//   read_random_ops               randomized single reads of backdoor-
//                                 preloaded data at the bus width
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
// shared AXI scoreboard through the intents issue_single() arms. The series,
// with-error and security-gating flows are the family layer's
// (dtp_jtag2axi_base_test_seq), shared with the SMC fabric bridge.
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

  function new(string name = "dtp_jtag2axi_otp_axi_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    if (scenario == "write_security_gating" || scenario == "read_security_gating") return "";
    return target_name;
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
      c.addr  = random_upper_addr(t);
      c.addr |= random_target_aligned_addr(t, c.size);
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
      log_iteration(idx + 1, cases.size(), $sformatf(
                    "single write addr=0x%08h size=%0d data=0x%0h wstrb=0x%01h",
                    cases[idx].addr,
                    cases[idx].size,
                    cases[idx].data,
                    cases[idx].wstrb
                    ));
      write_target_single_and_check(t, cases[idx].addr, cases[idx].data, status, cases[idx].size,
                                    cases[idx].wstrb, $sformatf("single_write#%0d", idx + 1));
      operation_count++;
    end
  endtask

  // -- single_write_data_verify: write then read back ---------------------
  task run_single_write_data_verify(dtp_j2a_target_t t);
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Write With Readback", t.name), UVM_LOW)
    write_neighbour_then_read(t, DefaultOtpAddr + 64'h100, "write_readback", status);
    operation_count += 3;
  endtask

  // -- single_write_read: one write plus readback of the same slot ---------
  task run_single_write_read(dtp_j2a_target_t t);
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Single Write-Read", t.name), UVM_LOW)
    write_neighbour_then_read(t, DefaultOtpAddr + 64'h300, "single_wr_rd", status);
    operation_count += 3;
  endtask

  task run_random_ops(dtp_j2a_target_t t);
    int unsigned size = t.default_size;
    bit [7:0] image[bit [63:0]];
    `uvm_info(get_type_name(), $sformatf("%s SINGLE_OP Randomized Writes", t.name), UVM_LOW)
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      bit [63:0] upper = random_upper_addr(t);
      bit [63:0] addr = upper | random_target_aligned_addr(t, size);
      bit [63:0] data = 64'($urandom) & data_mask(size);
      // Any non-empty legal strobe pattern; the per-write check judges the
      // enabled lanes, the end-state image every lane.
      bit [7:0] wstrb = 8'($urandom_range(int'(full_wstrb(size)), 1));
      log_iteration(idx, random_count, $sformatf(
                    "random write addr=0x%08h data=0x%0h wstrb=0x%01h", addr, data, wstrb));
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
      bit [63:0] upper = random_upper_addr(t);
      bit [63:0] addr = upper | random_target_aligned_addr(t, size);
      bit [63:0] data = 64'($urandom) & data_mask(size);
      // Backdoor preload (mirrored into the passive reference model)
      // keeps the read independent of any front-door write path.
      write_target_mem_int(t, addr, data, size);
      log_iteration(idx, random_count, $sformatf("random read addr=0x%08h data=0x%0h", addr, data));
      read_target_single_and_check(t, addr, data, status, size, $sformatf("random_read#%0d", idx));
      operation_count++;
    end
  endtask

  // A size field above the bus width moves full bus-width beats.
  task run_series_write_read_incr_oversize(dtp_j2a_target_t t);
    int unsigned size = (1 << t.size_bits) - 1;
    `uvm_info(get_type_name(), $sformatf("%s Series Write-Read With An Oversized Size Field",
                                         t.name), UVM_LOW)
    if (size <= dtp_j2a_data_size(t))
      `uvm_fatal(get_type_name(), $sformatf("%s size field cannot exceed the bus width", t.name))
    run_series_write_read_incr(t, size, "series_wr_rd_incr_oversize");
  endtask

  task body();
    dtp_j2a_target_t t = target();
    seed_scenario_rng();
    use_target(t);
    operation_count = 0;
    `uvm_info(get_type_name(),
              $sformatf("OTP AXI-Lite scenario=%s target=%s scenario_seed=%0d random_count=%0d",
                        scenario, t.name, scenario_seed, random_count), UVM_LOW)
    enable_all_debug();
    reset_to_rti();
    case (scenario)
      "single_write":                      run_single_write(t);
      "single_write_data_verify":          run_single_write_data_verify(t);
      "series_write_incr":                 run_series_write_incr(t);
      "series_write_no_incr":              run_series_write_no_incr(t);
      "series_write_incr_with_error":      run_series_write_incr_with_error(t);
      "random_ops":                        run_random_ops(t);
      "write_security_gating":             run_write_security_gating(t, DefaultOtpAddr + 64'h200);
      "single_write_read":                 run_single_write_read(t);
      "series_write_read_incr": begin
        `uvm_info(get_type_name(), $sformatf("%s Series Write-Read Incrementing", t.name), UVM_LOW)
        run_series_write_read_incr(t, t.default_size, "series_wr_rd_incr");
      end
      "series_write_read_incr_oversize":   run_series_write_read_incr_oversize(t);
      "series_write_read_no_incr": begin
        `uvm_info(get_type_name(), $sformatf("%s Series Write-Read No-Increment", t.name), UVM_LOW)
        run_series_write_read_no_incr(t);
      end
      "series_write_read_incr_with_error": begin
        `uvm_info(get_type_name(), $sformatf("%s Series Write-Read With Error-Status Mode",
                                             t.name), UVM_LOW)
        run_series_write_read_incr_with_error(t);
      end
      "read_random_ops":                   run_read_random_ops(t);
      "read_security_gating": begin
        `uvm_info(get_type_name(), $sformatf("%s Read Security Gating", t.name), UVM_LOW)
        run_read_security_gating(t, DefaultOtpAddr + 64'h400);
      end
      default:
                `uvm_fatal(get_type_name(), $sformatf(
                    "unknown OTP JTAG2AXI scenario %s", scenario))
    endcase
    enable_all_debug();
    // Scenario-level operation minimum (cocotb CHK-AXI-STREAM-MIN parity);
    // +DTP_RANDOM_COUNT=1 leaves the random scenarios one operation per pass.
    emit_nonvacuity_evidence(
        t, operation_count >= 1, $sformatf(
        "scenario=%s target=%s operations=%0d min_ops=1", scenario, t.name, operation_count));
    `uvm_info(get_type_name(),
              $sformatf(
                  "OTP AXI-Lite scenario complete: target=%s scenario=%s operations=%0d status=%s",
                  t.name, scenario, operation_count, status.name()), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_otp_axi_test_seq
