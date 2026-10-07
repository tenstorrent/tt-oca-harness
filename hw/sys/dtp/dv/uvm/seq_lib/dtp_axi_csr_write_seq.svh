// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable AXI-Lite operation: one single-beat CSR write on the XTRIG
// master agent, returning the VIP result item (response, timing, timeout).
// Channel skew (AWVALID, WVALID, BREADY delays) selects the VIP's skewed
// write; zero skew is the plain write. With `pair` set, a second write to
// pair_addr launches behind the first before either response is accepted
// (the VIP's two-outstanding write), and pair_result carries its item.
// With the default check_response = 1 the VIP reports a non-OKAY response
// as an error; the error-path scenarios clear it and judge the response
// themselves. Started by dtp_xtrig_base_test_seq::csr_write(),
// write_skewed_result(), and write_pair_skewed(). In the cocotb
// realization, seq_lib/dtp_xtrig_base_test_seq.py calls the VIP master
// sequence's write and seq_lib/dtp_xtrig_csr_test_seq.py its
// write_skewed_result and write_pair_skewed_result.

class dtp_axi_csr_write_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(dtp_axi_csr_write_seq)

  bit [63:0]   addr;
  bit [31:0]   data;
  bit [3:0]    wstrb = 4'hF;
  int unsigned aw_valid_delay = 0;
  int unsigned w_valid_delay  = 0;
  int unsigned b_ready_delay  = 0;
  bit          check_response = 1'b1;
  bit          allow_timeout  = 1'b0;
  bit          pair = 1'b0;
  bit [63:0]   pair_addr;
  bit [31:0]   pair_data;
  bit [3:0]    pair_wstrb = 4'hF;
  // Result items (response list, timed_out, timing); pair_result is the
  // second write of a pair.
  ocah_axi_item result;
  ocah_axi_item pair_result;

  function new(string name = "dtp_axi_csr_write_seq");
    super.new(name);
  endfunction

  task body();
    if (pair)
      write_pair_skewed_result(addr, 64'(data), pair_addr, 64'(pair_data), result, pair_result,
                               aw_valid_delay, w_valid_delay, b_ready_delay, .strb_a(8'(wstrb)),
                               .strb_b(8'(pair_wstrb)), .check_response(check_response),
                               .allow_timeout(allow_timeout));
    else if (aw_valid_delay == 0 && w_valid_delay == 0 && b_ready_delay == 0)
      write_result(addr, 64'(data), result, .strb(8'(wstrb)), .check_response(check_response),
                   .allow_timeout(allow_timeout));
    else
      write_skewed_result(addr, 64'(data), result, aw_valid_delay, w_valid_delay, b_ready_delay,
                          .strb(8'(wstrb)), .check_response(check_response),
                          .allow_timeout(allow_timeout));
  endtask

endclass : dtp_axi_csr_write_seq
