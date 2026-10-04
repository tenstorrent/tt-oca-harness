// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Demotes a UVM_ERROR whose report id equals `message_id` and whose message
// contains `message_text` (an empty `message_text` matches every message) to
// UVM_INFO and counts it; every other report passes through. A sequence
// reports under its own type name.

class ocah_axi_expected_error_catcher extends uvm_report_catcher;
  `uvm_object_utils(ocah_axi_expected_error_catcher)

  string       message_id;
  string       message_text;
  int unsigned caught;

  function new(string name = "ocah_axi_expected_error_catcher");
    super.new(name);
  endfunction

  function action_e catch();
    if (get_severity() != UVM_ERROR || get_id() != message_id) return THROW;
    if (!contains(get_message(), message_text)) return THROW;
    caught++;
    set_severity(UVM_INFO);
    return THROW;
  endfunction

  protected function bit contains(string text, string part);
    if (part.len() == 0) return 1'b1;
    for (int i = 0; i + part.len() <= text.len(); i++) begin
      if (text.substr(i, i + part.len() - 1) == part) return 1'b1;
    end
    return 1'b0;
  endfunction

endclass : ocah_axi_expected_error_catcher
