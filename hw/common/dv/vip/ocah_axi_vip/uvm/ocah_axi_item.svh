// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive AXI transaction record, mirroring the cocotb OcahAxiItem fields at
// maximum storage widths (actual bus geometry lives in ocah_axi_config). One
// object represents one completed transaction: a write published at its B
// handshake, or a read published at its RLAST beat.

class ocah_axi_item extends uvm_sequence_item;
    `uvm_object_utils(ocah_axi_item)

    ocah_axi_protocol_e protocol  = OCAH_AXI_PROTO_AXI4_LITE;
    ocah_axi_dir_e      direction = OCAH_AXI_DIR_READ;
    bit [63:0]          address;
    bit [63:0]          data_words[$];       // one entry per beat (raw bus word)
    bit [7:0]           strobes[$];          // write beats only
    int unsigned        size;                // AxSIZE
    ocah_axi_burst_e    burst = OCAH_AXI_BURST_INCR;
    bit [15:0]          transaction_id;
    bit [2:0]           prot;
    ocah_axi_resp_e     resp_list[$];        // per beat (reads) / single (writes)
    int unsigned        expected_beats = 1;  // AxLEN + 1 recorded at the address phase
    bit                 expected_armed;      // expected items: non-OKAY was armed
    time                start_time;
    time                end_time;
    string              source = "";

    function new(string name = "ocah_axi_item");
        super.new(name);
    endfunction

    function ocah_axi_resp_e worst_resp();
        return ocah_axi_worst_resp(resp_list);
    endfunction

    function bit is_ok();
        return ocah_axi_resp_ok(resp_list);
    endfunction

    function int unsigned beat_count();
        if (data_words.size() > 0)
            return data_words.size();
        if (resp_list.size() > 0)
            return resp_list.size();
        return 1;
    endfunction

    function bit [63:0] first_data();
        return (data_words.size() > 0) ? data_words[0] : '0;
    endfunction

    function string convert2string();
        return $sformatf(
            "%s %s addr=0x%0h beats=%0d resp=%s id=0x%0h size=%0d data0=0x%0h",
            protocol.name(), direction.name(), address, beat_count(),
            worst_resp().name(), transaction_id, size, first_data());
    endfunction

    function void do_copy(uvm_object rhs);
        ocah_axi_item rhs_item;
        super.do_copy(rhs);
        if (!$cast(rhs_item, rhs))
            `uvm_fatal(get_type_name(), "do_copy type mismatch")
        protocol       = rhs_item.protocol;
        direction      = rhs_item.direction;
        address        = rhs_item.address;
        data_words     = rhs_item.data_words;
        strobes        = rhs_item.strobes;
        size           = rhs_item.size;
        burst          = rhs_item.burst;
        transaction_id = rhs_item.transaction_id;
        prot           = rhs_item.prot;
        resp_list      = rhs_item.resp_list;
        expected_beats = rhs_item.expected_beats;
        expected_armed = rhs_item.expected_armed;
        start_time     = rhs_item.start_time;
        end_time       = rhs_item.end_time;
        source         = rhs_item.source;
    endfunction

endclass : ocah_axi_item
