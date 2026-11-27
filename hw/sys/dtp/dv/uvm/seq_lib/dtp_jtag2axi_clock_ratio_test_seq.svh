// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI Run-Test/Idle cycles across TCK and system clock ratios. Each pass
// retimes the system clock into one band of TCK-to-system-clock ratio, taken
// in a seeded order: near 1, 1.25 to 3, 3 to 12, and above 12 with the system
// clock at 10 ns or slower. The system clock stays faster than TCK, and a
// band the run's TCK period cannot reach is skipped. On each bridge, in a
// seeded order, the pass then probes a DMI operation at every distance from
// the shortest the TAP allows to DtpDmiSettleTck + 2, in a seeded order. A
// distance counts TCK cycles from the one that leaves the operation's
// Update-DR. A read of sbaddress0 is probed by the capture of the next DMI
// scan, chained from Update-DR at two cycles and from Run-Test/Idle beyond. A
// write of sbaddress0 is probed by the update of a scan that shifts no bit,
// two cycles after that scan's capture, and the status it left is read after
// the bench's idle cycles. A probe within DtpDmiBusyTck cycles reads busy and
// one DtpDmiSettleTck cycles or more after reads 0; between the two the
// bridge model accepts either. Each probe ends with an op-3 scan that leaves
// status 0 and the written value in the DMI register, so the next scan's
// capture shows the read data. Each bridge then makes a bus write and a bus
// read at the pass's ratio, and the pass restores the drawn system clock
// period with every bridge idle. The cocotb twin is
// seq_lib/dtp_jtag2axi_clock_ratio_test_seq.py.

