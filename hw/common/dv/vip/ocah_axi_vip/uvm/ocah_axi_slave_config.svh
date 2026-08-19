// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Configuration for one active ocah_axi_vip slave (memory-backed responder).
//
// Owns the responder-side one-shot error-injection tables (the SV-UVM
// analogue of the cocotb OcahFaultMixin): a beat-aligned address armed for a
// direction answers the programmed non-OKAY response ONCE, skips the memory
// update (writes), and returns zero data (reads). This table makes the
// responder MISBEHAVE on purpose; the separate passive ocah_axi_config
// arm_expected_resp table is what classifies the observed non-OKAY as
// EXPECTED for the scoreboard — tests arm both through their sequence layer.

class ocah_axi_slave_config extends uvm_object;
    `uvm_object_utils(ocah_axi_slave_config)

    // The responder drives its outputs on this interface procedurally; the
    // TB wires only the master-driven signals into it and routes the
    // responder-driven signals back to the DUT (see the DTP tb_top adoption).
    virtual ocah_axi_if vif;

    ocah_axi_protocol_e protocol   = OCAH_AXI_PROTO_AXI4_LITE;
    int unsigned        addr_width = 32;
    int unsigned        data_width = 32;
    int unsigned        id_width   = 0;

    uvm_active_passive_enum is_active = UVM_ACTIVE;

    // Backing memory footprint in bytes (power of two; addresses wrap).
    int unsigned mem_bytes = 65536;

    // Bounded READY backpressure: when nonzero, READY idles low for this many
    // accepted-clock cycles before each assertion window (never a permanent
    // stall — mirrors the cocotb bounded pause generator).
    int unsigned ready_stall_cycles = 0;

    // Stable name for log messages.
    string name_tag = "ocah_axi_slave";

    // One-shot injected-error tables, keyed by beat-aligned address.
    protected ocah_axi_resp_e m_inject_rd[bit [63:0]];
    protected ocah_axi_resp_e m_inject_wr[bit [63:0]];

    function new(string name = "ocah_axi_slave_config");
        super.new(name);
    endfunction

    function int unsigned beat_bytes();
        return data_width / 8;
    endfunction

    // Beat-align, then wrap into the memory footprint (mem_bytes is a power
    // of two, matching the SV RAM responder's address masking).
    function bit [63:0] beat_align(bit [63:0] addr);
        return ((addr / 64'(beat_bytes())) * 64'(beat_bytes())) % 64'(mem_bytes);
    endfunction

    // Program a one-shot non-OKAY response at a beat-aligned address.
    function void inject_error(
        bit [63:0]      addr,
        ocah_axi_resp_e resp,
        bit             for_read  = 1'b1,
        bit             for_write = 1'b1
    );
        bit [63:0] aligned = beat_align(addr);
        if (for_read)
            m_inject_rd[aligned] = resp;
        if (for_write)
            m_inject_wr[aligned] = resp;
        `uvm_info(get_type_name(), $sformatf(
            "%s: injecting error addr=0x%0h (aligned 0x%0h) resp=%s read=%0d write=%0d",
            name_tag, addr, aligned, resp.name(), for_read, for_write), UVM_LOW)
    endfunction

    function void clear_errors();
        m_inject_rd.delete();
        m_inject_wr.delete();
    endfunction

    function int unsigned pending_errors();
        return m_inject_rd.size() + m_inject_wr.size();
    endfunction

    // Consume the one-shot injection for one beat address, if armed.
    function ocah_axi_resp_e consume_injected(
        bit [63:0]     addr,
        ocah_axi_dir_e dir,
        output bit     armed
    );
        bit [63:0] aligned = beat_align(addr);
        ocah_axi_resp_e resp = OCAH_AXI_RESP_OKAY;
        armed = 1'b0;
        if (dir == OCAH_AXI_DIR_READ && m_inject_rd.exists(aligned)) begin
            resp  = m_inject_rd[aligned];
            armed = 1'b1;
            m_inject_rd.delete(aligned);
        end else if (dir == OCAH_AXI_DIR_WRITE && m_inject_wr.exists(aligned)) begin
            resp  = m_inject_wr[aligned];
            armed = 1'b1;
            m_inject_wr.delete(aligned);
        end
        return resp;
    endfunction

endclass : ocah_axi_slave_config
