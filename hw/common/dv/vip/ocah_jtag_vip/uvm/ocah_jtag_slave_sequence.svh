// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Slave-side sequence API — the test-facing surface over the reactive TAP
// device (the SV analogue of the cocotb OcahJtagSlaveSequence). The slave
// is reactive: the external host supplies all TCK/TMS/TDI stimulus, so this
// layer configures responses and judges what the host wrote, emitting named
// CHK-* evidence through a shared ocah_jtag_checker when one is attached.
// Tests use this class (or a DUT layer built on it), never the raw driver.

class ocah_jtag_slave_sequence extends uvm_object;
  `uvm_object_utils(ocah_jtag_slave_sequence)

  ocah_jtag_slave_driver responder;
  ocah_jtag_checker      evidence;

  function new(string name = "ocah_jtag_slave_sequence");
    super.new(name);
  endfunction

  protected function void require_responder();
    if (responder == null) `uvm_fatal(get_type_name(), "responder handle not set")
  endfunction

  // ------------------------------------------------------------------
  // Response configuration.
  // ------------------------------------------------------------------

  function void set_register(bit [63:0] opcode, bit [63:0] value);
    require_responder();
    responder.set_register(opcode, value);
  endfunction

  function bit [63:0] get_register(bit [63:0] opcode);
    require_responder();
    return responder.get_register(opcode);
  endfunction

  function void clear_updates();
    require_responder();
    responder.clear_updates();
  endfunction

  // ------------------------------------------------------------------
  // Host-write inspection (emit CHK-* named evidence).
  // ------------------------------------------------------------------

  function bit check_last_update(string reg_name, bit [63:0] expected_value, string context_s = "",
                                 string check_id = "CHK-SLAVE-DR-UPDATE");
    ocah_jtag_slave_update_t matched[$];
    require_responder();
    foreach (responder.updates[i])
    if (responder.updates[i].reg_name == reg_name) matched.push_back(responder.updates[i]);
    if (matched.size() == 0) begin
      if (evidence != null)
        return evidence.expect_true(
            check_id, 1'b0, $sformatf("reg=%s no Update-DR observed %s", reg_name, context_s)
        );
      `uvm_error(get_type_name(), $sformatf("%s: no Update-DR observed for %s (%s)", check_id,
                                            reg_name, context_s))
      return 1'b0;
    end
    if (evidence != null)
      return evidence.expect_equal(
          check_id,
          matched[$].value,
          expected_value & ((matched[$].width < 64) ? ((64'h1 << matched[$].width) - 1) : '1),
          $sformatf(
              "reg=%s width=%0d %s", reg_name, matched[$].width, context_s)
      );
    if (matched[$].value !== expected_value) begin
      `uvm_error(get_type_name(), $sformatf("%s: reg=%s expected=0x%0h observed=0x%0h (%s)",
                                            check_id, reg_name, expected_value, matched[$].value,
                                            context_s))
      return 1'b0;
    end
    return 1'b1;
  endfunction

  function bit check_update_count(int unsigned expected, string reg_name = "",
                                  string context_s = "",
                                  string check_id = "CHK-SLAVE-DR-UPDATE-COUNT");
    int unsigned count = 0;
    require_responder();
    foreach (responder.updates[i])
    if (reg_name == "" || responder.updates[i].reg_name == reg_name) count++;
    if (evidence != null)
      return evidence.expect_equal(
          check_id,
          64'(count),
          64'(expected),
          $sformatf(
              "reg=%s %s", (reg_name == "") ? "any" : reg_name, context_s)
      );
    if (count != expected) begin
      `uvm_error(get_type_name(), $sformatf("%s: expected %0d updates, observed %0d (%s)",
                                            check_id, expected, count, context_s))
      return 1'b0;
    end
    return 1'b1;
  endfunction

endclass : ocah_jtag_slave_sequence
