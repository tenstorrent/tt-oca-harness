// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI transfers under responder back-pressure on every bridge, each
// bridge in a seeded order. Each bridge's responder stalls AWREADY, WREADY
// and ARREADY and delays B and R, every channel from its own seeded stream,
// and takes a write's first W beat alongside its AW. Each channel takes every
// timing mode, no stall, short stalls, stalls of one to two sbcs polls and a
// seeded mix of short and long, in a seeded order of its own, so a long stall
// on one channel meets a short or no stall on another. W takes the mode paired
// with AW's, so the AW and W handshakes land in every order. Under each timing
// the bridge writes two neighbouring beats, reads the first back, then writes
// and reads back seeded lanes of it at a seeded size. Every access is judged on
// the bus (CHK-J2A-BUS-REQ, CHK-J2A-AXI-ATTR), in the responder memory and on
// the data the debugger fetches, and every sbcs poll against the bridge
// model; the port raises no request while one is open (CHK-J2A-ONE-XFER).
// With a write and then a read held open, the access a second sbdata0 or
// sbaddress0 write would start is refused with sbbusyerror and reaches no
// port. The cocotb twin is seq_lib/dtp_jtag2axi_backpressure_test_seq.py.

class dtp_jtag2axi_backpressure_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_backpressure_test_seq)

  typedef enum int unsigned {
    TIMING_NONE,
    TIMING_SHORT,
    TIMING_LONG,
    TIMING_MIXED
  } timing_mode_e;

  // Every responder channel with a seeded stream: the READY stalls of AW, W
  // and AR, and the B and R response delays.
  localparam int unsigned TimingChannels = 5;
  localparam int unsigned ChannelAw = 0;
  localparam int unsigned ChannelW = 1;
  localparam int unsigned TimingModes = 4;
  localparam int unsigned ShortMin = 1;
  localparam int unsigned ShortMax = 8;
  // Percentages of long draws in the mixed mode.
  localparam int unsigned MixedLongPercentMin = 10;
  localparam int unsigned MixedLongPercentMax = 40;
  // Long draws, in sbcs polls; three channels of one write at the top of the
  // range end within SbaPolls polls.
  localparam int unsigned LongPollsMin = 1;
  localparam int unsigned LongPollsMax = 2;
  // Write-and-read rounds under each timing.
  localparam int unsigned Rounds = 2;

  protected string m_ledger;

  function new(string name = "dtp_jtag2axi_backpressure_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return m_ledger;
  endfunction

  task body();
    string names[$] = '{"smc_otp", "sep_otp", "smc_axi"};
    seed_scenario_rng();
    `uvm_info(get_type_name(), "=== Transfers under responder back-pressure on every bridge ===",
              UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    names.shuffle();
    foreach (names[n]) begin
      dtp_j2a_target_t t = dtp_j2a_target_by_name(names[n]);
      m_ledger = t.name;
      open_bus_ledger();
      backpressure_case(t);
      check_responder_activity(t, 1, {t.name, ".backpressure"});
      close_bus_ledger();
      m_ledger = "";
      `uvm_info(get_type_name(), $sformatf(
                "Summary: %s transfers under back-pressure complete", t.name), UVM_LOW)
    end
  endtask

  // Every timing mode on every channel of `t`, each channel but W in its own
  // seeded order, with Rounds write-and-read rounds under each timing, then
  // the busy attempts.
  task backpressure_case(dtp_j2a_target_t t);
    timing_mode_e                 schedule[TimingChannels][$];
    int unsigned                  poll;
    int unsigned                  since;
    poll_cycles(t, poll);
    since = open_request_count(t);
    for (int unsigned c = 0; c < TimingChannels; c++) begin
      schedule[c] = '{TIMING_NONE, TIMING_SHORT, TIMING_LONG, TIMING_MIXED};
      schedule[c].shuffle();
    end
    foreach (schedule[ChannelAw][s]) begin
      schedule[ChannelW][s] = w_mode_with_aw(schedule[ChannelAw][s]);
    end
    for (int unsigned s = 0; s < TimingModes; s++) begin
      string          ctx = $sformatf("%s.timing%0d", t.name, s);
      ocah_axi_delays streams[TimingChannels];
      foreach (streams[c]) streams[c] = delays(schedule[c][s], poll);
      `uvm_info(get_type_name(), $sformatf(
                "%s poll=%0d cycles modes aw=%s w=%s ar=%s b=%s r=%s",
                ctx,
                poll,
                schedule[0][s].name(),
                schedule[1][s].name(),
                schedule[2][s].name(),
                schedule[3][s].name(),
                schedule[4][s].name()
                ), UVM_LOW)
      apply_responder_timing(t, streams[0], streams[1], streams[2], streams[3], streams[4]);
      for (int unsigned r = 0; r < Rounds; r++) begin
        write_and_read_round(t, $sformatf("%s.round%0d", ctx, r));
      end
    end
    clear_responder_timing(t);
    busy_attempt_case(t);
    check_one_transfer(t, since, {t.name, ".backpressure"});
  endtask

  // A second access requested while one is open: under a held write, an
  // sbdata0 write that would start the next write, and under a held read, an
  // sbaddress0 write that would start the next read. The held write lands
  // with its own data and the held read returns it.
  task busy_attempt_case(dtp_j2a_target_t t);
    string           ctx = {t.name, ".busy_attempt"};
    int unsigned     size = t.default_size;
    bit [63:0]       addr = random_target_addr(t);
    bit [63:0]       data = random_distinct_word(t);
    bit [7:0]        wstrb = dtp_j2a_full_wstrb(size);
    bit [63:0]       rdata;
    bit [31:0]       word;
    ocah_axi_checker ev = evidence(t);
    if (target_enabled(t))
      target_cfgs[t.name].arm_expected_write(addr & bit_mask(t.addr_width), data, wstrb);
    sba_setup(t, addr, size, 1'b0, {ctx, ".write"});
    hold_responses(t, 1'b1, 1'b0);
    if (size == 3) dmi_write(t, DTP_DM_SBDATA1, data[63:32], {ctx, ".write.sbdata1"});
    dmi_write(t, DTP_DM_SBDATA0, data[31:0], {ctx, ".write.sbdata0"});
    refuse_while_open(t, DTP_DM_SBDATA0, {ctx, ".write"});
    hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, 1'b0, addr, size, data, wstrb, {ctx, ".write"});
    wait_sba_idle(t, {ctx, ".write.released"}, 1'b1);
    check_target_word(t, addr, data, size, {ctx, ".write.mem"});
    clear_sbbusyerror(t, size, {ctx, ".write"});
    if (target_enabled(t)) target_cfgs[t.name].arm_expected_read(addr & bit_mask(t.addr_width));
    hold_responses(t, 1'b0, 1'b1);
    sba_setup(t, addr, size, 1'b1, {ctx, ".read"});
    refuse_while_open(t, DTP_DM_SBADDRESS0, {ctx, ".read"});
    hold_responses(t, 1'b0, 1'b0);
    expect_bus_request(t, 1'b1, addr, size, '0, '0, {ctx, ".read"});
    wait_sba_idle(t, {ctx, ".read.released"}, 1'b1);
    clear_sbbusyerror(t, size, {ctx, ".read"});
    dmi_read(t, DTP_DM_SBDATA0, {ctx, ".read.sbdata0"}, word);
    rdata = 64'(word);
    if (size == 3) begin
      dmi_read(t, DTP_DM_SBDATA1, {ctx, ".read.sbdata1"}, word);
      rdata[63:32] = word;
    end
    void'(ev.expect_equal(
        "CHK-AXI-RDATA",
        rdata,
        data,
        $sformatf(
            "%s.read target=%s source=bridge_capture", ctx, t.name)
    ));
  endtask

  // With the access just started held open, a seeded write to `address`
  // takes a busy DMI status, which the next scan clears; sbcs then reads
  // sbbusy and sbbusyerror 1, and the port raised no request for it.
  task refuse_while_open(dtp_j2a_target_t t, dtp_dm_reg_e address, string context_s);
    bit [31:0]       refused = $urandom();
    bit [31:0]       value;
    bit [1:0]        held_bits;
    dtp_sbcs_t       sbcs;
    int unsigned     since = open_request_count(t);
    ocah_axi_checker ev = evidence(t);
    dmi_write(t, address, refused, {context_s, ".refused"});
    select_dmi(t);
    dmi_raw(t, '0, '0, DTP_DMI_OP_CLEAR, DTP_DMI_BUSY, {context_s, ".refused_clear"}, 1'b0, 1'b1,
            address, refused);
    dmi_read(t, DTP_DM_SBCS, {context_s, ".held_sbcs"}, value);
    sbcs      = dtp_sbcs_t'(value);
    held_bits = {sbcs.sbbusy, sbcs.sbbusyerror};
    void'(ev.expect_equal(
        DtpJ2aFaultStatusCheckId,
        64'(held_bits),
        64'h3,
        $sformatf(
            "%s target=%s held (sbbusy, sbbusyerror)", context_s, t.name)
    ));
    check_one_transfer(t, since, {context_s, ".refused"});
  endtask

  // Clear sbbusyerror, keeping sbaccess `size`, and require sbcs idle with no
  // error.
  task clear_sbbusyerror(dtp_j2a_target_t t, int unsigned size, string context_s);
    dtp_sbcs_t sbcs = '0;
    sbcs.sbbusyerror = 1'b1;
    sbcs.sbaccess    = 3'(size);
    dmi_write(t, DTP_DM_SBCS, 32'(sbcs), {context_s, ".sbbusyerror_w1"});
    wait_sba_idle(t, {context_s, ".cleared"});
  endtask

  // The W mode under each AW mode: no stall on both puts the SMC fabric
  // bridge's AW and W handshakes in one cycle, and a long stall against a
  // short one puts the short channel's handshake first.
  function timing_mode_e w_mode_with_aw(timing_mode_e aw);
    case (aw)
      TIMING_SHORT: return TIMING_LONG;
      TIMING_LONG: return TIMING_SHORT;
      default: return aw;
    endcase
  endfunction

  // System clock cycles of one sbcs poll: the DMI read and the scan that
  // fetches it.
  task poll_cycles(input dtp_j2a_target_t t, output int unsigned cycles);
    bit [31:0] unused;
    bit        done;
    cycles = 0;
    fork
      begin
        dmi_read(t, DTP_DM_SBCS, {t.name, ".poll_length"}, unused);
        done = 1'b1;
      end
      begin
        while (!done) begin
          @(posedge tb_vif.clk);
          cycles++;
        end
      end
    join
  endtask

  // A seeded stream of `mode` cycle counts, long ones of LongPollsMin to
  // LongPollsMax polls.
  function ocah_axi_delays delays(timing_mode_e mode, int unsigned poll);
    int unsigned    seed = $urandom();
    ocah_axi_delays stream;
    case (mode)
      TIMING_NONE: stream = new(seed);
      TIMING_SHORT: stream = new(seed, ShortMin, ShortMax);
      TIMING_LONG: stream = new(seed, 0, 0, 100, LongPollsMin * poll, LongPollsMax * poll);
      default:
      stream = new(seed, 0, ShortMax, $urandom_range(MixedLongPercentMax, MixedLongPercentMin),
                   LongPollsMin * poll, LongPollsMax * poll);
    endcase
    return stream;
  endfunction

  // Two neighbouring beats written and the first read back, then seeded
  // lanes of that beat written at a seeded size and read back.
  task write_and_read_round(dtp_j2a_target_t t, string context_s);
    ocah_axi_checker        ev = evidence(t);
    bit              [63:0] addr = random_target_addr(t);
    bit              [63:0] rdata;
    bit              [63:0] beat;
    int unsigned            size;
    int unsigned            offset;
    bit              [63:0] size_mask;
    bit              [63:0] mask;
    bit              [63:0] lanes;
    string                  access;
    write_neighbour_then_read(t, addr, context_s, rdata, beat);
    size   = $urandom_range(t.default_size);
    offset = $urandom_range(t.beat_bytes / dtp_j2a_size_bytes(size) - 1) * dtp_j2a_size_bytes(size);
    size_mask = dtp_j2a_data_mask(size);
    mask   = size_mask << (8 * offset);
    do lanes = ({$urandom(), $urandom()} << (8 * offset)) & mask; while (lanes == (beat & mask));
    access = $sformatf("%s.lanes.size%0d.offset%0d", context_s, size, offset);
    sba_write(t, addr + offset, lanes >> (8 * offset), size, {access, ".write"});
    beat = (beat & ~mask) | lanes;
    check_target_word(t, addr, beat, t.default_size, {access, ".mem"});
    sba_read(t, addr + offset, size, {access, ".read"}, rdata);
    void'(ev.expect_equal(
        "CHK-AXI-RDATA",
        rdata & size_mask,
        lanes >> (8 * offset),
        $sformatf(
            "%s.read target=%s source=bridge_capture", access, t.name)
    ));
  endtask

endclass : dtp_jtag2axi_backpressure_test_seq
