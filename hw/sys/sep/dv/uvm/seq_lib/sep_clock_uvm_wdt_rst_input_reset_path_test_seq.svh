// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SEP watchdog reset-input scenario sequence, carrying the cocotb
// sep_clock_uvm_wdt_rst_input_reset_path_test semantics through sep_tb_if
// (no bus traffic). The TB drives the real wdt_rst_ni_i DUT input
// (tb_vif.wdt_rst_n) and samples the CPU-reset net (tb_vif.sep_cpu_reset_n,
// the sep_cpu_reset_n_o tb_top probe) and the main SEP reset output
// (tb_vif.sep_reset_n, dbg_sep_reset_n_o). Every check compares with ===
// against a known level, so an X or Z reset net fails both expectations.
//   * wait for fuse sense done (cocotb bring_up_no_cpu parity);
//   * CHK-BASELINE: with wdt_rst_ni_i released, both resets read 1;
//   * CHK-ASSERT: wdt_rst_ni_i low drives sep_cpu_reset_n to 0;
//   * CHK-ISOLATION: from the wdt_rst_ni_i assert edge through the release
//     settle, sep_reset_n reads 1 and a watcher sees no value change on it, so
//     a drop of any length in that window fails; then rst_ni low
//     must drive sep_reset_n to 0, the control that proves the observable
//     can read 0 (a stuck-high net satisfies the "stays 1" read alone);
//   * CHK-RELEASE: wdt_rst_ni_i high returns sep_cpu_reset_n to 1.
// The wdt_rst_ni_i hold after the CHK-ASSERT window is a seeded random
// number of extra system clocks, so each pass releases at a different time.
// rst_ni is released at the end of the pass; the next pass waits for fuse
// sense done again and its CHK-BASELINE proves both resets recovered.

class sep_clock_uvm_wdt_rst_input_reset_path_test_seq extends sep_base_test_seq;
  `uvm_object_utils(sep_clock_uvm_wdt_rst_input_reset_path_test_seq)

  localparam string ChkBaseline = "CHK-BASELINE";
  localparam string ChkAssert = "CHK-ASSERT";
  localparam string ChkIsolation = "CHK-ISOLATION";
  localparam string ChkRelease = "CHK-RELEASE";

  // System clocks for the reset path to settle after an input edge (cocotb
  // _SETTLE).
  localparam int unsigned SettleCycles = 5;
  // Width of the seeded extra wdt_rst_ni_i hold, in system clocks.
  localparam int unsigned ExtraHoldBits = 4;

  function new(string name = "sep_clock_uvm_wdt_rst_input_reset_path_test_seq");
    super.new(name);
  endfunction

  // Record that a reset observable reads exactly the expected level.
  function void check_level(string check_id, string name, logic observed, bit expected);
    void'(m_check.expect_true(
        check_id,
        observed === expected,
        $sformatf(
            "%s expected=%0b observed=%b", name, expected, observed)
    ));
  endfunction

  task body();
    int unsigned extra_hold;
    int unsigned iso_changes;
    process iso_proc;

    seed_scenario_rng();
    attach_evidence('{ChkFuseSense, ChkBaseline, ChkAssert, ChkIsolation, ChkRelease});
    extra_hold = int'(random_pattern(ExtraHoldBits));
    `uvm_info(get_type_name(),
              $sformatf({"SEP SV-UVM WDT reset input: wdt_rst_ni_i -> sep_cpu_reset_n only; ",
                         "scenario_seed=%0d extra_hold=%0d"}, scenario_seed, extra_hold), UVM_LOW)

    wait_fuse_sense_done();

    log_step("A", "baseline: wdt_rst_ni_i released");
    check_level(ChkBaseline, "wdt_rst_ni=1 -> sep_cpu_reset_n", tb_vif.sep_cpu_reset_n, 1'b1);
    check_level(ChkBaseline, "wdt_rst_ni=1 -> sep_reset_n", tb_vif.sep_reset_n, 1'b1);

    log_step("B", "assert wdt_rst_ni_i");
    // Count every sep_reset_n value change from here to the release settle.
    iso_changes = 0;
    fork
      begin
        iso_proc = process::self();
        forever begin
          @(tb_vif.sep_reset_n);
          iso_changes++;
        end
      end
    join_none
    wait (iso_proc != null);
    tb_vif.wdt_rst_n <= 1'b0;
    wait_sys_cycles(SettleCycles);
    check_level(ChkAssert, "wdt_rst_ni=0 -> sep_cpu_reset_n", tb_vif.sep_cpu_reset_n, 1'b0);
    check_level(ChkIsolation, "wdt_rst_ni=0 -> sep_reset_n", tb_vif.sep_reset_n, 1'b1);
    wait_sys_cycles(extra_hold);
    check_level(ChkAssert, $sformatf("wdt_rst_ni=0 held +%0d -> sep_cpu_reset_n", extra_hold),
                tb_vif.sep_cpu_reset_n, 1'b0);

    log_step("C", "release wdt_rst_ni_i");
    tb_vif.wdt_rst_n <= 1'b1;
    wait_sys_cycles(SettleCycles);
    check_level(ChkRelease, "wdt_rst_ni=1 -> sep_cpu_reset_n", tb_vif.sep_cpu_reset_n, 1'b1);
    iso_proc.kill();
    void'(m_check.expect_true(
        ChkIsolation,
        iso_changes == 0 && tb_vif.sep_reset_n === 1'b1,
        $sformatf(
            "wdt_rst_ni assert/release window -> sep_reset_n held 1: value_changes=%0d end=%b",
            iso_changes, tb_vif.sep_reset_n)
    ));

    log_step("D", "isolation observable control: assert rst_ni");
    tb_vif.rst_n <= 1'b0;
    wait_sys_cycles(SettleCycles);
    check_level(ChkIsolation, "rst_ni=0 -> sep_reset_n", tb_vif.sep_reset_n, 1'b0);
    tb_vif.rst_n <= 1'b1;
    wait_sys_cycles(SettleCycles);

    finalize_evidence();
  endtask

endclass : sep_clock_uvm_wdt_rst_input_reset_path_test_seq
