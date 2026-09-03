// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Configuration for one active ocah_axi_vip master (AXI initiator).
//
// The environment builds one, attaches the virtual interface, and publishes
// it to the agent via uvm_config_db#(ocah_axi_master_config)::set(..., "cfg", ...)
// (env-wrapped unit: plain `cfg`, per the UVM Env Surface Convention).

class ocah_axi_master_config extends uvm_object;
  `uvm_object_utils(ocah_axi_master_config)

  // The master drives the initiator-side signals (aw*/w*/ar* request
  // payloads plus awvalid/wvalid/arvalid/bready/rready) on this interface
  // procedurally and samples the responder-driven signals through mon_cb;
  // the TB routes the responder-driven direction in (see the selftest
  // harness adoption in dv/tb/tb_top.sv).
  virtual ocah_axi_if vif;

  ocah_axi_protocol_e protocol   = OCAH_AXI_PROTO_AXI4;
  int unsigned        addr_width = 32;
  int unsigned        data_width = 32;
  int unsigned        id_width   = 0;

  uvm_active_passive_enum is_active = UVM_ACTIVE;

  // Handshake watchdog: mon_cb cycles each wait (AW/W/B/AR/R) may take
  // before the driver gives up and completes the item with timed_out set
  // (the sequence layer decides whether a timeout is an error, mirroring
  // the cocotb allow_timeout contract). 0 disables the watchdog.
  int unsigned timeout_cycles = 1000;

  // Stable name for log messages.
  string name_tag = "ocah_axi_master";

  // Commercial-VIP integration hook (opaque; template parity with the JTAG
  // master cfg): an env subclass may carry its vendor system configuration
  // here. The OCAH implementation ignores it.
  uvm_object vendor_cfg;

  function new(string name = "ocah_axi_master_config");
    super.new(name);
  endfunction

  function int unsigned beat_bytes();
    return data_width / 8;
  endfunction

  // Full-beat lane mask at the configured geometry.
  function bit [7:0] full_strb();
    return 8'((64'd1 << beat_bytes()) - 1);
  endfunction

  function bit [15:0] mask_id(bit [15:0] value);
    return (id_width == 0) ? '0 : (value & ((16'd1 << id_width) - 1));
  endfunction

endclass : ocah_axi_master_config
