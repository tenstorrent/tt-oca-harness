// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Grades documented narrow reads and null-write side effects through SEP_IN.
class smc_narrow_access_side_effect_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_narrow_access_side_effect_test_seq)
  localparam string ChkAcquire = "CHK-NARROW-MUTEX-ACQUIRE";
  localparam string ChkRelease = "CHK-NARROW-MUTEX-RELEASE";
  localparam string ChkPoll = "CHK-NARROW-ZEROER-POLL";
  localparam string ChkPop = "CHK-NARROW-MBX-POP";
  localparam string ChkPush = "CHK-NARROW-MBX-PUSH";
  localparam string ChkZeroFill = "CHK-NARROW-MBX-ZERO-FILL";
  localparam string ChkEmpty = "CHK-NARROW-MBX-EMPTY";
  localparam string ChkError = "CHK-NARROW-MBX-ERROR";
  localparam string ChkNullZeroer = "CHK-NARROW-NULL-ZEROER";
  localparam string ChkNullMailbox = "CHK-NARROW-NULL-MAILBOX";
  localparam string ChkControl = "CHK-NARROW-ZEROER-CONTROL";
  localparam string ChkErrorControl = "CHK-NARROW-MBX-ERROR-CONTROL";
  localparam string ChkCleanup = "CHK-NARROW-CLEANUP";
  localparam string ChkRestore = "CHK-NARROW-RESTORE";
  localparam string ChkSetup = "CHK-NARROW-SETUP";
  localparam string ChkScoreboard = "CHK-NARROW-SCOREBOARD";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned WindowBytes = 64;
  localparam int unsigned WindowWords = WindowBytes / SmcMemBytes;
  localparam int unsigned GuardWords = 1;
  localparam int unsigned TotalBytes = WindowBytes + 2 * SmcMemBytes;
  localparam int unsigned PollReads = 8;
  localparam int unsigned PageBytes = 4096;
  localparam int unsigned CleanupPollBound = 4096;
  localparam int unsigned ComparisonBound = 64;
  localparam int unsigned ComparisonsPerPass = 3;
  // Reads: 4 baseline, 3 MUTEX, 8 upper polls, 4 SIZE/DEST readbacks,
  // 5 pop/push, 2 empty, 4 ERROR, 5 EIRQ, 3 STATUS and one per reverse entry.
  localparam int unsigned FixedReads = 38 + SmcMailboxDepth;
  // Writes: 3 MUTEX, 4 SIZE/DEST poison, 4 SIZE/DEST cleanup, 5 pushes,
  // 3 EIRQ, 2 null-strobe, 2 full-FIFO attempts and one per reverse entry.
  localparam int unsigned FixedWrites = 23 + SmcMailboxDepth;
  // Base of the SYS_OUT-backed memory pages reserved for this scenario.
  localparam bit [63:0] OutputBase = 64'h0200_0000;
  localparam bit [7:0] Poison = 8'hD3;
  // axil_mailbox.rdl READ_DATA and interface.adoc specify the full empty-read payload.
  localparam bit [63:0] EmptyReadData = 64'h0000_0000_FEED_DEAD;
  localparam bit [63:0] FilterStart =
      smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR(
      0
  );
  localparam bit [63:0] FilterEnd =
      smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR(
      0
  );
  localparam bit [63:0] FilterConfig =
      smc_top_addrmap_pkg::SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR(
      0
  );
  localparam bit [63:0] PassAll = FILTER_CTRL_FILTER_CONFIG_READ_ALLOWED_MASK |
      FILTER_CTRL_FILTER_CONFIG_WRITE_ALLOWED_MASK | FILTER_CTRL_FILTER_CONFIG_ENTRY_ENABLED_MASK |
      FILTER_CTRL_FILTER_CONFIG_ALLOW_BURST_MASK;
  localparam bit [63:0] ConfigMask = PassAll | FILTER_CTRL_FILTER_CONFIG_ALLOW_NS_MASK |
      FILTER_CTRL_FILTER_CONFIG_DATA_BUS_WIDTH_MASK | FILTER_CTRL_FILTER_CONFIG_SRC_ID_MASK |
      FILTER_CTRL_FILTER_CONFIG_GROUP_ID_MASK | FILTER_CTRL_FILTER_CONFIG_LOCKED_MASK;
  bit negative;
  int unsigned mailbox, mutex_index;
  bit [63:0] destination;

  protected function string access_context(string detail = "");
    return
        $sformatf("mailbox=%0d mutex=%0d dest=0x%0h %s", mailbox, mutex_index, destination, detail);
  endfunction

  function new(string name = "smc_narrow_access_side_effect_test_seq");
    super.new(name);
  endfunction

  protected task prerequisite(string id, bit actual, string label, string detail = "");
    check_evidence(id, label, 64'(actual), 1, access_context(detail));
    if (!actual) begin
      `uvm_fatal(get_type_name(), {label, " ", detail})
    end
  endtask

  protected task grade(string id, string label, bit actual, string detail = "");
    check_evidence(id, label, 64'(actual), 64'(!negative), access_context(detail));
  endtask

  protected task poison_window();
    bit [7:0] bytes_to_write[$];
    repeat (TotalBytes) bytes_to_write.push_back(Poison);
    p_sequencer.m_sys_out_slave_seq.write_bytes(destination - SmcMemBytes, bytes_to_write);
    mem_write(SmcZeroerDestAddr, destination, "Zeroer destination");
    mem_write(SmcZeroerSizeAddr, WindowBytes, "Zeroer size");
  endtask

  protected task inspect_window(output bit unchanged, output int unsigned zero_words,
                                output bit guards_intact);
    bit [7:0] bytes_read[$];
    p_sequencer.m_sys_out_slave_seq.read_bytes(destination - SmcMemBytes, TotalBytes, bytes_read);
    prerequisite(ChkSetup, bytes_read.size() == TotalBytes, "responder window shape");
    unchanged = 1;
    guards_intact = 1;
    zero_words = 0;
    for (int unsigned word_index = 0; word_index < TotalBytes / SmcMemBytes; word_index++) begin
      bit all_zero = 1;
      for (int unsigned lane = 0; lane < SmcMemBytes; lane++) begin
        bit [7:0] value = bytes_read[word_index*SmcMemBytes+lane];
        unchanged &= value == Poison;
        all_zero &= value == 0;
        if (word_index == 0 || word_index == WindowWords + GuardWords)
          guards_intact &= value == Poison;
      end
      if (word_index >= GuardWords && word_index < WindowWords + GuardWords && all_zero)
        zero_words++;
    end
  endtask

  protected task wait_zeroer_idle(string check_id, output int unsigned polls);
    bit [63:0] status;
    polls = 0;
    for (int unsigned i = 0; i < CleanupPollBound; i++) begin
      mem_read(SmcZeroerCtrlStatusAddr, status, "Zeroer completion");
      polls++;
      if ((status & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK) == 0) return;
      wait_smc_cycles(1);
    end
    prerequisite(check_id, 1'b0, "Zeroer completion within poll bound", $sformatf(
                 "status=%h polls=%0d bound=%0d", status, polls, CleanupPollBound));
  endtask

  protected task clear_command(string check_id = ChkCleanup);
    bit [63:0] size_value, destination;
    mem_write(SmcZeroerSizeAddr, ZEROER_CTRL_SIZE_REG_DEFAULT, "Zeroer size cleanup");
    mem_write(SmcZeroerDestAddr, ZEROER_CTRL_DEST_ADDR_REG_DEFAULT, "Zeroer destination cleanup");
    mem_read(SmcZeroerSizeAddr, size_value, "Zeroer size restored");
    mem_read(SmcZeroerDestAddr, destination, "Zeroer destination restored");
    prerequisite(check_id,
                 size_value == ZEROER_CTRL_SIZE_REG_DEFAULT &&
                 destination == ZEROER_CTRL_DEST_ADDR_REG_DEFAULT,
                 "Zeroer command cleared", $sformatf(
                 "size=%h destination=%h", size_value, destination));
  endtask

  protected task filter_readback(bit [63:0] address, bit [63:0] expected, string check_id,
                                 string label);
    bit [63:0] observed;
    bit [63:0] mask;
    if (address == FilterConfig) mask = ConfigMask;
    else if (address == FilterStart) mask = FILTER_CTRL_START_ADDR_START_ADDR_MASK;
    else mask = FILTER_CTRL_END_ADDR_END_ADDR_MASK;
    mem_read(address, observed, label);
    check_evidence(check_id, label, observed & mask, expected & mask, access_context());
    if (check_id == ChkSetup && (observed & mask) != (expected & mask)) begin
      `uvm_fatal(get_type_name(), "Programmed filter readback does not match stimulus")
    end
  endtask

  protected task strobed_write(bit [63:0] address, bit [63:0] data, bit [7:0] strb, string label,
                               bit error_expected = 0);
    smc_axi_mem_write_seq op = smc_axi_mem_write_seq::type_id::create("strobed_write");
    op.addr = address;
    op.data = data;
    op.strb = strb;
    op.check_response = !error_expected;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    `uvm_info(get_type_name(), $sformatf("SEP_IN %s addr=0x%0h data=%h strb=%h resp=%s %s", label,
                                         address, data, strb, op.result.worst_resp().name(),
                                         access_context()), UVM_LOW)
    if (error_expected) begin
      prerequisite(ChkErrorControl,
                   !op.result.timed_out && op.result.resp_list.size() == 1 &&
                   !op.result.any_resp_xz() && op.result.worst_resp() == OCAH_AXI_RESP_SLVERR,
                   label, $sformatf(
                   "addr=0x%0h timeout=%b responses=%p",
                   address,
                   op.result.timed_out,
                   op.result.resp_list
                   ));
    end else begin
      check_response(ChkMemResp, op.result, label);
    end
  endtask

  protected task null_write(bit [63:0] address);
    strobed_write(address, '1, '0, "null-strobe write");
  endtask

  protected task empty_read(bit [63:0] address, int unsigned ordinal);
    smc_axi_mem_read_seq op = smc_axi_mem_read_seq::type_id::create("empty_read");
    op.addr = address;
    op.check_response = 0;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    `uvm_info(get_type_name(), $sformatf("SEP_IN empty read addr=0x%0h data=%h ordinal=%0d %s",
                                         address, op.data, ordinal, access_context()), UVM_LOW)
    grade(ChkEmpty, "empty mailbox response and 64-bit payload",
          !op.result.timed_out && op.result.resp_list.size() == 1 && !op.result.any_resp_xz() &&
          op.result.worst_resp() == OCAH_AXI_RESP_SLVERR && op.data == EmptyReadData,
          $sformatf("ordinal=%0d data=%h resp=%s", ordinal, op.data, op.result.worst_resp().name()
          ));
  endtask

  task body();
    int unsigned read_before, write_before, compare_before, mismatch_before;
    int unsigned polls, control_polls, zero_words, entries;
    bit [63:0] page, status, errors, observed, word0, word1, upper_push;
    bit [63:0] saved_start, saved_end, saved_config, programmed_config;
    bit [63:0] queue_data[$];
    bit [31:0] upper, lower, value, value_lo, value_zf, pattern;
    bit unchanged, guards_intact, poll_idle, null_entry_ok;
    logic [31:0] busy_before, busy_after;
    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkMemResp, ChkAcquire, ChkRelease, ChkPoll, ChkPop,
                    ChkPush, ChkZeroFill, ChkEmpty, ChkError, ChkNullZeroer, ChkNullMailbox,
                    ChkControl, ChkErrorControl, ChkCleanup, ChkRestore, ChkSetup, ChkScoreboard,
                    ChkNonvac, ChkSbMinAct});
    negative = env_cfg.narrow_side_effect_sequence_negative;
    if (negative)
      `uvm_info(get_type_name(), "NEGATIVE VALIDATION: narrow side-effect expectations", UVM_LOW)
    check_min_activity(SmcFeatureMutexSema, ComparisonsPerPass);
    wait_fuse_sense_done();
    if (sep_in_history == null) begin
      `uvm_fatal(get_type_name(), "SEP_IN completed-transaction history is not connected")
    end
    mailbox = loop_index % SmcMailboxCount;
    mutex_index = loop_index % SmcMutexCount;
    page = OutputBase + 64'(loop_index) * PageBytes;
    destination = page + SmcMemBytes +
        64'(random_pattern(32) % ((PageBytes - TotalBytes) / SmcMemBytes)) * SmcMemBytes;
    prerequisite(ChkSetup, page + PageBytes <= env_cfg.sys_out_mem_bytes,
                 "Zeroer window inside responder");
    mem_read(SmcZeroerCtrlStatusAddr, status, "Zeroer entry status");
    prerequisite(ChkSetup, (status & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK) == 0, "Zeroer idle");
    mem_read(FilterStart, saved_start, "filter saved START");
    mem_read(FilterEnd, saved_end, "filter saved END");
    mem_read(FilterConfig, saved_config, "filter saved CONFIG");
    prerequisite(ChkSetup, (saved_config & FILTER_CTRL_FILTER_CONFIG_LOCKED_MASK) == 0,
                 "filter entry unlocked");
    programmed_config = (saved_config & FILTER_CTRL_FILTER_CONFIG_DATA_BUS_WIDTH_MASK) | PassAll;
    mem_write(FilterConfig, 0, "filter disable for programming");
    mem_write(FilterStart, page, "filter page START");
    mem_write(FilterEnd, page + PageBytes - 1, "filter page END");
    mem_write(FilterConfig, PassAll, "filter page CONFIG");
    filter_readback(FilterStart, page, ChkSetup, "filter programmed START");
    filter_readback(FilterEnd, page + PageBytes - 1, ChkSetup, "filter programmed END");
    filter_readback(FilterConfig, programmed_config, ChkSetup, "filter programmed CONFIG");
    if (saved_start == page || saved_end == page + PageBytes - 1 ||
        saved_config == programmed_config)
      `uvm_info(get_type_name(), $sformatf(
                "NARROW-RESTORE restore_nondiscriminating start=%b end=%b config=%b",
                saved_start == page,
                saved_end == page + PageBytes - 1,
                saved_config == programmed_config
                ), UVM_LOW)
    poison_window();
    busy_before = tb_vif.zeroer_busy_sample_count;
    mem_write(SmcZeroerCtrlStatusAddr, 0, "Zeroer path control");
    wait_zeroer_idle(ChkControl, control_polls);
    busy_after = tb_vif.zeroer_busy_sample_count;
    prerequisite(ChkControl, !$isunknown({busy_before, busy_after}) && busy_after > busy_before,
                 "valid START advances busy samples", $sformatf(
                 "busy_samples=%0d->%0d", busy_before, busy_after));
    inspect_window(unchanged, zero_words, guards_intact);
    prerequisite(ChkControl, zero_words == WindowWords && guards_intact,
                 "valid START reaches SYS_OUT with intact guards", $sformatf(
                 "zero_words=%0d guards=%b polls=%0d", zero_words, guards_intact, control_polls));
    clear_command(ChkSetup);

    pattern = random_pattern(32);
    word0 = {pattern, pattern ^ 32'h0101_0101};
    word1 = {pattern ^ 32'h0202_0202, pattern ^ 32'h0404_0404};
    value = 32'(random_pattern(32)) | 1;
    value_lo = 32'(random_pattern(32)) | 1;
    value_zf = 32'(random_pattern(32)) | 1;
    read_before = sep_in_history.count(1);
    write_before = sep_in_history.count(0);
    compare_before = scoreboard.compare_count(SmcFeatureMutexSema);
    mismatch_before = scoreboard.mismatch_count(SmcFeatureMutexSema);
    mem_read(SmcZeroerCtrlStatusAddr, status, "Zeroer baseline");
    prerequisite(ChkSetup, (status & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK) == 0, "Zeroer idle");
    mem_read(smc_mailbox_addr(mailbox, 0, MBX_STATUS), status, "outbound empty");
    prerequisite(ChkSetup, (status & AXIL_MAILBOX_STATUS_EMPTY_MASK) != 0, "outbound empty");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_STATUS), status, "inbound empty");
    prerequisite(ChkSetup, (status & AXIL_MAILBOX_STATUS_EMPTY_MASK) != 0, "inbound empty");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_ERROR), errors, "mailbox clean errors");
    prerequisite(ChkSetup, errors == 0, "mailbox error baseline clear");

    // MUTEX reads acquire, so release cannot be verified by a passive readback.
    csr_write(smc_mutex_addr(mutex_index), 0, "mutex initial release");
    csr_read(smc_mutex_addr(mutex_index), lower, "mutex free control");
    grade(ChkRelease, "release admits next acquire", (lower & SmcMutexMask) == SmcMutexFree,
          $sformatf("lower=%h", lower));
    csr_write(smc_mutex_addr(mutex_index), 0, "mutex release before upper read");
    csr_read(smc_mutex_addr(mutex_index) + SmcCsrBytes, upper, "mutex upper acquire");
    csr_read(smc_mutex_addr(mutex_index), lower, "mutex acquired readback");
    grade(ChkAcquire, "upper read returns zero and acquires",
          upper == 0 && (lower & SmcMutexMask) == SmcMutexTaken, $sformatf(
          "upper=%h lower=%h", upper, lower));
    csr_write(smc_mutex_addr(mutex_index), 0, "mutex cleanup");

    poison_window();
    busy_before = tb_vif.zeroer_busy_sample_count;
    poll_idle = 1;
    repeat (PollReads) begin
      csr_read(SmcZeroerCtrlStatusAddr + SmcCsrBytes, upper, "Zeroer upper poll");
      poll_idle &= (smc_csr_to_bus(
          SmcZeroerCtrlStatusAddr + SmcCsrBytes, upper
      ) & ZEROER_CTRL_CTRL_STATUS_STATUS_MASK) == 0;
    end
    inspect_window(unchanged, zero_words, guards_intact);
    // Keep sampling through the SIZE/DEST cleanup writes and readbacks so the
    // last upper read is not graded in its response cycle.
    clear_command();
    busy_after = tb_vif.zeroer_busy_sample_count;
    grade(ChkPoll, "upper polls leave window poisoned and Zeroer never busy",
          poll_idle && unchanged && !$isunknown({busy_before, busy_after}
          ) && busy_after === busy_before, $sformatf(
          "idle=%b unchanged=%b guards=%b busy_samples=%0d->%0d",
          poll_idle,
          unchanged,
          guards_intact,
          busy_before,
          busy_after
          ));

    mem_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA), word0, "mailbox word 0");
    mem_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA), word1, "mailbox word 1");
    csr_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA) + SmcCsrBytes, upper, "upper pop");
    csr_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), lower, "lower pop");
    grade(ChkPop, "narrow reads consume separate whole entries",
          {upper, lower} == {word0[63:32], word1[31:0]}, $sformatf(
          "actual=%h expected=%h", {upper, lower}, {word0[63:32], word1[31:0]}));
    csr_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA) + SmcCsrBytes, value, "upper push");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), observed, "upper push readback");
    upper_push = observed;
    csr_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA), value_lo, "lower push");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), observed, "lower push readback");
    grade(ChkPush, "32-bit pushes place data in the addressed half",
          upper_push == {value, 32'h0} && observed == {32'h0, value_lo}, $sformatf(
          "upper_push=%h lower_push=%h upper_value=%h lower_value=%h",
          upper_push,
          observed,
          value,
          value_lo
          ));
    strobed_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA), {value_zf, 32'hFFFF_FFFF}, 8'hF0,
                  "partial-strobe push");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), observed, "partial-strobe push readback");
    grade(ChkZeroFill, "unstrobed lanes of a partial-strobe push are zero",
          observed == {value_zf, 32'h0}, $sformatf("actual=%h value=%h", observed, value_zf));
    empty_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), 1);
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_ERROR), errors, "read-error control");
    prerequisite(ChkErrorControl, (errors & AXIL_MAILBOX_ERROR_READ_ERROR_MASK) != 0,
                 "read-error flag is live", $sformatf("errors=%h", errors));
    for (int unsigned i = 0; i < SmcMailboxDepth; i++) begin
      mem_write(smc_mailbox_addr(mailbox, 1, MBX_WRITE_DATA), word0 ^ 64'(i), "reverse FIFO fill");
    end
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_STATUS), status, "reverse FIFO full");
    prerequisite(ChkErrorControl, (status & AXIL_MAILBOX_STATUS_FULL_MASK) != 0,
                 "reverse FIFO is full", $sformatf("status=%h depth=%0d", status, SmcMailboxDepth));
    strobed_write(smc_mailbox_addr(mailbox, 1, MBX_WRITE_DATA), ~word0, '1,
                  "full FIFO write-error control", 1);
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_ERROR), errors, "write-error control");
    prerequisite(ChkErrorControl, (errors & AXIL_MAILBOX_ERROR_WRITE_ERROR_MASK) != 0,
                 "write-error flag is live", $sformatf("errors=%h", errors));
    mem_write(smc_mailbox_addr(mailbox, 1, MBX_IRQS), AXIL_MAILBOX_IRQS_EIRQ_MASK,
              "EIRQ clear before repeated full write");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_IRQS), observed,
             "EIRQ cleared before repeated full write");
    prerequisite(ChkErrorControl, (observed & AXIL_MAILBOX_IRQS_EIRQ_MASK) == 0,
                 "EIRQ clear before repeated full write is effective", $sformatf("IRQS=%h", observed
                 ));
    // Reading ERROR clears its flags, so recreate write_error before the upper read.
    strobed_write(smc_mailbox_addr(mailbox, 1, MBX_WRITE_DATA), ~word1, '1,
                  "full FIFO write-error recreation", 1);
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_IRQS), observed, "repeated full write error");
    prerequisite(ChkErrorControl, (observed & AXIL_MAILBOX_IRQS_EIRQ_MASK) != 0,
                 "repeated full write registers an error", $sformatf("IRQS=%h", observed));
    mem_write(smc_mailbox_addr(mailbox, 1, MBX_IRQS), AXIL_MAILBOX_IRQS_EIRQ_MASK,
              "EIRQ clear before second empty read");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_IRQS), observed,
             "EIRQ cleared before second empty read");
    prerequisite(ChkErrorControl, (observed & AXIL_MAILBOX_IRQS_EIRQ_MASK) == 0,
                 "EIRQ clear before second empty read is effective", $sformatf("IRQS=%h", observed
                 ));
    empty_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), 2);
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_IRQS), observed, "second empty read error");
    prerequisite(ChkErrorControl, (observed & AXIL_MAILBOX_IRQS_EIRQ_MASK) != 0,
                 "second empty read registers an error", $sformatf("IRQS=%h", observed));
    csr_read(smc_mailbox_addr(mailbox, 1, MBX_ERROR) + SmcCsrBytes, upper, "upper error clear");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_ERROR), errors, "errors after upper read");
    grade(ChkError, "upper read clears both error flags", upper == 0 && errors == 0, $sformatf(
          "upper=%h errors=%h", upper, errors));
    for (int unsigned i = 0; i < SmcMailboxDepth; i++) begin
      mem_read(smc_mailbox_addr(mailbox, 0, MBX_READ_DATA), observed, "reverse FIFO drain");
      prerequisite(ChkCleanup, observed == (word0 ^ 64'(i)),
                   "full writes preserve queued reverse data", $sformatf(
                   "index=%0d expected=%h observed=%h", i, word0 ^ 64'(i), observed));
    end
    mem_read(smc_mailbox_addr(mailbox, 0, MBX_STATUS), status, "reverse FIFO drained");
    prerequisite(ChkCleanup, (status & AXIL_MAILBOX_STATUS_EMPTY_MASK) != 0,
                 "reverse FIFO is empty", $sformatf("status=%h", status));
    mem_write(smc_mailbox_addr(mailbox, 1, MBX_IRQS), AXIL_MAILBOX_IRQS_EIRQ_MASK, "EIRQ clear");
    mem_read(smc_mailbox_addr(mailbox, 1, MBX_IRQS), observed, "EIRQ cleared");
    prerequisite(ChkCleanup, (observed & AXIL_MAILBOX_IRQS_EIRQ_MASK) == 0, "EIRQ cleanup",
                 $sformatf("IRQS=%h", observed));

    poison_window();
    null_write(SmcZeroerCtrlStatusAddr);
    wait_zeroer_idle(ChkNullZeroer, polls);
    inspect_window(unchanged, zero_words, guards_intact);
    grade(ChkNullZeroer, "null START zeros exactly the window",
          zero_words == WindowWords && guards_intact, $sformatf(
          "zero_words=%0d guards=%b polls=%0d", zero_words, guards_intact, polls));
    null_write(smc_mailbox_addr(mailbox, 0, MBX_WRITE_DATA));
    entries = 0;
    forever begin
      mem_read(smc_mailbox_addr(mailbox, 1, MBX_STATUS), status, "null-push status");
      if ((status & AXIL_MAILBOX_STATUS_EMPTY_MASK) != 0) break;
      if (entries == SmcMailboxDepth) begin
        prerequisite(ChkCleanup, 1'b0, "null-push drain within mailbox depth", $sformatf(
                     "entries=%0d status=%h data=%p", entries, status, queue_data));
      end
      mem_read(smc_mailbox_addr(mailbox, 1, MBX_READ_DATA), observed, "null-push data");
      queue_data.push_back(observed);
      entries++;
    end
    null_entry_ok = 0;
    if (entries == 1) null_entry_ok = queue_data[0] == 0;
    grade(ChkNullMailbox, "null write pushes exactly one zero entry", null_entry_ok, $sformatf(
          "entries=%0d data=%p", entries, queue_data));
    clear_command();

    for (int unsigned cycle = 0; cycle < ComparisonBound; cycle++) begin
      if (scoreboard.compare_count(
              SmcFeatureMutexSema
          ) >= compare_before + ComparisonsPerPass && sep_in_history.count(
              1
          ) >= read_before + FixedReads + polls + 2 * entries && sep_in_history.count(
              0
          ) >= write_before + FixedWrites)
        break;
      wait_smc_cycles(1);
    end
    check_evidence(ChkScoreboard, "new mutex mismatches", scoreboard.mismatch_count(
                   SmcFeatureMutexSema) - mismatch_before, 0);
    check_evidence(ChkNonvac, "SEP_IN reads", sep_in_history.count(1) - read_before,
                   FixedReads + polls + 2 * entries);
    check_evidence(ChkNonvac, "SEP_IN writes", sep_in_history.count(0) - write_before, FixedWrites);
    check_evidence(ChkNonvac, "mutex comparisons", scoreboard.compare_count(SmcFeatureMutexSema
                   ) - compare_before, ComparisonsPerPass);
    mem_write(FilterConfig, 0, "filter disable before restore");
    mem_write(FilterStart, saved_start, "filter START restore");
    mem_write(FilterEnd, saved_end, "filter END restore");
    mem_write(FilterConfig, saved_config, "filter CONFIG restore");
    filter_readback(FilterStart, saved_start, ChkRestore, "filter START restored");
    filter_readback(FilterEnd, saved_end, ChkRestore, "filter END restored");
    filter_readback(FilterConfig, saved_config, ChkRestore, "filter CONFIG restored");
    finalize_evidence();
  endtask
endclass : smc_narrow_access_side_effect_test_seq
