// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL randomized clock stop: a seeded request walk first counts
// one stop_clks change per change of the request OR, then a deterministic
// sweep of per-request one-hots, all-ones, and checker patterns crossed
// with every jtag_clock_stop / cla_clock_stop_en combination, then seeded
// random combinations — stop_clks must always equal jtag_clock_stop OR
// (any CLA request), and the read-only CLA status must track the request
// aggregate. Across the pass no stop_clks change falls off a clk_i rising
// edge (CHK-DBG-STOP-EDGE). Mirrors the cocotb
// dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq.

class dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq)

  function new(string name = "dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq");
    super.new(name);
  endfunction

  // Apply one clock-stop combination and check outputs plus readback.
  protected task check_combo(bit jtag_clock_stop, bit cla_clock_stop_en,
                             bit [NumClkStopReq-1:0] clk_stop_req, string context_s);
    bit [63:0] control_value, readback;
    bit expected_cla  = |clk_stop_req;
    bit expected_stop = jtag_clock_stop | expected_cla;
    control_value = pack_debug_control(.cla_clock_stop_en(cla_clock_stop_en), .jtag_clock_stop(
                                       jtag_clock_stop));
    `uvm_info(get_type_name(),
              $sformatf("%s apply jtag_stop=%0d cla_stop_en=%0d clk_stop_req=0x%03h control=0x%02h",
                        context_s, jtag_clock_stop, cla_clock_stop_en, clk_stop_req, control_value),
              UVM_MEDIUM)
    set_clk_stop_requests(clk_stop_req);
    write_debug_control(control_value);
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", expected_stop, .context_s(context_s));
    expect_dbg_signal("cla_clock_stop_en", cla_clock_stop_en, context_s);
    read_debug_control(readback, control_value);
    check_debug_control_bit(readback, DbgClaClockStopBit, expected_cla,
                            "DEBUG_CONTROL.cla_clock_stop", context_s);
    check_debug_control_bit(readback, DbgJtagClockStopBit, jtag_clock_stop,
                            "DEBUG_CONTROL.jtag_clock_stop", context_s);
    check_debug_control_bit(readback, DbgClaClockStopEnBit, cla_clock_stop_en,
                            "DEBUG_CONTROL.cla_clock_stop_en", context_s);
  endtask

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN", "CHK-DBG-STOP-EDGE"};
    bit [NumClkStopReq-1:0] directed_reqs[$];
    bit [NumClkStopReq-1:0] even_reqs = '0;
    int unsigned iteration = 0;
    int unsigned off_edge_start;
    seed_scenario_rng();
    attach_family_checker(required);
    off_edge_start = stop_clks_off_edge_count();

    log_step("1", "Reset TAP");
    reset_to_tlr();
    log_step("2", "Walk seeded request vectors with DEBUG_CONTROL cleared");
    check_stop_clks_walk();

    directed_reqs.push_back('0);
    for (int unsigned idx = 0; idx < NumClkStopReq; idx++) begin
      directed_reqs.push_back(NumClkStopReq'(1) << idx);
      even_reqs[idx] = (idx % 2 == 0);
    end
    directed_reqs.push_back('1);
    directed_reqs.push_back(even_reqs);
    directed_reqs.push_back(~even_reqs);

    log_step("3", "Run deterministic per-request and all-control sweep");
    foreach (directed_reqs[r]) begin
      for (int unsigned js = 0; js <= 1; js++) begin
        for (int unsigned ce = 0; ce <= 1; ce++) begin
          iteration++;
          log_iteration(
              iteration, directed_reqs.size() * 4, $sformatf(
              "directed req=0x%03h jtag_stop=%0d cla_stop_en=%0d", directed_reqs[r], js, ce));
          check_combo(bit'(js), bit'(ce), directed_reqs[r], $sformatf("directed#%0d", iteration));
        end
      end
    end

    log_step("4", "Run seeded random clock-stop combinations");
    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      bit jtag_clock_stop = bit'($urandom_range(1));
      bit cla_clock_stop_en = bit'($urandom_range(1));
      bit [NumClkStopReq-1:0] clk_stop_req = NumClkStopReq'($urandom);
      log_iteration(idx, random_count, $sformatf(
                    "random req=0x%03h jtag_stop=%0d cla_stop_en=%0d",
                    clk_stop_req,
                    jtag_clock_stop,
                    cla_clock_stop_en
                    ));
      check_combo(jtag_clock_stop, cla_clock_stop_en, clk_stop_req, $sformatf("random#%0d", idx));
    end

    log_step("5", "Cleanup clock-stop request and DEBUG_CONTROL");
    set_clk_stop_requests('0);
    write_debug_control(pack_debug_control());
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b0, .context_s("cleanup"));
    check_stop_clks_off_edge(off_edge_start, "whole pass");

    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq
