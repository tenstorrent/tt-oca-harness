// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// TMP persistence across chip reset: CLAMP_HOLD drives Persistence-On,
// a seeded-width rst_n_i pulse (POR and TRST untouched) must not clear it,
// and the TAP must still read IDCODE afterwards. Mirrors the cocotb
// dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq.

class dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq extends dtp_debug_tdr_base_test_seq;
  `uvm_object_utils(dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq)

  function new(string name = "dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq");
    super.new(name);
  endfunction

  task body();
    string required[$] = {"CHK-TAP-RESET-TLR", "CHK-TMP-PERSIST", "CHK-DBG-TDR"};
    bit persistence, bypass_escape;
    bit [63:0] idcode;
    int unsigned reset_cycles;
    seed_scenario_rng();
    attach_family_checker(required);

    reset_to_tlr();
    load_ir(6'(CLAMP_HOLD_INSTR));
    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1,
                 "before chip reset");

    // Seeded per-pass pulse width: each loop varies how long rst_n_i
    // stays low relative to the free-running TCK.
    reset_cycles = $urandom_range(12, 3);
    `uvm_info(get_type_name(), $sformatf("Pulse rst_n_i for %0d cycles with TAP held accessible",
                                         reset_cycles), UVM_LOW)
    pulse_system_reset(reset_cycles);

    read_tmp_status(persistence, bypass_escape);
    family_check("CHK-TMP-PERSIST", "TMP_STATUS.persistence", 64'(persistence), 64'd1, $sformatf(
                 "after %0d-cycle chip reset", reset_cycles));

    read_idcode(idcode);
    family_check("CHK-DBG-TDR", "IDCODE.lsb", idcode & 64'h1, 64'd1, $sformatf(
                 "idcode=0x%08h", idcode));

    finalize_family_checker();
  endtask

endclass : dtp_jtag_tmp_status_chrst_n_in_persistence_test_seq
