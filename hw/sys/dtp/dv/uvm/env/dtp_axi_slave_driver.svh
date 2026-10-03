// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI responder driver: the shared memory-backed responder with one more
// write order. An armed w_before_aw makes the next write raise WREADY together
// with its first AWREADY window, so a bridge that presents AW and W as a pair
// has its W beat accepted while AW waits against a stalled AWREADY (a
// subordinate may accept write data before the address, IHI 0022 A3.3.1).
// The cocotb RAM responder accepts W independently of AW, so this is the
// order an AW-only stall gives there. Reads, responses, error injection and
// the memory are the shared driver's.

class dtp_axi_slave_driver extends ocah_axi_slave_driver;
  `uvm_component_utils(dtp_axi_slave_driver)

  // One-shot: the next write's first W beat is accepted without waiting for
  // its AW, and the driver clears the flag when that write starts. Arm it
  // while the target's write channels are idle.
  bit w_before_aw;

  function new(string name = "dtp_axi_slave_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  task run_phase(uvm_phase phase);
    if (cfg.is_active != UVM_ACTIVE) return;
    drive_idle();
    fork
      dtp_write_pump();
      read_pump();
    join_none
  endtask

  // The shared write pump, with the address and first data handshakes taken
  // concurrently for a write that w_before_aw was armed for. Arming it while
  // the pump waits for an AW takes effect for that AW. The first beat's W
  // fields are held from its own handshake edge.
  protected task dtp_write_pump();
    bit [63:0] addr, start_addr;
    bit [15:0] id, bid_out, corrupt_mask;
    bit [7:0] len;
    bit [2:0] size;
    bit [1:0] burst;
    ocah_axi_resp_e resp, beat_resp;
    bit armed, w_early, aw_taken;
    bit [63:0] wdata_q;
    bit [7:0] wstrb_q;
    bit wlast_q;
    int unsigned beats, lanes;
    forever begin
      @(cfg.vif.mon_cb);
      if (!cfg.vif.aresetn) begin
        cfg.vif.awready <= 1'b0;
        cfg.vif.wready  <= 1'b0;
        cfg.vif.bvalid  <= 1'b0;
        continue;
      end
      // Address phase, with the first data beat alongside it when the early
      // W order is armed.
      w_early = w_before_aw;
      if (!w_early) begin
        aw_taken = 1'b0;
        fork
          begin
            accept_aw();
            take_aw(id, size, len, burst, start_addr);
            aw_taken = 1'b1;
          end
          wait (w_before_aw);
        join_any
        disable fork;
        w_early = !aw_taken;
        if (w_early) cfg.vif.awready <= 1'b0;
      end
      if (w_early) begin
        w_before_aw = 1'b0;
        fork
          begin
            accept_aw();
            take_aw(id, size, len, burst, start_addr);
          end
          begin
            accept_w();
            cfg.vif.wready <= 1'b0;
            wdata_q = cfg.vif.mon_cb.wdata;
            wstrb_q = cfg.vif.mon_cb.wstrb;
            wlast_q = cfg.vif.mon_cb.wlast;
          end
        join
      end
      if (!cfg.vif.aresetn) continue;
      addr  = (start_addr >> size) << size;
      beats = int'(len) + 1;
      resp  = OCAH_AXI_RESP_OKAY;
      // Data phase.
      for (int unsigned beat = 0; beat < beats; beat++) begin
        if (!(w_early && beat == 0)) begin
          accept_w();
          if (!cfg.vif.aresetn) break;
          wdata_q = cfg.vif.mon_cb.wdata;
          wstrb_q = cfg.vif.mon_cb.wstrb;
          wlast_q = cfg.vif.mon_cb.wlast;
        end
        beat_resp = cfg.consume_injected(addr, OCAH_AXI_DIR_WRITE, armed);
        if (armed) begin
          if (beat_resp > resp) resp = beat_resp;
        end else begin
          lanes = cfg.beat_bytes();
          for (int unsigned lane = 0; lane < lanes; lane++) begin
            if (wstrb_q[lane]) mem_write_byte(cfg.beat_align(addr) + 64'(lane), wdata_q[8*lane+:8]);
          end
        end
        if (cfg.protocol == OCAH_AXI_PROTO_AXI4 && wlast_q != (beat == beats - 1))
          `uvm_error(get_type_name(), $sformatf(
                     "%s: WLAST=%0d at beat %0d/%0d", cfg.name_tag, wlast_q, beat + 1, beats))
        addr = next_beat_addr(addr, start_addr, size, len, burst);
      end
      cfg.vif.wready <= 1'b0;
      if (!cfg.vif.aresetn) continue;
      // Response phase. One-shot armed BID corruption answers a wrong
      // response ID (data path and BRESP stay untouched).
      bid_out = id;
      if (cfg.consume_id_corruption(OCAH_AXI_DIR_WRITE, corrupt_mask)) begin
        bid_out = cfg.mask_id(id ^ corrupt_mask);
        `uvm_info(get_type_name(), $sformatf(
                                       "%s: corrupting BID awid=0x%0h -> bid=0x%0h (mask=0x%0h)",
                                       cfg.name_tag, id, bid_out, corrupt_mask), UVM_LOW)
      end
      cfg.vif.bid    <= bid_out;
      cfg.vif.bresp  <= resp;
      cfg.vif.bvalid <= 1'b1;
      do
      @(cfg.vif.mon_cb);
      while (cfg.vif.aresetn && !(cfg.vif.mon_cb.bvalid && cfg.vif.mon_cb.bready));
      cfg.vif.bvalid <= 1'b0;
      if (!cfg.vif.aresetn) continue;
      write_bursts++;
    end
  endtask

  // The AW fields of the handshake on this edge.
  protected function void take_aw(output bit [15:0] id, output bit [2:0] size, output bit [7:0] len,
                                  output bit [1:0] burst, output bit [63:0] start_addr);
    id    = cfg.vif.mon_cb.awid;
    size  = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 3'($clog2(cfg.beat_bytes())) : cfg.vif.mon_cb.awsize;
    len   = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 8'h0 : cfg.vif.mon_cb.awlen;
    burst = (cfg.protocol == OCAH_AXI_PROTO_AXI4_LITE)
                  ? 2'(OCAH_AXI_BURST_INCR) : cfg.vif.mon_cb.awburst;
    start_addr = cfg.vif.mon_cb.awaddr;
  endfunction

endclass : dtp_axi_slave_driver
