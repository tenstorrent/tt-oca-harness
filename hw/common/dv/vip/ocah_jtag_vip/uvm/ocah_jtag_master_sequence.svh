// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VIP-level base sequence: the reusable stimulus API over ocah_jtag_item.
// DUT sequence libraries extend this class and add their DUT-specific
// checking (observable TAP-state comparison, reset sequencing, evidence
// hooks) on top of these protocol-neutral operations. Scan preconditions
// follow the item contract: IR/DR scans assume Run-Test/Idle (the driver
// navigates RTI -> scan leg -> RTI).
//
// The sequence tracks the predicted TAP state through an owned
// ocah_jtag_ref_model (mirroring the cocotb OcahJtagMasterDriver's tracked state):
// every task steps the model with the exact TMS bits the driver drives, so
// goto_state() can plan a shortest TMS path from the current state and
// current_state() stays valid across raw walks and scans. Tracking is per
// sequence instance and assumes this sequence is the TAP's only stimulus
// source; after TAP movement the sequence cannot see (e.g. a power-on
// reset), re-align with sync_model(). Any five consecutive
// TMS=1 steps self-correct the model regardless of prior drift.

class ocah_jtag_master_sequence extends uvm_sequence #(ocah_jtag_item);
  `uvm_object_utils(ocah_jtag_master_sequence)

  protected ocah_jtag_ref_model m_model;
  // TRST level after the last assert_trst()/release_trst(); released at construction.
  protected bit m_trst_asserted = 1'b0;

  function new(string name = "ocah_jtag_master_sequence");
    super.new(name);
    m_model = ocah_jtag_ref_model::type_id::create({name, ".model"});
  endfunction

  task do_jtag(ocah_jtag_item it);
    start_item(it);
    finish_item(it);
  endtask

  // ------------------------------------------------------------------
  // Tracked-state helpers.
  // ------------------------------------------------------------------

  // Predicted TAP state after the last issued operation.
  function ocah_jtag_tap_state_e current_state();
    return m_model.state();
  endfunction

  // Re-align tracking after TAP movement this sequence did not drive.
  function void sync_model(ocah_jtag_tap_state_e state);
    m_model.sync_state(state);
  endfunction

  // Step the model through the exact TMS leg the driver drives for a scan
  // (see ocah_jtag_master_driver::do_scan).
  protected function void model_scan(bit sel_ir, int unsigned nbits);
    void'(m_model.step(1'b1));  // RTI       -> Select-DR
    if (sel_ir) void'(m_model.step(1'b1));  // Select-DR -> Select-IR
    void'(m_model.step(1'b0));  // Select-x  -> Capture-x
    void'(m_model.step(1'b0));  // Capture-x -> Shift-x
    for (int unsigned i = 0; i < nbits; i++)
    void'(m_model.step(i == nbits - 1));  // last: -> Exit1-x
    void'(m_model.step(1'b1));  // Exit1-x   -> Update-x
    void'(m_model.step(1'b0));  // Update-x  -> RTI
  endfunction

  // Scan preconditions are the caller's contract (item header); flag
  // violations instead of silently mis-predicting the scan result.
  protected function void warn_scan_precondition(string op_name);
    ocah_jtag_tap_state_e tracked = m_model.state();
    if (tracked != OCAH_JTAG_RUN_TEST_IDLE)
      `uvm_error(get_type_name(), $sformatf(
                 "%s issued with tracked TAP state %s; the scan contract expects RUN_TEST_IDLE",
                 op_name,
                 tracked.name()
                 ))
  endfunction

  // ------------------------------------------------------------------
  // Raw stepping and navigation.
  // ------------------------------------------------------------------

  // One raw TCK step (tms/tdi) from any state.
  task step(bit tms, bit tdi = 1'b0);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("step");
    it.op       = OCAH_JTAG_RAW_TMS;
    it.tms_bits = new[1];
    it.tdi_bits = new[1];
    it.tms_bits[0] = tms;
    it.tdi_bits[0] = tdi;
    do_jtag(it);
    void'(m_model.step(tms));
  endtask

  // Raw TMS/TDI walk, one TCK cycle per element.
  task raw_walk(bit tms_bits[], bit tdi_bits[]);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("raw_walk");
    it.op       = OCAH_JTAG_RAW_TMS;
    it.tms_bits = tms_bits;
    it.tdi_bits = tdi_bits;
    do_jtag(it);
    foreach (tms_bits[i]) void'(m_model.step(tms_bits[i]));
  endtask

  // Navigate to `target` on a shortest TMS path from the tracked state
  // (TDI held 0), issued as one raw item. No-op when already there.
  task goto_state(ocah_jtag_tap_state_e target);
    bit path[$];
    bit tms[], tdi[];
    ocah_jtag_tms_path(m_model.state(), target, path);
    if (path.size() == 0) return;
    tms = new[path.size()];
    tdi = new[path.size()];
    foreach (path[i]) tms[i] = path[i];
    raw_walk(tms, tdi);
  endtask

  // Navigate to a random TAP state (optionally excluding states) and
  // return the state reached. Randomization uses the calling thread's
  // RNG, so runs reproduce from the simulator seed.
  task goto_random_state(output ocah_jtag_tap_state_e reached,
                         input ocah_jtag_tap_state_e exclude[$] = {});
    ocah_jtag_tap_state_e candidates[$];
    for (int unsigned i = 0; i < 16; i++) begin
      ocah_jtag_tap_state_e s = ocah_jtag_tap_state_e'(i);
      bit excluded = 1'b0;
      foreach (exclude[j]) if (exclude[j] == s) excluded = 1'b1;
      if (!excluded) candidates.push_back(s);
    end
    if (candidates.size() == 0)
      `uvm_fatal(get_type_name(), "no TAP state choices remain after exclusions")
    reached = candidates[$urandom_range(candidates.size()-1)];
    goto_state(reached);
  endtask

  // Random TMS walk (TDI held 0), issued as one raw item; read the landing
  // state back with current_state().
  task random_tms_walk(int unsigned cycles);
    bit tms[], tdi[];
    if (cycles == 0) return;
    tms = new[cycles];
    tdi = new[cycles];
    foreach (tms[i]) tms[i] = bit'($urandom_range(1));
    raw_walk(tms, tdi);
  endtask

  // ------------------------------------------------------------------
  // Reset and scans.
  // ------------------------------------------------------------------

  // TAP reset: TRST pulse via the driver -> Test-Logic-Reset.
  task tap_reset_op();
    ocah_jtag_item it = ocah_jtag_item::type_id::create("tap_reset");
    it.op = OCAH_JTAG_TAP_RESET;
    do_jtag(it);
    m_model.reset_model();
  endtask

  // TRST level control through one TRST_LEVEL item: `tck_cycles` TCK cycles
  // run with TMS at `tms` after the level change. TMS high is the
  // Test-Logic-Reset self-loop; TMS low never enters Test-Logic-Reset, so
  // only the reset can put the controller there. Asserting resets the tracked model to
  // Test-Logic-Reset; releasing steps it through the cycles.
  task assert_trst(int unsigned tck_cycles = 1, bit tms = 1'b1);
    trst_level_op(1'b1, tck_cycles, tms);
    m_model.reset_model();
  endtask

  task release_trst(int unsigned tck_cycles = 0, bit tms = 1'b1);
    trst_level_op(1'b0, tck_cycles, tms);
    repeat (tck_cycles) void'(m_model.step(tms));
  endtask

  function bit trst_asserted();
    return m_trst_asserted;
  endfunction

  protected task trst_level_op(bit asserted, int unsigned tck_cycles, bit tms = 1'b1);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("trst_level");
    it.op              = OCAH_JTAG_TRST_LEVEL;
    it.trst_asserted   = asserted;
    it.trst_tck_cycles = tck_cycles;
    it.trst_tms        = tms;
    do_jtag(it);
    m_trst_asserted = asserted;
  endtask

  // IR scan from Run-Test/Idle (LSB-first), back to Run-Test/Idle.
  task ir_scan(input bit [63:0] instr, input int unsigned width, output bit [63:0] captured);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("ir_scan");
    warn_scan_precondition("ir_scan");
    it.op    = OCAH_JTAG_IR_SCAN;
    it.width = width;
    it.wdata = instr;
    do_jtag(it);
    captured = it.tdo;
    model_scan(1'b1, width);
  endtask

  // DR scan from Run-Test/Idle (LSB-first), returning observed TDO.
  task dr_scan(input bit [63:0] pattern, input int unsigned width, output bit [63:0] observed);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("dr_scan");
    warn_scan_precondition("dr_scan");
    it.op    = OCAH_JTAG_DR_SCAN;
    it.width = width;
    it.wdata = pattern;
    do_jtag(it);
    observed = it.tdo;
    model_scan(1'b0, width);
  endtask

  // Wide DR scan (no 64-bit limit), one bit per element, LSB-first.
  task dr_scan_wide(input bit pattern[], output bit observed[]);
    ocah_jtag_item it = ocah_jtag_item::type_id::create("dr_scan_wide");
    warn_scan_precondition("dr_scan_wide");
    it.op    = OCAH_JTAG_DR_SCAN;
    it.wbits = pattern;
    do_jtag(it);
    observed = it.rbits;
    model_scan(1'b0, pattern.size());
  endtask

endclass : ocah_jtag_master_sequence
