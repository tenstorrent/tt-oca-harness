// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Slave-side (reactive TAP device) agent configuration: IDCODE, IR width,
// data-register map, and pin binding. The environment builds one, attaches
// the virtual interface, and publishes it via
// uvm_config_db#(ocah_jtag_slave_config)::set(..., "slave_cfg", ...).

// One Update-DR latch into a writable slave register (driver-recorded).
typedef struct {
  string       reg_name;
  bit [63:0]   opcode;
  bit [63:0]   value;
  int unsigned width;
  time         timestamp;
} ocah_jtag_slave_update_t;

class ocah_jtag_slave_config extends uvm_object;
  `uvm_object_utils(ocah_jtag_slave_config)

  virtual ocah_jtag_if vif;

  uvm_active_passive_enum is_active = UVM_ACTIVE;
  bit en_monitor = 1;

  int unsigned ir_width = 5;
  // IEEE 1149.1: the two IR LSBs capture 01; extra capture bits above them
  // may carry design-specific status.
  bit [63:0]   ir_capture = 'h1;

  bit          has_idcode = 1;
  bit [31:0]   idcode = 32'h0000_0001;
  bit [63:0]   idcode_opcode = 'h1;

  bit          drive_tdo_oen = 1;

  // Data-register map keyed by IR opcode (<= 64-bit registers; BYPASS and
  // unknown opcodes are implicit). IDCODE capture comes from `idcode`.
  string       reg_name[bit [63:0]];
  int unsigned reg_width[bit [63:0]];
  bit          reg_writable[bit [63:0]];
  bit [63:0]   reg_reset_value[bit [63:0]];

  function new(string name = "ocah_jtag_slave_config");
    super.new(name);
  endfunction

  function void add_reg(string name, bit [63:0] opcode, int unsigned width, bit writable = 1'b0,
                        bit [63:0] reset_value = '0);
    if (width == 0 || width > 64)
      `uvm_fatal(get_type_name(), $sformatf(
                 "%s: slave register width must be 1..64, got %0d", name, width))
    reg_name[opcode]        = name;
    reg_width[opcode]       = width;
    reg_writable[opcode]    = writable;
    reg_reset_value[opcode] = reset_value & ((width < 64) ? ((64'h1 << width) - 1) : '1);
  endfunction

endclass : ocah_jtag_slave_config
