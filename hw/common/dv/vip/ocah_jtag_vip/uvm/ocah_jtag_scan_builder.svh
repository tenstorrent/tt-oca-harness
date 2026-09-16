// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// IR/DR scan-level reconstruction over the passive monitor's STEP stream.
// Mirrors the cocotb OcahJtagMasterMonitor reconstruction: walk the IEEE
// 1149.1 reference FSM from the sampled TMS bits, accumulate TDI/TDO while
// the controller is in Shift-x, and publish one ocah_jtag_scan_item on each
// Shift-x -> Exit1-x transition. A scan that re-enters Shift-x via
// Pause/Exit2 publishes a partial item at the first Exit1-x and a cumulative
// item at the last, same as the cocotb builder.
//
// Purely passive and DUT-agnostic: state comes from the reference model,
// never from DUT observables. TRST assertion (event or sampled level)
// re-baselines to Test-Logic-Reset and drops any partial accumulation.

class ocah_jtag_scan_builder extends uvm_subscriber #(ocah_jtag_event);
  `uvm_component_utils(ocah_jtag_scan_builder)

  uvm_analysis_port #(ocah_jtag_scan_item) scan_ap;

  int unsigned max_history = 2000;

  ocah_jtag_scan_item ir_items[$];
  ocah_jtag_scan_item dr_items[$];

  protected ocah_jtag_tap_state_e m_model = OCAH_JTAG_TEST_LOGIC_RESET;
  protected bit          m_tdi_acc[$];
  protected bit          m_tdo_acc[$];
  protected time         m_scan_start;
  protected bit          m_active_ir_known;
  protected bit [63:0]   m_active_ir;
  protected bit          m_pending_ir_valid;
  protected bit [63:0]   m_pending_ir;

  function new(string name = "ocah_jtag_scan_builder", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    scan_ap = new("scan_ap", this);
  endfunction

  function void write(ocah_jtag_event t);
    ocah_jtag_tap_state_e previous;

    if (t.kind == OCAH_JTAG_EV_TRST) begin
      if (t.trst_asserted) reset_reconstruction();
      return;
    end
    if (t.trst_n === 1'b0) begin
      reset_reconstruction();
      return;
    end

    previous = m_model;

    // Capture-x entry restarts accumulation for a fresh scan.
    if (previous inside {OCAH_JTAG_CAPTURE_IR, OCAH_JTAG_CAPTURE_DR}) begin
      m_tdi_acc.delete();
      m_tdo_acc.delete();
      m_scan_start = t.timestamp;
    end

    if (previous inside {OCAH_JTAG_SHIFT_IR, OCAH_JTAG_SHIFT_DR}) begin
      m_tdi_acc.push_back(t.tdi);
      m_tdo_acc.push_back(t.tdo);
    end

    m_model = ocah_jtag_next_state(previous, t.tms);

    if (previous == OCAH_JTAG_SHIFT_IR && m_model == OCAH_JTAG_EXIT1_IR) begin
      ocah_jtag_scan_item item = publish(1'b1, t.timestamp);
      m_pending_ir       = item.tdi_value();
      m_pending_ir_valid = 1'b1;
    end else if (previous == OCAH_JTAG_SHIFT_DR && m_model == OCAH_JTAG_EXIT1_DR) begin
      void'(publish(1'b0, t.timestamp));
    end

    // The instruction becomes active leaving Update-IR. Without a Shift-IR
    // cycle the register latches its device-specific Capture-IR pattern,
    // which the reconstruction cannot know.
    if (previous == OCAH_JTAG_UPDATE_IR) begin
      if (m_pending_ir_valid) begin
        m_active_ir       = m_pending_ir;
        m_active_ir_known = 1'b1;
      end else m_active_ir_known = 1'b0;
      m_pending_ir_valid = 1'b0;
    end
  endfunction

  function void clear_history();
    ir_items.delete();
    dr_items.delete();
  endfunction

  protected function void reset_reconstruction();
    m_model = OCAH_JTAG_TEST_LOGIC_RESET;
    m_tdi_acc.delete();
    m_tdo_acc.delete();
    m_pending_ir_valid = 1'b0;
    // IEEE 1149.1: reset selects IDCODE (when implemented) or BYPASS;
    // the exact opcode is device-specific, so mark it unknown.
    m_active_ir_known = 1'b0;
  endfunction

  protected function ocah_jtag_scan_item publish(bit is_ir, time end_time);
    ocah_jtag_scan_item item = ocah_jtag_scan_item::type_id::create("scan_item");
    item.is_ir      = is_ir;
    item.tdi_bits   = m_tdi_acc;
    item.tdo_bits   = m_tdo_acc;
    item.bit_count  = m_tdi_acc.size();
    item.start_time = m_scan_start;
    item.end_time   = end_time;
    if (!is_ir && m_active_ir_known) begin
      item.instruction_known = 1'b1;
      item.instruction       = m_active_ir;
    end
    if (is_ir) begin
      if (ir_items.size() < max_history) ir_items.push_back(item);
    end else begin
      if (dr_items.size() < max_history) dr_items.push_back(item);
    end
    `uvm_info(get_type_name(), item.convert2string(), UVM_MEDIUM)
    scan_ap.write(item);
    return item;
  endfunction

endclass : ocah_jtag_scan_builder
