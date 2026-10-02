// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// xtrig_decode reference model: every access to the cross-trigger CSR port
// completes with the response the network memory map gives its word
// (dtp_xtrig_csr_decode): DECERR for an unmapped word, OKAY for a register or
// a hole. Consumes the XTRIG AXI-Lite monitor stream (write) and publishes
// one dtp_expected_item per observed transaction so the scoreboard pairs the
// two streams in lockstep. Stateless, no comparison, no reporting. The cocotb
// twin is env/dtp_xtrig_decode_ref_model.py.

class dtp_xtrig_decode_ref_model extends ocah_ref_model #(ocah_axi_item, dtp_expected_item);
  `uvm_component_utils(dtp_xtrig_decode_ref_model)

  function new(string name = "dtp_xtrig_decode_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void write(ocah_axi_item t);
    bit [31:0]           mask;
    dtp_xtrig_csr_kind_e kind;
    dtp_expected_item    exp = dtp_expected_item::type_id::create("exp");
    kind          = dtp_xtrig_csr_decode(t.address, mask);
    exp.timestamp = t.end_time;
    exp.compare   = 1'b1;
    exp.mask      = 64'h3;
    exp.expected  = 64'((kind == DTP_XTRIG_CSR_UNMAPPED) ? OCAH_AXI_RESP_DECERR : OCAH_AXI_RESP_OKAY);
    exp.context_s = $sformatf("%s %s addr=0x%03h", t.direction.name(), kind.name(), t.address);
    expected_ap.write(exp);
  endfunction

endclass : dtp_xtrig_decode_ref_model
