// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// Provides keyed watchdog writes and timestamped count reads through SEP_IN.

class smc_wdt_base_test_seq extends smc_base_test_seq;
  `uvm_object_utils(smc_wdt_base_test_seq)

  int unsigned core;

  function new(string name = "smc_wdt_base_test_seq");
    super.new(name);
  endfunction

  protected function real smc_cycle_time();
    return $realtime / env_cfg.smc_clk_period_ns;
  endfunction

  protected task wdt_write(smc_wdt_reg_e reg_kind, bit [31:0] value);
    csr_write(smc_wdt_addr(core, WDT_KEY), SmcWdtMagicKey, "WDT.KEY");
    csr_write(smc_wdt_addr(core, reg_kind), value, "WDT write");
  endtask

  protected task read_count(output bit [31:0] value, output real sampled_at);
    csr_read(smc_wdt_addr(core, WDT_COUNT), value, "WDT.COUNT");
    sampled_at = smc_cycle_time();
  endtask
endclass : smc_wdt_base_test_seq
