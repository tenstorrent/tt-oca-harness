// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Demotes the driver's pipeline rejection to an info message and counts it.

class ocah_axi_pipeline_reject_catcher extends uvm_report_catcher;
  `uvm_object_utils(ocah_axi_pipeline_reject_catcher)

  int unsigned caught;

  function new(string name = "ocah_axi_pipeline_reject_catcher");
    super.new(name);
  endfunction

  function action_e catch();
    if (get_severity() == UVM_ERROR && get_id() == ocah_axi_master_driver::PipelineInvalidId) begin
      caught++;
      set_severity(UVM_INFO);
    end
    return THROW;
  endfunction

endclass : ocah_axi_pipeline_reject_catcher
