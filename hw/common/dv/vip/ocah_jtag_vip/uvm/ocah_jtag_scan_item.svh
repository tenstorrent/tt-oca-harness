// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reconstructed IR/DR scan record — the SV analogue of the cocotb
// OcahJtagScanItem. Produced by ocah_jtag_scan_builder from the passive
// monitor's per-TCK STEP stream; consumed by checkers/scoreboards (e.g.
// scan-length evidence). Bits are stored LSB-first in shift order with no
// width limit (wide TDRs exceed 64 bits), plus packed 64-bit conveniences
// for narrow scans.

class ocah_jtag_scan_item extends uvm_object;
  `uvm_object_utils(ocah_jtag_scan_item)

  bit          is_ir;              // 1 = IR scan, 0 = DR scan
  bit          tdi_bits[$];        // shifted-in bits, LSB-first
  bit          tdo_bits[$];        // observed TDO bits, LSB-first
  int unsigned bit_count;          // shift-cycle count (== tdi_bits.size())
  bit          instruction_known;  // DR scans: active IR was observed
  bit [63:0]   instruction;        // DR scans: active IR value when known
  time         start_time;         // Capture-x entry
  time         end_time;           // Shift-x -> Exit1-x transition

  function new(string name = "ocah_jtag_scan_item");
    super.new(name);
  endfunction

  // Lowest 64 bits packed LSB-first (narrow-scan convenience).
  function bit [63:0] tdi_value();
    bit [63:0] v = '0;
    foreach (tdi_bits[i]) if (i < 64) v[i] = tdi_bits[i];
    return v;
  endfunction

  function bit [63:0] tdo_value();
    bit [63:0] v = '0;
    foreach (tdo_bits[i]) if (i < 64) v[i] = tdo_bits[i];
    return v;
  endfunction

  function string convert2string();
    return $sformatf(
        "%s_SCAN bits=%0d tdi=0x%0h tdo=0x%0h ir=%s @[%0t,%0t]",
        is_ir ? "IR" : "DR",
        bit_count,
        tdi_value(),
        tdo_value(),
        instruction_known ? $sformatf(
            "0x%0h", instruction
        ) : "-",
        start_time,
        end_time
    );
  endfunction

endclass : ocah_jtag_scan_item
