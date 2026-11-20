// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI single write and read-back through one bridge's System Bus Access:
// a seeded word and its neighbour are written through `target`, then the
// first is read back. The cocotb twin is
// seq_lib/dtp_jtag2axi_single_write_read_test_seq.py.

class dtp_jtag2axi_single_write_read_test_seq extends dtp_jtag2axi_base_test_seq;
  `uvm_object_utils(dtp_jtag2axi_single_write_read_test_seq)

  // The bridge the pass drives (smc_axi, smc_otp, sep_otp); set by the test
  // before start().
  string target = "smc_axi";

  function new(string name = "dtp_jtag2axi_single_write_read_test_seq");
    super.new(name);
  endfunction

  virtual function string bus_ledger_target();
    return target;
  endfunction

  task body();
    dtp_j2a_target_t t = dtp_j2a_target_by_name(target);
    bit       [63:0] addr;
    bit       [63:0] data;
    bit       [63:0] rdata;
    seed_scenario_rng();
    `uvm_info(get_type_name(), $sformatf("=== %s single write-read ===", target), UVM_LOW)
    enable_all_debug();
    tap_reset();
    step(1'b0);
    addr = random_target_addr(t);
    write_neighbour_then_read(t, addr, "single_wr_rd", rdata, data);
    check_responder_activity(t, 3, "single_wr_rd");
    `uvm_info(get_type_name(),
              $sformatf("Summary: %s single write-read complete addr=0x%0h data=0x%0h rdata=0x%0h",
                        target, addr, data, rdata), UVM_LOW)
  endtask

endclass : dtp_jtag2axi_single_write_read_test_seq
