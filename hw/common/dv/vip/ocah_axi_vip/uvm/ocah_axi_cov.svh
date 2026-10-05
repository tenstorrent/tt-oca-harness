// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Optional functional-coverage subscriber: samples the existing shared
// covergroups in cov/ocah_axi_cov.sv (ocah_axi_cov_if, default parameters)
// once per completed transaction. Built only when cfg.en_cov is set; the TB
// instantiates ocah_axi_cov_if and publishes it as "axi_cov_vif".
// Commercial-simulator only (never in Verilator filelists), like the
// interface it samples.

class ocah_axi_cov extends uvm_subscriber #(ocah_axi_item);
  `uvm_component_utils(ocah_axi_cov)

  ocah_axi_config cfg;
  virtual ocah_axi_cov_if cov_vif;

  function new(string name = "ocah_axi_cov", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_config `cfg` not found in uvm_config_db")
    if (!uvm_config_db#(virtual ocah_axi_cov_if)::get(
            this, "", "axi_cov_vif", cov_vif
        ) || cov_vif == null)
      `uvm_fatal(get_type_name(), "virtual ocah_axi_cov_if `axi_cov_vif` not found")
  endfunction

  function void write(ocah_axi_item t);
    bit is_lite = (t.protocol == OCAH_AXI_PROTO_AXI4_LITE);
    if (t.direction == OCAH_AXI_DIR_WRITE)
      cov_vif.sample_write(is_lite, 64'(t.address), 8'(t.transaction_id), t.size, t.beat_count(),
                           t.worst_resp());
    else
      cov_vif.sample_read(is_lite, 64'(t.address), 8'(t.transaction_id), t.size, t.beat_count(),
                          t.worst_resp());
  endfunction

endclass : ocah_axi_cov
