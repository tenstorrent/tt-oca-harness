// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Checks occupied mailbox state clearing and fresh FIFO traffic across cool reset.
class smc_mailbox_cool_reset_recovery_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_mailbox_cool_reset_recovery_test_seq)
  localparam string ChkPre = "CHK-MBX-RST-PRE";
  localparam string ChkAsserted = "CHK-MBX-RST-ASSERTED";
  localparam string ChkReleased = "CHK-MBX-RST-RELEASED";
  localparam string ChkEpoch = "CHK-MBX-RST-EPOCH";
  localparam string ChkDefaults = "CHK-MBX-RST-DEFAULTS";
  localparam string ChkEmpty = "CHK-MBX-RST-EMPTY";
  localparam string ChkRecovery = "CHK-MBX-RST-RECOVERY";
  localparam string ChkClean = "CHK-MBX-RST-CLEAN";
  localparam string ChkScoreboard = "CHK-MBX-RST-SCOREBOARD";
  localparam string ChkNonvac = "CHK-NONVAC";
  localparam int unsigned Registers = 6;
  localparam int unsigned Ports = 4;
  // Baseline 24; error proof/re-arm 8; load/config/readbacks 26;
  // post-reset 27; fresh FIFO traffic 8; cleanup 12 per port.
  localparam int unsigned MailboxAccesses = Registers * Ports + 8 + 26 +
      Registers * Ports + 3 + 8 + 12 * Ports;
  localparam int unsigned ResetPollCycles = 5000;
  localparam int unsigned ScoreboardPollCycles = 64;
  localparam bit [63:0] ClockGateAddr =
      smc_top_addrmap_pkg::SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR;
  localparam bit [63:0] AllIrqs = AXIL_MAILBOX_IRQS_WTIRQ_MASK |
      AXIL_MAILBOX_IRQS_RTIRQ_MASK | AXIL_MAILBOX_IRQS_EIRQ_MASK;
  localparam bit [63:0] BothFlush = AXIL_MAILBOX_CTRL_WFLUSH_MASK | AXIL_MAILBOX_CTRL_RFLUSH_MASK;
  // Exceeds the integrated depth to distinguish clamp from a simple stored value.
  localparam bit [63:0] ThresholdProbe = 64'hFF;
  smc_mailbox_reg_e surface[Registers] = '{
      MBX_STATUS, MBX_ERROR, MBX_IRQEN, MBX_WIRQT, MBX_RIRQT, MBX_IRQS};
  int unsigned mailbox_a, mailbox_b, compare_before, issued;
  bit negative;

  function new(string name = "smc_mailbox_cool_reset_recovery_test_seq");
    super.new(name);
  endfunction

  protected function void require_value(bit condition, string label);
    if (!m_check.expect_true(ChkPre, condition, label))
      `uvm_fatal(get_type_name(), {"mailbox prerequisite failed: ", label})
  endfunction

  protected function void grade(string id, string label, bit condition);
    check_evidence(id, label, 64'(condition), 64'(!negative));
  endfunction

  protected function bit [63:0] payload(int unsigned mailbox, bit inbound, bit fresh,
                                        int unsigned word_index);
    return {
      32'(random_pattern(32)), 8'(loop_index), 8'(mailbox), 4'(inbound), 4'(fresh), 8'(word_index)
    };
  endfunction

  protected task write_word(int unsigned mailbox, bit inbound, smc_mailbox_reg_e reg_kind,
                            bit [63:0] data, bit error_expected = 0);
    smc_axi_mem_write_seq op = smc_axi_mem_write_seq::type_id::create("op");
    bit valid;
    op.addr = smc_mailbox_addr(mailbox, inbound, reg_kind);
    op.data = data;
    op.check_response = 0;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    issued++;
    valid = !op.result.timed_out && !op.result.any_resp_xz() &&
        op.result.resp_list.size() == 1 &&
        op.result.worst_resp() == (error_expected ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_OKAY);
    check_evidence(ChkMemResp, "mailbox write response", 64'(valid), 1, $sformatf(
                   "mailbox=%0d inbound=%0b reg=%s", mailbox, inbound, reg_kind.name()));
  endtask

  protected task read_word(int unsigned mailbox, bit inbound, smc_mailbox_reg_e reg_kind,
                           output bit [63:0] data, input bit error_expected = 0,
                           input string response_id = ChkMemResp);
    smc_axi_mem_read_seq op = smc_axi_mem_read_seq::type_id::create("op");
    bit valid;
    op.addr = smc_mailbox_addr(mailbox, inbound, reg_kind);
    op.check_response = 0;
    op.start(p_sequencer.m_sep_in_seqr);
    mem_accesses++;
    issued++;
    data = op.data;
    valid = !op.result.timed_out && !op.result.any_resp_xz() &&
        op.result.resp_list.size() == 1 &&
        op.result.worst_resp() == (error_expected ? OCAH_AXI_RESP_SLVERR : OCAH_AXI_RESP_OKAY);
    check_evidence(response_id, "mailbox read response", 64'(valid),
                   64'(!(negative && response_id == ChkEmpty)), $sformatf(
                   "mailbox=%0d inbound=%0b reg=%s", mailbox, inbound, reg_kind.name()));
  endtask

  protected task read_surface(string check_id, bit prerequisite = 0);
    for (int unsigned port = 0; port < Ports; port++) begin
      int unsigned mailbox = port < 2 ? mailbox_a : mailbox_b;
      bit inbound = port % 2;
      foreach (surface[i]) begin
        bit [63:0] data;
        bit [63:0] expected;
        bit at_default;
        read_word(mailbox, inbound, surface[i], data);
        at_default = (data & smc_mailbox_mask(surface[i])) == smc_mailbox_default(surface[i]);
        expected = smc_mailbox_default(surface[i]);
        if (negative && check_id == ChkDefaults) expected ^= 64'h1;
        if (prerequisite)
          require_value(at_default, $sformatf(
                        "baseline mailbox=%0d inbound=%0b reg=%s data=%0h",
                        mailbox,
                        inbound,
                        surface[i].name(),
                        data
                        ));
        else
          check_evidence(check_id, surface[i].name(), data & smc_mailbox_mask(surface[i]), expected,
                         $sformatf("mailbox=%0d inbound=%0b", mailbox, inbound));
      end
    end
  endtask

  protected task sync_scoreboard();
    for (int unsigned cycle = 0; cycle < ScoreboardPollCycles; cycle++) begin
      if (scoreboard.compare_count(SmcFeatureMailboxFifo) == compare_before + issued) return;
      wait_smc_cycles(1);
    end
    `uvm_fatal(get_type_name(), "mailbox predictions/comparisons did not drain")
  endtask

  protected task wait_reset_level(bit level, string check_id);
    bit reached = 0;
    for (int unsigned cycle = 0; cycle < ResetPollCycles; cycle++) begin
      if (tb_vif.rst_primary_smc_clk_n === level && tb_vif.rst_warm_smc_clk_n === level) begin
        reached = 1;
        break;
      end
      wait_smc_cycles(1);
    end
    if (!m_check.expect_true(
            check_id,
            reached,
            $sformatf(
                "level=%0b primary=%0b warm=%0b",
                level,
                tb_vif.rst_primary_smc_clk_n,
                tb_vif.rst_warm_smc_clk_n)
        ))
      `uvm_fatal(get_type_name(), "cool reset transition exceeded bound")
  endtask

  task body();
    bit [31:0] gate;
    bit [63:0] data, fresh, epoch_before, epoch_after;
    int unsigned cool_before, mismatch_before;
    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkCsrResp, ChkMemResp, ChkPre, ChkAsserted, ChkReleased,
                    ChkEpoch, ChkDefaults, ChkEmpty, ChkRecovery, ChkClean, ChkScoreboard,
                    ChkNonvac, ChkSbMinAct});
    negative = env_cfg.mailbox_reset_sequence_negative;
    require_value(!(negative && env_cfg.mailbox_fifo_scoreboard_negative),
                  "negative controls used separately");
    require_value(loop_index < 256 && SmcMailboxDepth == 2 && ThresholdProbe >= SmcMailboxDepth,
                  "payload identity and threshold stimulus fit");
    wait_fuse_sense_done();
    compare_before = scoreboard.compare_count(SmcFeatureMailboxFifo);
    mismatch_before = scoreboard.mismatch_count(SmcFeatureMailboxFifo);
    check_min_activity(SmcFeatureMailboxFifo, MailboxAccesses);
    issued = 0;
    mailbox_a = loop_index % 4 == 0 ? 0 :
        loop_index % 4 == 1 ? SmcMailboxCount - 1 :
        int'(random_pattern(8) % SmcMailboxCount);
    mailbox_b = int'(random_pattern(8) % (SmcMailboxCount - 1));
    if (mailbox_b >= mailbox_a) mailbox_b++;
    `uvm_info(get_type_name(), $sformatf("MAILBOX-RESET seed=%0d pass=%0d A=%0d B=%0d",
                                         scenario_seed, loop_index, mailbox_a, mailbox_b), UVM_LOW)
    csr_read(ClockGateAddr, gate, "mailbox clock gate prerequisite");
    require_value((gate & SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_MAILBOX_CG_EN_MASK) == 0,
                  "mailbox clock gate disabled");
    read_surface(ChkPre, 1);

    write_word(mailbox_a, 0, MBX_WRITE_DATA, payload(mailbox_a, 0, 0, 0));
    write_word(mailbox_a, 0, MBX_WRITE_DATA, payload(mailbox_a, 0, 0, 1));
    write_word(mailbox_a, 0, MBX_WRITE_DATA, payload(mailbox_a, 0, 0, 2), 1);
    read_word(mailbox_b, 1, MBX_READ_DATA, data, 1);
    read_word(mailbox_a, 0, MBX_ERROR, data);
    require_value((data & smc_mailbox_mask(MBX_ERROR)) == AXIL_MAILBOX_ERROR_WRITE_ERROR_MASK,
                  "overflow error positive control");
    read_word(mailbox_b, 1, MBX_ERROR, data);
    require_value((data & smc_mailbox_mask(MBX_ERROR)) == AXIL_MAILBOX_ERROR_READ_ERROR_MASK,
                  "underflow error positive control");
    // ERROR reads clear flags; recreate both errors and leave them unread until reset.
    write_word(mailbox_a, 0, MBX_WRITE_DATA, payload(mailbox_a, 0, 0, 3), 1);
    read_word(mailbox_b, 1, MBX_READ_DATA, data, 1);
    write_word(mailbox_a, 1, MBX_WRITE_DATA, payload(mailbox_a, 1, 0, 0));
    write_word(mailbox_b, 0, MBX_WRITE_DATA, payload(mailbox_b, 0, 0, 0));
    write_word(mailbox_a, 0, MBX_IRQEN, smc_mailbox_mask(MBX_IRQEN));
    write_word(mailbox_b, 1, MBX_IRQEN,
               AXIL_MAILBOX_IRQEN_WTIRQ_MASK | AXIL_MAILBOX_IRQEN_EIRQ_MASK);
    write_word(mailbox_a, 0, MBX_WIRQT, ThresholdProbe);
    write_word(mailbox_a, 0, MBX_RIRQT, ThresholdProbe);
    for (int unsigned port = 0; port < Ports; port++) begin
      int unsigned mailbox = port < 2 ? mailbox_a : mailbox_b;
      bit inbound = port % 2;
      foreach (surface[i]) begin
        if (surface[i] == MBX_ERROR) continue;
        read_word(mailbox, inbound, surface[i], data);
        if (surface[i] == MBX_STATUS) begin
          bit populated = port != 2;
          require_value(((data & AXIL_MAILBOX_STATUS_EMPTY_MASK) == 0) == populated,
                        "loaded FIFO read-side empty indication");
          if (port == 0)
            require_value((data & AXIL_MAILBOX_STATUS_FULL_MASK) != 0, "A forward FIFO full");
        end
        if (surface[i] == MBX_IRQEN && (port == 0 || port == 3))
          require_value((data & smc_mailbox_mask(MBX_IRQEN)) == (port == 0 ? smc_mailbox_mask(
                        MBX_IRQEN) : AXIL_MAILBOX_IRQEN_WTIRQ_MASK | AXIL_MAILBOX_IRQEN_EIRQ_MASK),
                        "non-reset IRQEN readback");
        if (port == 0 && (surface[i] == MBX_WIRQT || surface[i] == MBX_RIRQT))
          require_value(data == SmcMailboxDepth - 1, "non-reset clamped threshold readback");
        if (port == 0 && surface[i] == MBX_IRQS)
          require_value((data & smc_mailbox_mask(MBX_IRQS)) != 0, "latched IRQ positive control");
      end
    end
    sync_scoreboard();
    cool_before = tb_vif.cool_rst_assert_count;
    epoch_before = smc_csr_reset_epoch(tb_vif.cold_rst_assert_count, cool_before);
    tb_vif.rst_cool_n <= 0;
    wait_reset_level(0, ChkAsserted);
    tb_vif.rst_cool_n <= 1;
    wait_reset_level(1, ChkReleased);
    wait_fuse_sense_done();
    epoch_after = smc_csr_reset_epoch(tb_vif.cold_rst_assert_count, tb_vif.cool_rst_assert_count);
    if (!m_check.expect_true(
            ChkEpoch,
            tb_vif.cool_rst_assert_count == cool_before + 1 &&
        epoch_before[63:32] == epoch_after[63:32] && epoch_before != epoch_after,
            "one cool reset, no cold reset"
        ))
      `uvm_fatal(get_type_name(), "unexpected reset epoch")
    read_surface(ChkDefaults);
    read_word(mailbox_a, 1, MBX_READ_DATA, data, 1, ChkEmpty);
    read_word(mailbox_a, 0, MBX_READ_DATA, data, 1, ChkEmpty);
    read_word(mailbox_b, 1, MBX_READ_DATA, data, 1, ChkEmpty);

    for (int unsigned word_index = 0; word_index < 2; word_index++)
      write_word(mailbox_a, 0, MBX_WRITE_DATA, payload(mailbox_a, 0, 1, word_index));
    for (int unsigned word_index = 0; word_index < 2; word_index++) begin
      read_word(mailbox_a, 1, MBX_READ_DATA, data);
      grade(ChkRecovery, "A forward fresh identity",
            data[31:0] == {8'(loop_index), 8'(mailbox_a), 4'(0), 4'(1), 8'(word_index)});
    end
    fresh = payload(mailbox_a, 1, 1, 0);
    write_word(mailbox_a, 1, MBX_WRITE_DATA, fresh);
    read_word(mailbox_a, 0, MBX_READ_DATA, data);
    grade(ChkRecovery, "A reverse fresh payload", data == fresh);
    fresh = payload(mailbox_b, 0, 1, 0);
    write_word(mailbox_b, 0, MBX_WRITE_DATA, fresh);
    read_word(mailbox_b, 1, MBX_READ_DATA, data);
    grade(ChkRecovery, "B forward fresh payload", data == fresh);

    for (int unsigned port = 0; port < Ports; port++) begin
      int unsigned mailbox = port < 2 ? mailbox_a : mailbox_b;
      bit inbound = port % 2;
      write_word(mailbox, inbound, MBX_CTRL, BothFlush);
      read_word(mailbox, inbound, MBX_ERROR, data);
      write_word(mailbox, inbound, MBX_IRQEN, AXIL_MAILBOX_IRQEN_REG_DEFAULT);
      write_word(mailbox, inbound, MBX_WIRQT, AXIL_MAILBOX_WIRQT_REG_DEFAULT);
      write_word(mailbox, inbound, MBX_RIRQT, AXIL_MAILBOX_RIRQT_REG_DEFAULT);
      write_word(mailbox, inbound, MBX_IRQS, AllIrqs);
    end
    read_surface(ChkClean);
    sync_scoreboard();
    check_evidence(ChkScoreboard, "new mailbox mismatches", scoreboard.mismatch_count(
                   SmcFeatureMailboxFifo) - mismatch_before, 0);
    check_evidence(ChkNonvac, "mailbox comparisons", scoreboard.compare_count(SmcFeatureMailboxFifo
                   ) - compare_before, MailboxAccesses);
    check_evidence(ChkNonvac, "sep_in_memory_accesses", mem_accesses, MailboxAccesses);
    check_evidence(ChkNonvac, "sep_in_csr_accesses", csr_accesses, 1);
    finalize_evidence();
  endtask
endclass : smc_mailbox_cool_reset_recovery_test_seq
