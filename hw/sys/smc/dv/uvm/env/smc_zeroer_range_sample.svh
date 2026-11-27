// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 VNCHIP LABS
//
// One command's declared, predicted or observed byte window, keyed across resets.
class smc_zeroer_range_sample extends uvm_object;
  `uvm_object_utils(smc_zeroer_range_sample)
  bit [63:0] epoch;
  int unsigned command_id, size, phase_index, guard_bytes;
  bit [63:0] destination;
  bit [7:0] bytes_by_addr[bit [63:0]];
  bit response_error;
  int unsigned shape_errors, outside_bytes;
  string detail;
  bit closing, close_valid = 1;
  function new(string name = "smc_zeroer_range_sample");
    super.new(name);
  endfunction
  virtual function string convert2string();
    return $sformatf(
        "key=%s dest=%016h size=%0d bytes=%0d err=%0b shape=%0d outside=%0d %s",
        key(),
        destination,
        size,
        bytes_by_addr.num(),
        response_error,
        shape_errors,
        outside_bytes,
        detail
    );
  endfunction
  virtual function void do_copy(uvm_object rhs);
    smc_zeroer_range_sample other;
    super.do_copy(rhs);
    if (!$cast(other, rhs)) `uvm_fatal(get_type_name(), "copy requires a Zeroer range sample")
    epoch = other.epoch;
    command_id = other.command_id;
    size = other.size;
    phase_index = other.phase_index;
    guard_bytes = other.guard_bytes;
    destination = other.destination;
    bytes_by_addr = other.bytes_by_addr;
    response_error = other.response_error;
    shape_errors = other.shape_errors;
    outside_bytes = other.outside_bytes;
    detail = other.detail;
    closing = other.closing;
    close_valid = other.close_valid;
  endfunction
  function string key();
    return $sformatf("%0d:%0d", epoch, command_id);
  endfunction
endclass : smc_zeroer_range_sample
