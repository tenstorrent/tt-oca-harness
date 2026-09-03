// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reusable AXI-Lite operation: one single-beat CSR write on the XTRIG
// master agent, returning the VIP result item (response, timing, timeout).
// Channel skew (AWVALID, WVALID, BREADY delays) selects the VIP's skewed
// write; zero skew is the plain write. Response checking stays with the
// caller (check_response = 0), so error-path scenarios judge the response
// themselves. Started by dtp_xtrig_base_test_seq::csr_write() and
// csr_write_skewed(). The cocotb twin is seq_lib/dtp_axi_csr_write_seq.py.

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
    // Result item (response list, timed_out, timing).
    ocah_axi_item result;

    function new(string name = "dtp_axi_csr_write_seq");
        super.new(name);
    endfunction

    task body();
        if (aw_valid_delay == 0 && w_valid_delay == 0 && b_ready_delay == 0)
            write_result(addr, 64'(data), result, .strb(8'(wstrb)),
                         .check_response(check_response), .allow_timeout(allow_timeout));
        else
            write_skewed_result(addr, 64'(data), result, aw_valid_delay, w_valid_delay,
                                b_ready_delay, .strb(8'(wstrb)),
                                .check_response(check_response), .allow_timeout(allow_timeout));
    endtask

endclass : dtp_axi_csr_write_seq
