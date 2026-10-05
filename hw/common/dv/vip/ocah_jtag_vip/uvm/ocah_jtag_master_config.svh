// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Agent configuration. The environment builds one, attaches the virtual
// interface, and publishes it to the agent via
// uvm_config_db#(ocah_jtag_master_config)::set(..., "cfg", ...).

class ocah_jtag_master_config extends uvm_object;
  `uvm_object_utils(ocah_jtag_master_config)

  virtual ocah_jtag_if vif;

  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // OCAH passive monitor enable. Commercial-VIP env subclasses set 0: the
  // vendor system env then owns driving AND monitoring, and the OCAH
  // event_ap stream goes silent (subscribers keyed to ocah_jtag_event must
  // be re-pointed or adapted by the integration).
  bit en_monitor = 1;

  // Optional functional-coverage subscriber (uvm/ocah_jtag_cov.svh). When
  // set, the env builds ocah_jtag_cov, which requires the TB to instantiate
  // ocah_jtag_cov_if and publish it as "jtag_cov_vif". Commercial-simulator
  // flows only.
  bit en_cov = 0;

  // Opaque extension hook for commercial-VIP env subclasses (the vendor
  // system configuration object built by the integration and consumed in
  // the subclass's build_phase). The OCAH implementation ignores it.
  uvm_object vendor_cfg;

  // Bit-banged TCK timing: full period = 2 * tck_half_period.
  time tck_half_period = 50ns;    // 10 MHz default

  // TAP_RESET op: TCK cycles with TRST asserted (TMS held 1) before release.
  int unsigned trst_reset_cycles = 3;

  function new(string name = "ocah_jtag_master_config");
    super.new(name);
  endfunction

endclass : ocah_jtag_master_config