class dtp_jtag2axi_clock_ratio_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_clock_ratio_test_seq)

  // Shortest probe distances: a scan chained from Update-DR captures two TCK
  // cycles after it, and a scan that shifts no bit updates two cycles after
  // its capture.
  localparam int unsigned CaptureMinTck = 2;
  localparam int unsigned UpdateMinTck = 4;
  localparam int unsigned ProbeMaxTck = DtpDmiSettleTck + 2;
  localparam int unsigned SysClkMinNs = 10;
  // System clock cycles between a retime and the next scan.
  localparam int unsigned RetimeSettleCycles = 16;
  localparam int unsigned NumBands = 4;
  localparam string BandNames[NumBands] = '{"near 1", "1.25 to 3", "3 to 12", "above 12"};

  typedef bit [1:0] statuses_t[int unsigned];

  // The address and data the bridge's DMI register holds, with status 0.
  protected bit [31:0] m_dmi_value;

  function new(string name = "dtp_jtag2axi_clock_ratio_test_seq");
    super.new(name);
  endfunction

  task body();
    string       names [$] = '{"smc_otp", "sep_otp", "smc_axi"};
    int unsigned drawn = tb_vif.clk_period_ns;
    int unsigned band;
    int unsigned period;
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== JTAG2AXI Run-Test/Idle cycles across clock ratios ===", UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    pass_period(band, period);
    `uvm_info(get_type_name(),
              $sformatf("Ratio band %s: TCK %0d ns, system clock %0d ns retimed to %0d ns",
                        BandNames[band], test_cfg.tck_period_ns, drawn, period), UVM_LOW)
    retime(period);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      string           ctx = $sformatf("%s.ratio_%0d", t.name, band);
      sweep(t, ctx);
      port_access(t, 1'b0, DtpJ2aIdleCheckId, ctx);
      port_access(t, 1'b1, DtpJ2aIdleCheckId, ctx);
      check_responder_activity(t, 2, ctx);
    end
    retime(drawn);
  endtask

  // The lowest and highest even system clock periods that put the
  // TCK-to-system-clock ratio in `band`; `low` is above `high` when the TCK
  // period cannot reach it.
  static function void band_periods(int unsigned band, int unsigned tck_ns, output int unsigned low,
                                    output int unsigned high);
    int unsigned edges[NumBands+1] = '{
        tck_ns,
        2 * ((4 * tck_ns + 9) / 10),
        2 * ((tck_ns + 5) / 6),
        2 * ((tck_ns + 23) / 24),
        SysClkMinNs
    };
    low  = (edges[band+1] > SysClkMinNs) ? edges[band+1] : SysClkMinNs;
    high = edges[band] - 2;
  endfunction

  // The bands in the order the run's seed gives them, the same in both
  // realizations.
  function void band_order(output int unsigned order[$]);
    int unsigned index;
    int unsigned bands [$] = '{0, 1, 2, 3};
    int unsigned radix [NumBands] = '{6, 2, 1, 1};
    index = ocah_rng::salted_seed(scenario_seed - loop_index, "clock_ratio_bands") % 24;
    order = {};
    foreach (radix[i]) begin
      order.push_back(bands[index/radix[i]]);
      bands.delete(index / radix[i]);
      index %= radix[i];
    end
  endfunction

  // The pass's band, from the run's seeded order of the bands its TCK period
  // reaches, and a seeded even system clock period inside it.
  function void pass_period(output int unsigned band, output int unsigned period);
    int unsigned order    [$];
    int unsigned reachable[$];
    int unsigned low;
    int unsigned high;
    band_order(order);
    foreach (order[i]) begin
      band_periods(order[i], test_cfg.tck_period_ns, low, high);
      if (low <= high) reachable.push_back(order[i]);
    end
    band = reachable[loop_index%reachable.size()];
    band_periods(band, test_cfg.tck_period_ns, low, high);
    period = 2 * $urandom_range(high / 2, low / 2);
  endfunction

  // Give the system clock `period_ns`; every bridge is idle.
  task retime(int unsigned period_ns);
    @(negedge tb_vif.clk);
    tb_vif.clk_period_ns = period_ns;
    wait_sys_cycles(RetimeSettleCycles);
  endtask

  // Probe a write and a read at every distance, each kind in its own seeded
  // order; CHK-J2A-IDLE judges the probes at and beyond the two bounds.
  task sweep(dtp_j2a_target_t t, string ctx);
    int unsigned reads [$];
    int unsigned writes[$];
    statuses_t   read_status;
    statuses_t   write_status;
    dtp_sbcs_t   sbcs = '0;
    activate_dm(t);
    sbcs.sbaccess = 3'(t.default_size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {ctx, ".sbcs"});
    m_dmi_value = random_sbaddress0(t);
    dmi_write(t, DTP_DM_SBADDRESS0, m_dmi_value, {ctx, ".setup"});
    select_dmi(t);
    for (int unsigned d = CaptureMinTck; d <= ProbeMaxTck; d++) reads.push_back(d);
    for (int unsigned d = UpdateMinTck; d <= ProbeMaxTck; d++) writes.push_back(d);
    reads.shuffle();
    writes.shuffle();
    while (reads.size() != 0 || writes.size() != 0) begin
      if (writes.size() != 0) begin
        int unsigned d = writes.pop_front();
        write_probe(t, d, $sformatf("%s.write@%0d", ctx, d), write_status[d]);
      end
      if (reads.size() != 0) begin
        int unsigned d = reads.pop_front();
        read_probe(t, d, $sformatf("%s.read@%0d", ctx, d), read_status[d]);
      end
    end
    dmi_raw(t, '0, '0, DTP_DMI_OP_NOP, DTP_DMI_SUCCESS, {ctx, ".last"}, 1'b0, 1'b1,
            DTP_DM_SBADDRESS0, m_dmi_value);
    check_bounds(t, read_status, write_status, ctx);
  endtask

  // Write a seeded sbaddress0 and update a scan that shifts no bit
  // `distance` TCK cycles later; `status` is the status that update left.
  task write_probe(input dtp_j2a_target_t t, input int unsigned distance, input string ctx,
                   output bit [1:0] status);
    bit [31:0] value = random_sbaddress0(t);
    bit        chain = distance == UpdateMinTck;
    dmi_raw(t, DTP_DM_SBADDRESS0, value, DTP_DMI_OP_WRITE, DTP_DMI_SUCCESS, ctx, chain, 1'b1,
            DTP_DM_SBADDRESS0, m_dmi_value);
    if (!chain) begin
      if (distance > UpdateMinTck + 1) run_test_idle(distance - UpdateMinTck - 1);
      step(1'b1);
      m_dr_chained = 1'b1;
    end
    dmi_zero_shift();
    run_test_idle(DmiIdleTck);
    m_dmi_value = value;
    clear_scan(t, value, {ctx, ".status"}, status);
  endtask

  // Read sbaddress0 and capture the next DMI scan `distance` TCK cycles
  // later; `status` is the status that capture shows.
  task read_probe(input dtp_j2a_target_t t, input int unsigned distance, input string ctx,
                  output bit [1:0] status);
    bit [31:0] op_data = $urandom();
    bit        chain = distance == CaptureMinTck;
    dmi_raw(t, DTP_DM_SBADDRESS0, op_data, DTP_DMI_OP_READ, DTP_DMI_SUCCESS, ctx, chain, 1'b1,
            DTP_DM_SBADDRESS0, m_dmi_value);
    if (distance > CaptureMinTck + 1) run_test_idle(distance - CaptureMinTck - 1);
    clear_scan(t, op_data, {ctx, ".capture"}, status);
  endtask

  // A DMI scan whose update is op 3 of sbaddress0 and the written value,
  // which leaves status 0 and that address and data whichever status it
  // captured. `status` is the captured status; the captured data is judged
  // against `busy_data` with busy and the written value otherwise.
  task clear_scan(input dtp_j2a_target_t t, input bit [31:0] busy_data, input string ctx,
                  output bit [1:0] status);
    bit       [63:0] captured;
    bit       [63:0] observed;
    bit       [63:0] predicted;
    bit       [31:0] expected;
    dtp_dmi_t        dmi;
    dmi_shift(DTP_DM_SBADDRESS0, m_dmi_value, DTP_DMI_OP_CLEAR, 1'b0, captured);
    dmi       = dtp_j2a_unpack_dmi(captured);
    status    = dmi.op;
    expected  = (status == DTP_DMI_BUSY) ? busy_data : m_dmi_value;
    observed  = dtp_j2a_pack_dmi(dmi.address, dmi.data, '0) >> 2;
    predicted = dtp_j2a_pack_dmi(DTP_DM_SBADDRESS0, expected, '0) >> 2;
    check_dtm_capture(t, observed, predicted, $sformatf("%s status=%0d", ctx, status));
  endtask

  // CHK-J2A-IDLE: every probe within DtpDmiBusyTck reads busy and every
  // probe DtpDmiSettleTck or more after reads 0, a bound the bench's idle
  // cycles exceed.
  function void check_bounds(dtp_j2a_target_t t, statuses_t reads, statuses_t writes, string ctx);
    string read_from;
    string write_from;
    string read_busy;
    string write_busy;
    record_field(t, DtpJ2aIdleCheckId, "settle_below_idle", 64'(DtpDmiSettleTck < DmiIdleTck),
                 64'd1, ctx);
    check_kind(t, "read", reads, CaptureMinTck, ctx);
    check_kind(t, "write", writes, UpdateMinTck, ctx);
    read_from  = complete_from(reads, CaptureMinTck);
    write_from = complete_from(writes, UpdateMinTck);
    read_busy  = busy_list(reads);
    write_busy = busy_list(writes);
    `uvm_info(get_type_name(), $sformatf(
              "Summary: %s Run-Test/Idle at TCK %0d ns, system clock %0d ns: read_complete_from_rti=%s write_complete_from_rti=%s dtmcs_idle=%0d read_busy=%s write_busy=%s",
              t.name,
              test_cfg.tck_period_ns,
              tb_vif.clk_period_ns,
              read_from,
              write_from,
              DtpExpectedDtmcs[14:12],
              read_busy,
              write_busy
              ), UVM_LOW)
  endfunction

  // CHK-J2A-IDLE on one kind of probe. +DTP_J2A_IDLE_NEGATIVE expects 0 from
  // the shortest probe, so the run must fail.
  function void check_kind(dtp_j2a_target_t t, string kind, statuses_t statuses,
                           int unsigned shortest, string ctx);
    foreach (statuses[d]) begin
      bit [1:0] expected;
      if (d > DtpDmiBusyTck && d < DtpDmiSettleTck) continue;
      expected = (d <= DtpDmiBusyTck) ? DTP_DMI_BUSY : DTP_DMI_SUCCESS;
      if (test_cfg.j2a_idle_negative && d == shortest) expected = DTP_DMI_SUCCESS;
      record_field(t, DtpJ2aIdleCheckId, $sformatf("%s probed %0d TCK after update", kind, d),
                   64'(statuses[d]), 64'(expected), ctx);
    end
  endfunction

  // The shortest probe that read 0, as the DTMCS idle value that reaches it.
  static function string complete_from(statuses_t statuses, int unsigned shortest);
    foreach (statuses[d]) if (statuses[d] == DTP_DMI_SUCCESS) return $sformatf("%0d", d - shortest);
    return "none";
  endfunction

  static function string busy_list(statuses_t statuses);
    string s;
    foreach (statuses[d]) begin
      if (statuses[d] == DTP_DMI_BUSY) s = {s, s.len() ? ", " : "", $sformatf("%0d", d)};
    end
    return {"[", s, "]"};
  endfunction

endclass : dtp_jtag2axi_clock_ratio_test_seq
