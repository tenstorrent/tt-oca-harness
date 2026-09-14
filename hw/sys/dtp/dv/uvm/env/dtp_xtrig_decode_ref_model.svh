// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// xtrig_decode reference model: every access to the unmapped cross-trigger
// address space completes with DECERR. Consumes the XTRIG AXI-Lite monitor
// stream (write) and publishes one dtp_expected_item per observed
// transaction so the scoreboard pairs the two streams in lockstep; mapped
// accesses carry no contract. Stateless, no comparison, no reporting. The
// cocotb realization has no twin (DTP_TB_ARCH).

class dtp_xtrig_decode_ref_model extends ocah_ref_model #(ocah_axi_item, dtp_expected_item);
  `uvm_component_utils(dtp_xtrig_decode_ref_model)

  function new(string name = "dtp_xtrig_decode_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void write(ocah_axi_item t);
    bit [31:0]        mask;
    dtp_expected_item exp = dtp_expected_item::type_id::create("exp");
    exp.timestamp = t.end_time;
    exp.compare   = 1'b0;
    if (dtp_xtrig_csr_decode(t.address, mask) == DTP_XTRIG_CSR_UNMAPPED) begin
      exp.compare   = 1'b1;
      exp.mask      = 64'h3;
      exp.expected  = 64'(OCAH_AXI_RESP_DECERR);
      exp.context_s = $sformatf("%s addr=0x%03h", t.direction.name(), t.address);
    end
    expected_ap.write(exp);
  endfunction

endclass : dtp_xtrig_decode_ref_model
