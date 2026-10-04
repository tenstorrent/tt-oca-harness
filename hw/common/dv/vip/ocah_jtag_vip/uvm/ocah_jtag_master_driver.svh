// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Pin-level JTAG driver: bit-bangs TCK on the shared ocah_jtag_if.
//
// Timing per TCK cycle (period = 2 * cfg.tck_half_period):
//   drive tms/tdi at TCK low -> half period -> sample TDO (stable since the
//   DUT's previous falling edge) -> TCK rises (DUT captures tms/tdi, TAP
//   state advances) -> half period -> TCK falls (DUT updates TDO).
//
// Responses are written into the same item object before item_done, so the
// issuing sequence reads observed TDO directly after finish_item().

class ocah_jtag_master_driver extends uvm_driver #(ocah_jtag_item);
  `uvm_component_utils(ocah_jtag_master_driver)

  ocah_jtag_master_config cfg;

  function new(string name = "ocah_jtag_master_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_jtag_master_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_jtag_master_config `cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_jtag_master_config.vif is null")
  endfunction

  virtual task tck_cycle(bit tms, bit tdi, output bit tdo_s);
    cfg.vif.tms <= tms;
    cfg.vif.tdi <= tdi;
    #(cfg.tck_half_period);
    tdo_s = cfg.vif.tdo;
    cfg.vif.tck <= 1'b1;
    #(cfg.tck_half_period);
    cfg.vif.tck <= 1'b0;
  endtask

  virtual task step(bit tms, bit tdi = 1'b0);
    bit unused;
    tck_cycle(tms, tdi, unused);
  endtask

  // From Run-Test/Idle: navigate to Shift-IR/DR, shift LSB-first bits,
  // return to Run-Test/Idle. Caller contract: TAP is in RTI. A non-empty
  // it.wbits selects the wide path (bit count = wbits.size(), observed TDO
  // in it.rbits); otherwise the classic <=64-bit width/wdata/tdo path runs.
  virtual task do_scan(ocah_jtag_item it);
    bit sel_ir = (it.op == OCAH_JTAG_IR_SCAN);
    bit wide = (it.wbits.size() > 0);
    int unsigned nbits = wide ? it.wbits.size() : it.width;
    it.tdo = '0;
    if (wide) it.rbits = new[nbits];
    step(1'b1);  // RTI       -> Select-DR
    if (sel_ir) step(1'b1);  // Select-DR -> Select-IR
    step(1'b0);  // Select-x  -> Capture-x
    step(1'b0);  // Capture-x -> Shift-x
    for (int unsigned i = 0; i < nbits; i++) begin
      bit tdo_s;
      bit tdi_b = wide ? it.wbits[i] : it.wdata[i];
      tck_cycle(i == nbits - 1, tdi_b, tdo_s);  // last: -> Exit1-x
      if (wide) it.rbits[i] = tdo_s;
      else it.tdo[i] = tdo_s;
    end
    step(1'b1);  // Exit1-x   -> Update-x
    step(1'b0);  // Update-x  -> RTI
  endtask

  virtual task do_raw(ocah_jtag_item it);
    int unsigned n = it.tms_bits.size();
    it.tdo_bits = new[n];
    for (int unsigned i = 0; i < n; i++) begin
      bit tdi_b = (i < it.tdi_bits.size()) ? it.tdi_bits[i] : 1'b0;
      tck_cycle(it.tms_bits[i], tdi_b, it.tdo_bits[i]);
    end
  endtask

  virtual task do_tap_reset();
    cfg.vif.trst_n <= 1'b0;
    repeat (cfg.trst_reset_cycles) step(1'b1);
    cfg.vif.trst_n <= 1'b1;
    #(2 * cfg.tck_half_period);
  endtask

  virtual task do_trst_level(ocah_jtag_item it);
    cfg.vif.trst_n <= it.trst_asserted ? 1'b0 : 1'b1;
    repeat (it.trst_tck_cycles) step(it.trst_tms);
  endtask

  task run_phase(uvm_phase phase);
    // Idle pin values before the first item.
    cfg.vif.tck    <= 1'b0;
    cfg.vif.tms    <= 1'b1;
    cfg.vif.tdi    <= 1'b0;
    cfg.vif.trst_n <= 1'b1;
    forever begin
      seq_item_port.get_next_item(req);
      `uvm_info(get_type_name(), {"drive ", req.convert2string()}, UVM_HIGH)
      case (req.op)
        OCAH_JTAG_TAP_RESET:                 do_tap_reset();
        OCAH_JTAG_IR_SCAN, OCAH_JTAG_DR_SCAN: do_scan(req);
        OCAH_JTAG_RAW_TMS:                   do_raw(req);
        OCAH_JTAG_TRST_LEVEL:                do_trst_level(req);
        default: `uvm_error(get_type_name(),
                    $sformatf("unsupported op %s", req.op.name()))
      endcase
      seq_item_port.item_done();
    end
  endtask

endclass : ocah_jtag_master_driver
