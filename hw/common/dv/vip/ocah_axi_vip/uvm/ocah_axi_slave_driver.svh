// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Reactive AXI4/AXI4-Lite memory-backed responder driver (device side).
//
// The class analogue of sv/ocah_axi_ram_responder.sv: a sparse zero-default
// byte memory answering FIXED/INCR/WRAP single- and multi-beat bursts with
// ID echo, per-beat one-shot error matching (via ocah_axi_slave_config), and
// single-outstanding registered handshakes per direction. cfg.protocol
// selects AXI4-Lite (single-beat, no IDs/bursts; the AXI4-only vif fields
// are never sampled).
//
// Wire contract: the driver SAMPLES master-driven signals through mon_cb
// (race-free preponed values, the same view the passive monitor uses) and
// DRIVES the responder-side signals (awready/wready/b*/arready/r*)
// procedurally with NBA — so the TB must wire only the master-driven
// direction into this vif and route the responder-driven signals back to
// the DUT. Reactive: there is deliberately no sequencer; tests configure
// and inspect the device through ocah_axi_slave_sequence.

class ocah_axi_slave_driver extends uvm_component;
    `uvm_component_utils(ocah_axi_slave_driver)

    ocah_axi_slave_config cfg;

    // Sparse backing memory: unwritten bytes read as zero (matching the
    // zero-initialized SV RAM responder).
    protected bit [7:0] m_mem[bit [63:0]];

    // Statistics (completed bursts).
    int unsigned write_bursts;
    int unsigned read_bursts;

    function new(string name = "ocah_axi_slave_driver", uvm_component parent = null);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if (cfg == null &&
            !uvm_config_db#(ocah_axi_slave_config)::get(this, "", "slave_cfg", cfg))
            `uvm_fatal(get_type_name(), "ocah_axi_slave_config `slave_cfg` not found")
        if (cfg.vif == null)
            `uvm_fatal(get_type_name(), "slave cfg.vif is null")
    endfunction

    // ------------------------------------------------------------------
    // Backdoor memory access (test-facing surface is the slave sequence).
    // ------------------------------------------------------------------

    function void mem_write_byte(bit [63:0] addr, bit [7:0] value);
        m_mem[addr % 64'(cfg.mem_bytes)] = value;
    endfunction

    function bit [7:0] mem_read_byte(bit [63:0] addr);
        bit [63:0] wrapped = addr % 64'(cfg.mem_bytes);
        return m_mem.exists(wrapped) ? m_mem[wrapped] : 8'h0;
    endfunction

    function void mem_clear();
        m_mem.delete();
    endfunction

    // ------------------------------------------------------------------
    // Reactive pumps.
    // ------------------------------------------------------------------

    task run_phase(uvm_phase phase);
        if (cfg.is_active != UVM_ACTIVE)
            return;
        drive_idle();
        fork
            write_pump();
            read_pump();
        join_none
    endtask

    protected function void drive_idle();
        cfg.vif.awready <= 1'b0;
        cfg.vif.wready  <= 1'b0;
        cfg.vif.bid     <= '0;
        cfg.vif.bresp   <= '0;
        cfg.vif.buser   <= '0;
        cfg.vif.bvalid  <= 1'b0;
        cfg.vif.arready <= 1'b0;
        cfg.vif.rid     <= '0;
        cfg.vif.rdata   <= '0;
        cfg.vif.rresp   <= '0;
        cfg.vif.rlast   <= 1'b0;
        cfg.vif.ruser   <= '0;
        cfg.vif.rvalid  <= 1'b0;
    endfunction

    // Next beat address for FIXED/INCR/WRAP (IHI 0022 A3.4.1 arithmetic).
    protected function bit [63:0] next_beat_addr(
        bit [63:0] cur,
        bit [63:0] start_addr,
        bit [2:0]  size,
        bit [7:0]  len,
        bit [1:0]  burst
    );
        bit [63:0] nxt, transfer, lower_wrap;
        if (burst == 2'(OCAH_AXI_BURST_FIXED))
            return cur;
        nxt = cur + (64'h1 << size);
        if (burst == 2'(OCAH_AXI_BURST_WRAP)) begin
            transfer   = (64'(len) + 64'h1) << size;
            lower_wrap = (start_addr / transfer) * transfer;
            if (nxt == lower_wrap + transfer)
                nxt = lower_wrap;
        end
        return nxt;
    endfunction

    // Bounded READY stall: wait cfg.ready_stall_cycles edges before the
    // caller asserts READY (0 = assert immediately).
    protected task ready_stall();
        repeat (cfg.ready_stall_cycles) @(cfg.vif.mon_cb);
    endtask

    protected task write_pump();
        bit [63:0]      addr, start_addr;
        bit [15:0]      id;
        bit [7:0]       len;
        bit [2:0]       size;
        bit [1:0]       burst;
        ocah_axi_resp_e resp, beat_resp;
        bit             armed;
        int unsigned    beats, lanes;
        forever begin
            @(cfg.vif.mon_cb);
            if (!cfg.vif.aresetn) begin
                cfg.vif.awready <= 1'b0;
                cfg.vif.wready  <= 1'b0;
                cfg.vif.bvalid  <= 1'b0;
                continue;
            end
            // Address phase.
            ready_stall();
            cfg.vif.awready <= 1'b1;
            do @(cfg.vif.mon_cb); while (cfg.vif.aresetn &&
                !(cfg.vif.mon_cb.awvalid && cfg.vif.mon_cb.awready));
            cfg.vif.awready <= 1'b0;
            if (!cfg.vif.aresetn) continue;
            id    = cfg.vif.mon_cb.awid;
            size  = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 3'($clog2(cfg.beat_bytes())) : cfg.vif.mon_cb.awsize;
            len   = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 8'h0 : cfg.vif.mon_cb.awlen;
            burst = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 2'(OCAH_AXI_BURST_INCR) : cfg.vif.mon_cb.awburst;
            start_addr = cfg.vif.mon_cb.awaddr;
            addr  = (start_addr >> size) << size;
            beats = int'(len) + 1;
            resp  = OCAH_AXI_RESP_OKAY;
            // Data phase.
            cfg.vif.wready <= 1'b1;
            for (int unsigned beat = 0; beat < beats; beat++) begin
                do @(cfg.vif.mon_cb); while (cfg.vif.aresetn &&
                    !(cfg.vif.mon_cb.wvalid && cfg.vif.mon_cb.wready));
                if (!cfg.vif.aresetn) break;
                beat_resp = cfg.consume_injected(addr, OCAH_AXI_DIR_WRITE, armed);
                if (armed) begin
                    if (beat_resp > resp)
                        resp = beat_resp;
                end else begin
                    lanes = cfg.beat_bytes();
                    for (int unsigned lane = 0; lane < lanes; lane++) begin
                        if (cfg.vif.mon_cb.wstrb[lane])
                            mem_write_byte(cfg.beat_align(addr) + 64'(lane),
                                           cfg.vif.mon_cb.wdata[8*lane +: 8]);
                    end
                end
                if (cfg.protocol == OCAH_AXI_PROTO_AXI4 &&
                    bit'(cfg.vif.mon_cb.wlast) != (beat == beats - 1))
                    `uvm_error(get_type_name(), $sformatf(
                        "%s: WLAST=%0d at beat %0d/%0d",
                        cfg.name_tag, cfg.vif.mon_cb.wlast, beat + 1, beats))
                addr = next_beat_addr(addr, start_addr, size, len, burst);
            end
            cfg.vif.wready <= 1'b0;
            if (!cfg.vif.aresetn) continue;
            // Response phase.
            cfg.vif.bid    <= id;
            cfg.vif.bresp  <= resp;
            cfg.vif.bvalid <= 1'b1;
            do @(cfg.vif.mon_cb); while (cfg.vif.aresetn &&
                !(cfg.vif.mon_cb.bvalid && cfg.vif.mon_cb.bready));
            cfg.vif.bvalid <= 1'b0;
            if (!cfg.vif.aresetn) continue;
            write_bursts++;
        end
    endtask

    protected task read_pump();
        bit [63:0]      addr, start_addr;
        bit [15:0]      id;
        bit [7:0]       len;
        bit [2:0]       size;
        bit [1:0]       burst;
        int unsigned    beats;
        forever begin
            @(cfg.vif.mon_cb);
            if (!cfg.vif.aresetn) begin
                cfg.vif.arready <= 1'b0;
                cfg.vif.rvalid  <= 1'b0;
                continue;
            end
            // Address phase.
            ready_stall();
            cfg.vif.arready <= 1'b1;
            do @(cfg.vif.mon_cb); while (cfg.vif.aresetn &&
                !(cfg.vif.mon_cb.arvalid && cfg.vif.mon_cb.arready));
            cfg.vif.arready <= 1'b0;
            if (!cfg.vif.aresetn) continue;
            id    = cfg.vif.mon_cb.arid;
            size  = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 3'($clog2(cfg.beat_bytes())) : cfg.vif.mon_cb.arsize;
            len   = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 8'h0 : cfg.vif.mon_cb.arlen;
            burst = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                    ? 2'(OCAH_AXI_BURST_INCR) : cfg.vif.mon_cb.arburst;
            start_addr = cfg.vif.mon_cb.araddr;
            addr  = (start_addr >> size) << size;
            beats = int'(len) + 1;
            // Data phase: one beat per accepted cycle.
            for (int unsigned beat = 0; beat < beats; beat++) begin
                load_read_beat(addr, id, beat == beats - 1);
                cfg.vif.rvalid <= 1'b1;
                do @(cfg.vif.mon_cb); while (cfg.vif.aresetn &&
                    !(cfg.vif.mon_cb.rvalid && cfg.vif.mon_cb.rready));
                if (!cfg.vif.aresetn) break;
                addr = next_beat_addr(addr, start_addr, size, len, burst);
            end
            cfg.vif.rvalid <= 1'b0;
            if (!cfg.vif.aresetn) continue;
            read_bursts++;
        end
    endtask

    protected function void load_read_beat(bit [63:0] addr, bit [15:0] id, bit last);
        ocah_axi_resp_e resp;
        bit             armed;
        bit [63:0]      data;
        resp = cfg.consume_injected(addr, OCAH_AXI_DIR_READ, armed);
        data = '0;
        if (!armed) begin
            for (int unsigned lane = 0; lane < cfg.beat_bytes(); lane++)
                data[8*lane +: 8] = mem_read_byte(cfg.beat_align(addr) + 64'(lane));
        end
        cfg.vif.rid   <= id;
        cfg.vif.rdata <= data;
        cfg.vif.rresp <= armed ? resp : OCAH_AXI_RESP_OKAY;
        cfg.vif.rlast <= last;
    endfunction

endclass : ocah_axi_slave_driver
