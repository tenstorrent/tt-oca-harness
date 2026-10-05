// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reference-model base: the per-feature predictor behind the mandatory bench
// scoreboard (a bench `<dut>_<feature>_ref_model`). It subscribes to the VIP
// monitor stream the feature is observed on, reads tb_if observables through
// handles the env plumbs, keeps whatever model state the prediction needs,
// and republishes one expected item per transaction it predicts on
// expected_ap, in observation order; the scoreboard pairs that stream with
// the observed one. Expected values derive from configuration and the
// observed stimulus, never from the observation under check. A reference
// model performs no comparison and emits no verdict: a mismatch is the
// scoreboard's finding. write() never blocks. The cocotb twin is
// ocah_lib.OcahRefModel.

class ocah_ref_model #(
  type OBS = uvm_object,
  type EXP = OBS
) extends uvm_subscriber #(OBS);
  `uvm_component_param_utils(ocah_ref_model#(OBS, EXP))

  // Expected items, one per predicted transaction, in observation order.
  uvm_analysis_port #(EXP) expected_ap;

  function new(string name = "ocah_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    expected_ap = new("expected_ap", this);
  endfunction

  // The stream handler; every concrete reference model overrides it. The
  // base accepts and drops, so an unconnected base instance is inert.
  virtual function void write(OBS t);
  endfunction

endclass : ocah_ref_model
