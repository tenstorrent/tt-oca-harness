// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// One reset-release event on the SMU boundary, published by
// smu_reset_pin_monitor when a watched reset observable rises, carrying the
// levels of the gating inputs sampled in the same SMU clock: the external
// boot-sequence gate and the SMC fuse-sense completion. The boot_gate
// reference model predicts the levels a legal release requires; the
// scoreboard pairs the two. No cocotb twin.

typedef enum int unsigned {
  SMU_PIN_EV_FUSE_RESET_RELEASE = 0,
  SMU_PIN_EV_PRIMARY_RESET_RELEASE = 1
} smu_pin_event_kind_e;

class smu_pin_event_item extends uvm_object;
  `uvm_object_utils(smu_pin_event_item)

  smu_pin_event_kind_e kind;
  // Levels sampled with the rise.
  bit                  ext_boot_seq_done;
  bit                  fuse_sense_done;
  // Predictions: compare = 0 carries no contract.
  bit                  compare = 1'b0;
  string               context_s;
  time                 timestamp;

  function new(string name = "smu_pin_event_item");
    super.new(name);
  endfunction

  virtual function string convert2string();
    return $sformatf(
        "%s ext_boot_seq_done=%0b fuse_sense_done=%0b @%0t %s",
        kind.name(),
        ext_boot_seq_done,
        fuse_sense_done,
        timestamp,
        context_s
    );
  endfunction

endclass : smu_pin_event_item
