// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// One downstream STAP TAP behind a STAP host port (cocotb StapDownstream
// parity), predicted from IEEE 1149.1 and never read back from the VIP's
// device engine: Test-Logic-Reset selects IDCODE, an unknown instruction
// selects the one-bit BYPASS, Capture-IR presents 01 in the IR LSBs, and a
// writable register latches the shifted-in value on Update-DR. Seeded from
// the attached device's ocah_jtag_slave_config. Plain model class, built
// with new(); no reporting. Types come from dtp_types.svh.

// Tracked state of the downstream TAP spliced behind one STAP host port,
// seeded from the attached device's ocah_jtag_slave_config (IR width, IDCODE,
// register map).
class dtp_stap_ds_state;

  int unsigned      ir_width;
  bit [31:0]        idcode;
  bit [63:0]        idcode_opcode;
  dtp_stap_ds_reg_t regs[bit [63:0]];   // keyed by IR opcode; IDCODE and BYPASS included
  bit [63:0]        active_ir;
  bit [63:0]        values[string];     // writable registers, keyed by name

  function new(ocah_jtag_slave_config cfg);
    dtp_stap_ds_reg_t r;
    if (!cfg.has_idcode) `uvm_fatal("dtp_stap_ds_state", "downstream device has no IDCODE register")
    ir_width      = cfg.ir_width;
    idcode        = cfg.idcode;
    idcode_opcode = cfg.idcode_opcode;
    r = '{"IDCODE", cfg.idcode_opcode, 32, 1'b0};
    regs[cfg.idcode_opcode] = r;
    foreach (cfg.reg_name[op]) begin
      r = '{cfg.reg_name[op], op, cfg.reg_width[op], cfg.reg_writable[op]};
      regs[op] = r;
      if (cfg.reg_writable[op]) values[cfg.reg_name[op]] = cfg.reg_reset_value[op];
    end
    if (!regs.exists(bypass_opcode())) begin
      r = '{"BYPASS", bypass_opcode(), 1, 1'b0};
      regs[bypass_opcode()] = r;
    end
    reset_instruction();
  endfunction

  function bit [63:0] bypass_opcode();
    return (ir_width >= 64) ? '1 : ((64'h1 << ir_width) - 1);
  endfunction

  function bit [63:0] width_mask(int unsigned width);
    return (width >= 64) ? '1 : ((64'h1 << width) - 1);
  endfunction

  // Resolve a register name to its opcode.
  function bit opcode_of(string name, output bit [63:0] opcode);
    foreach (regs[op])
    if (regs[op].name == name) begin
      opcode = op;
      return 1'b1;
    end
    return 1'b0;
  endfunction

  // The register the active instruction selects (0 = BYPASS behavior).
  function bit selected(output dtp_stap_ds_reg_t r);
    bit [63:0] op = active_ir & bypass_opcode();
    if (!regs.exists(op) || regs[op].name == "BYPASS") return 1'b0;
    r = regs[op];
    return 1'b1;
  endfunction

  // Chain segment width the downstream contributes to a composed scan.
  function int unsigned selected_width(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return ir_width;
    if (selected(r) && r.width > 0) return r.width;
    return 1;
  endfunction

  // Segment value a maintain scan shifts in: the stored value of a
  // writable register (re-latched unchanged), the active IR for an IR
  // scan, zero otherwise.
  function bit [63:0] shift_default(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return active_ir;
    if (selected(r) && r.writable) return values[r.name];
    return '0;
  endfunction

  // Segment value the downstream captures at Capture-IR / Capture-DR.
  function bit [63:0] capture(dtp_scan_kind_e kind);
    dtp_stap_ds_reg_t r;
    if (kind == DTP_SCAN_IR) return DtpStapDsIrCapture & width_mask(ir_width);
    if (!selected(r)) return '0;
    if (r.name == "IDCODE") return {32'h0, idcode};
    return values.exists(r.name) ? values[r.name] : '0;
  endfunction

  // Update-DR: a writable selected register takes the shifted value.
  function void latch(bit [63:0] value);
    dtp_stap_ds_reg_t r;
    if (selected(r) && r.writable) values[r.name] = value & width_mask(r.width);
  endfunction

  function void update_ir(bit [63:0] opcode);
    active_ir = opcode & bypass_opcode();
  endfunction

  // Test-Logic-Reset (TRST, or five parked TMS=1 cycles) selects IDCODE.
  function void reset_instruction();
    active_ir = idcode_opcode;
  endfunction

endclass : dtp_stap_ds_state
