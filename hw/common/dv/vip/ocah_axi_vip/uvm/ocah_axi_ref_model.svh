// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Stateful AXI reference model: sparse strobe-masked shadow memory plus the
// cfg-owned expected-response policy. Subscribes to the monitor's observed
// item stream and republishes an EXPECTED item per transaction on expected_ap
// (same completion order, so the scoreboard pairs in order).
//
// Update order (mirrors the cocotb OcahAxiRefModel contract): the expected
// response is resolved first (consuming a one-shot arming if present); memory
// commits only for expected-OKAY writes, so an armed-error write leaves the
// shadow memory untouched exactly like the error-injecting responder.

class ocah_axi_ref_model extends uvm_subscriber #(ocah_axi_item);
  `uvm_component_utils(ocah_axi_ref_model)

  ocah_axi_config cfg;
  uvm_analysis_port #(ocah_axi_item) expected_ap;

  protected bit [7:0] m_mem[bit [63:0]];

  function new(string name = "ocah_axi_ref_model", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_config `cfg` not found in uvm_config_db")
    expected_ap = new("expected_ap", this);
  endfunction

  // Backdoor preload mirror (keeps the shadow equal to responder preloads).
  function void backdoor_write(bit [63:0] addr, bit [7:0] data[]);
    foreach (data[i]) m_mem[addr+i] = data[i];
  endfunction

  function bit [63:0] read_word(bit [63:0] addr);
    bit [63:0] word = '0;
    for (int unsigned lane = 0; lane < cfg.beat_bytes(); lane++) begin
      if (m_mem.exists(addr + lane)) word[8*lane+:8] = m_mem[addr+lane];
    end
    return word;
  endfunction

  function void reset_model();
    m_mem.delete();
  endfunction

  // Word address of each beat (FIXED re-addresses; INCR advances by 2**size;
  // WRAP wraps at the transfer boundary), aligned to the bus beat.
  protected function void beat_addresses(input ocah_axi_item t, ref bit [63:0] addrs[$]);
    int unsigned num_bytes = (t.protocol == OCAH_AXI_PROTO_AXI4)
                                 ? (1 << t.size) : cfg.beat_bytes();
    bit [63:0] aligned = (t.address / num_bytes) * num_bytes;
    bit [63:0] transfer = num_bytes * t.beat_count();
    bit [63:0] lower_wrap = (transfer > 0) ? (t.address / transfer) * transfer : aligned;
    bit [63:0] cur = aligned;
    addrs.delete();
    repeat (t.beat_count()) begin
      addrs.push_back(cfg.beat_align(cur));
      if (t.burst != OCAH_AXI_BURST_FIXED) begin
        cur += num_bytes;
        if (t.burst == OCAH_AXI_BURST_WRAP && cur == lower_wrap + transfer) cur = lower_wrap;
      end
    end
  endfunction

  function void write(ocah_axi_item t);
    ocah_axi_item expected = ocah_axi_item::type_id::create("expected_item");
    bit [63:0] addrs[$];
    ocah_axi_resp_e beat_resps[$];
    bit any_armed = 1'b0;

    expected.protocol       = t.protocol;
    expected.direction      = t.direction;
    expected.address        = t.address;
    expected.size           = t.size;
    expected.burst          = t.burst;
    expected.transaction_id = t.transaction_id;
    expected.expected_beats = t.expected_beats;
    expected.source         = get_full_name();

    beat_addresses(t, addrs);
    foreach (addrs[i]) begin
      bit armed;
      ocah_axi_resp_e resp = cfg.consume_expected_resp(
                addrs[i],
                t.direction,
                armed);
      if (!armed) resp = OCAH_AXI_RESP_OKAY;
      beat_resps.push_back(resp);
      any_armed |= armed;

      if (t.direction == OCAH_AXI_DIR_WRITE) begin
        // Commit strobed bytes only on expected-OKAY beats.
        if (resp == OCAH_AXI_RESP_OKAY && i < t.data_words.size()) begin
          bit [7:0] strb = (i < t.strobes.size()) ? t.strobes[i]
                                     : (8'hFF >> (8 - cfg.beat_bytes()));
          for (int unsigned lane = 0; lane < cfg.beat_bytes(); lane++) begin
            if (strb[lane]) m_mem[addrs[i]+lane] = t.data_words[i][8*lane+:8];
          end
        end
      end else begin
        // Expected readback: shadow word on OKAY, zero on error beats.
        expected.data_words.push_back((resp == OCAH_AXI_RESP_OKAY) ? read_word(addrs[i]) : '0);
      end
    end

    // Writes carry a single response (worst across beats).
    if (t.direction == OCAH_AXI_DIR_WRITE)
      expected.resp_list.push_back(ocah_axi_worst_resp(beat_resps));
    else expected.resp_list = beat_resps;
    expected.expected_armed = any_armed;
    expected_ap.write(expected);
  endfunction

endclass : ocah_axi_ref_model
