// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Slave-side test-facing API: configure and inspect the reactive responder.
//
// The responder is reactive (no sequencer), so this is a uvm_object holding
// the driver handle rather than a uvm_sequence: tests and DUT sequence
// layers backdoor the memory, program one-shot error injection, and read
// statistics ONLY through this class (basename parity with the cocotb
// ocah_axi_slave_sequence.py surface) — never through the raw driver.

class ocah_axi_slave_sequence extends uvm_object;
  `uvm_object_utils(ocah_axi_slave_sequence)

  ocah_axi_slave_driver responder;

  function new(string name = "ocah_axi_slave_sequence");
    super.new(name);
  endfunction

  protected function void check_bound();
    if (responder == null) `uvm_fatal(get_type_name(), "slave sequence has no responder bound")
  endfunction

  // ------------------------------------------------------------------
  // Backdoor memory access.
  // ------------------------------------------------------------------

  function void write_bytes(bit [63:0] addr, bit [7:0] data[$]);
    check_bound();
    foreach (data[i]) responder.mem_write_byte(addr + 64'(i), data[i]);
  endfunction

  function void read_bytes(bit [63:0] addr, int unsigned len, ref bit [7:0] data[$]);
    check_bound();
    data.delete();
    for (int unsigned i = 0; i < len; i++) data.push_back(responder.mem_read_byte(addr + 64'(i)));
  endfunction

  function void write_int(bit [63:0] addr, bit [63:0] value, int unsigned nbytes);
    check_bound();
    for (int unsigned i = 0; i < nbytes; i++)
    responder.mem_write_byte(addr + 64'(i), value[8*i+:8]);
  endfunction

  function bit [63:0] read_int(bit [63:0] addr, int unsigned nbytes);
    bit [63:0] value = '0;
    check_bound();
    for (int unsigned i = 0; i < nbytes; i++)
    value[8*i+:8] = responder.mem_read_byte(addr + 64'(i));
    return value;
  endfunction

  function void write32(bit [63:0] addr, bit [31:0] value);
    write_int(addr, 64'(value), 4);
  endfunction

  function bit [31:0] read32(bit [63:0] addr);
    bit [63:0] value = read_int(addr, 4);
    return value[31:0];
  endfunction

  function void write64(bit [63:0] addr, bit [63:0] value);
    write_int(addr, value, 8);
  endfunction

  function bit [63:0] read64(bit [63:0] addr);
    return read_int(addr, 8);
  endfunction

  function void clear_memory();
    check_bound();
    responder.mem_clear();
  endfunction

  // ------------------------------------------------------------------
  // Deterministic fault controls (one-shot, beat-aligned).
  // ------------------------------------------------------------------

  function void inject_error(bit [63:0] addr, ocah_axi_resp_e resp, bit for_read = 1'b1,
                             bit for_write = 1'b1);
    check_bound();
    responder.cfg.inject_error(addr, resp, for_read, for_write);
  endfunction

  // Arm one-shot response-ID corruption: the next selected transaction
  // answers BID/RID = request_id ^ mask (ID-width truncated; data path and
  // response code untouched). clear_errors() disarms.
  function void inject_id_corruption(bit [15:0] mask, bit for_read = 1'b1, bit for_write = 1'b1);
    check_bound();
    responder.cfg.inject_id_corruption(mask, for_read, for_write);
  endfunction

  // Arm a one-shot missing RLAST: the next read whose AR address aligns at
  // addr answers its final beat with RLAST low and sends no further beat.
  function void inject_missing_rlast(bit [63:0] addr);
    check_bound();
    responder.cfg.inject_missing_rlast(addr);
  endfunction

  function void clear_errors();
    check_bound();
    responder.cfg.clear_errors();
  endfunction

  function int unsigned pending_errors();
    check_bound();
    return responder.cfg.pending_errors();
  endfunction

  // ------------------------------------------------------------------
  // Bounded READY backpressure (cocotb enable_backpressure parity):
  // READY low for stall_cycles then high for one cycle, repeating, on
  // each selected channel ("aw"/"w"/"ar") until disabled.
  // ------------------------------------------------------------------

  function void enable_backpressure(string channels[$], int unsigned stall_cycles);
    check_bound();
    responder.cfg.enable_backpressure(channels, stall_cycles);
  endfunction

  function void disable_backpressure();
    check_bound();
    responder.cfg.disable_backpressure();
  endfunction

  // ------------------------------------------------------------------
  // Statistics.
  // ------------------------------------------------------------------

  function int unsigned write_burst_count();
    check_bound();
    return responder.write_bursts;
  endfunction

  function int unsigned read_burst_count();
    check_bound();
    return responder.read_bursts;
  endfunction

endclass : ocah_axi_slave_sequence
