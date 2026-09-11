// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// DEBUG_CONTROL randomized clock stop: a deterministic sweep of per-request
// one-hots, all-ones, and checker patterns crossed with every
// jtag_clock_stop / cla_clock_stop_en combination, then seeded random
// combinations — stop_clks must always equal jtag_clock_stop OR
// (any CLA request), and the read-only CLA status must track the request
// aggregate. Mirrors the cocotb
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
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-DBG-TDR", "CHK-DBG-PIN"};
    bit [NumClkStopReq-1:0] directed_reqs[$];
    int unsigned iteration = 0;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();

    directed_reqs.push_back('0);
    for (int unsigned idx = 0; idx < NumClkStopReq; idx++)
      directed_reqs.push_back(NumClkStopReq'(1) << idx);
    directed_reqs.push_back('1);
    directed_reqs.push_back(NumClkStopReq'(9'b101010101));
    directed_reqs.push_back(NumClkStopReq'(9'b010101010));

    foreach (directed_reqs[r]) begin
      for (int unsigned js = 0; js <= 1; js++) begin
        for (int unsigned ce = 0; ce <= 1; ce++) begin
          iteration++;
          `uvm_info(get_type_name(), $sformatf(
                    "Iteration %0d/%0d: directed req=0x%03h jtag_stop=%0d cla_stop_en=%0d",
                    iteration,
                    directed_reqs.size() * 4,
                    directed_reqs[r],
                    js,
                    ce
                    ), UVM_LOW)
          check_combo(bit'(js), bit'(ce), directed_reqs[r], $sformatf("directed#%0d", iteration));
        end
      end
    end

    for (int unsigned idx = 1; idx <= random_count; idx++) begin
      bit jtag_clock_stop = bit'($urandom_range(1));
      bit cla_clock_stop_en = bit'($urandom_range(1));
      bit [NumClkStopReq-1:0] clk_stop_req = NumClkStopReq'($urandom);
      `uvm_info(get_type_name(), $sformatf(
                "Iteration %0d/%0d: random req=0x%03h jtag_stop=%0d cla_stop_en=%0d",
                idx,
                random_count,
                clk_stop_req,
                jtag_clock_stop,
                cla_clock_stop_en
                ), UVM_LOW)
      check_combo(jtag_clock_stop, cla_clock_stop_en, clk_stop_req, $sformatf("random#%0d", idx));
    end

    set_clk_stop_requests('0);
    write_debug_control(pack_debug_control());
    wait_sys_cycles();
    wait_for_signal_value("stop_clks", 1'b0, .context_s("cleanup"));

    finalize_family_checker();
  endtask

endclass : dtp_dbg_ctrl_clk_stop_random_clock_stop_test_seq
