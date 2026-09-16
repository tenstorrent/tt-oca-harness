// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reactive IEEE 1149.1 TAP device — the SV analogue of the cocotb
// OcahJtagSlaveDriver/Engine. Responds on TDO when the other end of the
// wire (a DUT JTAG host port, or the VIP's own master driver in a
// back-to-back bench) drives TCK/TMS/TDI:
//
//   * rising edge:  capture in Capture-x, shift in Shift-x (TDI enters the
//     MSB), then the controller advances per ocah_jtag_next_state()
//   * falling edge: latch in Update-x (writable registers recorded in
//     `updates`), re-select the reset instruction in Test-Logic-Reset, and
//     drive TDO with the selected shift register's LSB (TDO enabled only
//     while shifting)
//
// Test-Logic-Reset selects IDCODE (BYPASS when cfg.has_idcode == 0), and
// unimplemented instructions behave as BYPASS. Reactive: there is no
// sequence-driven stimulus, so the agent has no sequencer; tests configure
// and inspect the device through ocah_jtag_slave_sequence.
//
// Rule provenance: implemented from the public IEEE Std 1149.1 clause
// descriptions. No third-party device-model source was consulted or copied.

class ocah_jtag_slave_driver extends uvm_component;
  `uvm_component_utils(ocah_jtag_slave_driver)

  ocah_jtag_slave_config cfg;

  ocah_jtag_slave_update_t updates[$];

  protected ocah_jtag_tap_state_e m_state = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit [63:0] m_ir_shift;
  protected bit [63:0] m_dr_shift;
  protected bit [63:0] m_active_ir;
  protected bit [63:0] m_reg_value[bit [63:0]];

  function new(string name = "ocah_jtag_slave_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_slave_config)::get(this, "", "slave_cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_slave_config `slave_cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_jtag_slave_config.vif is null")
    foreach (cfg.reg_width[op]) m_reg_value[op] = cfg.reg_reset_value[op];
    reset_device();
  endfunction

  // ------------------------------------------------------------------
  // Test-facing register access (consumed via ocah_jtag_slave_sequence).
  // ------------------------------------------------------------------

  function void set_register(bit [63:0] opcode, bit [63:0] value);
    if (!cfg.reg_width.exists(opcode))
      `uvm_fatal(get_type_name(), $sformatf(
                 "set_register: no slave register at opcode 0x%0h", opcode))
    m_reg_value[opcode] = value & width_mask(cfg.reg_width[opcode]);
  endfunction

  function bit [63:0] get_register(bit [63:0] opcode);
    if (!cfg.reg_width.exists(opcode))
      `uvm_fatal(get_type_name(), $sformatf(
                 "get_register: no slave register at opcode 0x%0h", opcode))
    return m_reg_value[opcode];
  endfunction

  function void clear_updates();
    updates.delete();
  endfunction

  function ocah_jtag_tap_state_e device_state();
    return m_state;
  endfunction

  function bit [63:0] active_instruction();
    return m_active_ir;
  endfunction

  // ------------------------------------------------------------------
  // Per-edge behavior.
  // ------------------------------------------------------------------

  protected function bit [63:0] width_mask(int unsigned width);
    return (width < 64) ? ((64'h1 << width) - 1) : '1;
  endfunction

  protected function int unsigned selected_width();
    if (cfg.has_idcode && m_active_ir == cfg.idcode_opcode) return 32;
    if (cfg.reg_width.exists(m_active_ir)) return cfg.reg_width[m_active_ir];
    return 1;  // BYPASS and unimplemented instructions
  endfunction

  protected function bit [63:0] capture_dr_value();
    if (cfg.has_idcode && m_active_ir == cfg.idcode_opcode) return {32'h0, cfg.idcode};
    if (cfg.reg_width.exists(m_active_ir)) return m_reg_value[m_active_ir];
    return '0;  // BYPASS captures 0
  endfunction

  protected function void reset_device();
    m_state = OCAH_JTAG_TEST_LOGIC_RESET;
    m_active_ir = cfg.has_idcode ? cfg.idcode_opcode
                                     : width_mask(cfg.ir_width);
  endfunction

  protected function void clock_rise(bit tms, bit tdi);
    case (m_state)
      OCAH_JTAG_CAPTURE_IR:
                m_ir_shift = (cfg.ir_capture | 64'h1) & width_mask(cfg.ir_width);
      OCAH_JTAG_SHIFT_IR:
                m_ir_shift = ((m_ir_shift >> 1) | (64'(tdi) << (cfg.ir_width - 1)))
                             & width_mask(cfg.ir_width);
      OCAH_JTAG_CAPTURE_DR:
                m_dr_shift = capture_dr_value();
      OCAH_JTAG_SHIFT_DR:
                m_dr_shift = ((m_dr_shift >> 1) | (64'(tdi) << (selected_width() - 1)))
                             & width_mask(selected_width());
      default: ;
    endcase
    m_state = ocah_jtag_next_state(m_state, tms);
  endfunction

  protected function void clock_fall(output bit tdo, output bit oen);
    case (m_state)
      OCAH_JTAG_UPDATE_IR:
                m_active_ir = m_ir_shift & width_mask(cfg.ir_width);
      OCAH_JTAG_UPDATE_DR: latch_dr();
      OCAH_JTAG_TEST_LOGIC_RESET: reset_device();
      default: ;
    endcase
    tdo = 1'b0;
    oen = 1'b0;
    if (m_state == OCAH_JTAG_SHIFT_IR) begin
      tdo = m_ir_shift[0];
      oen = 1'b1;
    end else if (m_state == OCAH_JTAG_SHIFT_DR) begin
      tdo = m_dr_shift[0];
      oen = 1'b1;
    end
  endfunction

  protected function void latch_dr();
    ocah_jtag_slave_update_t update;
    if (!cfg.reg_writable.exists(m_active_ir) || !cfg.reg_writable[m_active_ir]) return;
    m_reg_value[m_active_ir] = m_dr_shift & width_mask(cfg.reg_width[m_active_ir]);
    update.reg_name  = cfg.reg_name[m_active_ir];
    update.opcode    = m_active_ir;
    update.value     = m_reg_value[m_active_ir];
    update.width     = cfg.reg_width[m_active_ir];
    update.timestamp = $time;
    updates.push_back(update);
    `uvm_info(get_type_name(), $sformatf(
              "Update-DR latched %s = 0x%0h", update.reg_name, update.value), UVM_MEDIUM)
  endfunction

  task run_phase(uvm_phase phase);
    cfg.vif.tdo <= 1'b0;
    if (cfg.drive_tdo_oen) cfg.vif.tdo_oen <= 1'b0;
    fork
      pump();
      watch_trst();
    join
  endtask

  protected virtual task pump();
    bit tms, tdi, tdo, oen;
    forever begin
      @(posedge cfg.vif.tck);
      tms = cfg.vif.tms;
      tdi = cfg.vif.tdi;
      if (cfg.vif.trst_n === 1'b0) reset_device();
      else clock_rise(tms, tdi);
      @(negedge cfg.vif.tck);
      clock_fall(tdo, oen);
      cfg.vif.tdo <= tdo;
      if (cfg.drive_tdo_oen) cfg.vif.tdo_oen <= oen;
    end
  endtask

  protected virtual task watch_trst();
    forever begin
      @(negedge cfg.vif.trst_n);
      reset_device();
      `uvm_info(get_type_name(), "TRST asserted -> Test-Logic-Reset", UVM_MEDIUM)
    end
  endtask

endclass : ocah_jtag_slave_driver
