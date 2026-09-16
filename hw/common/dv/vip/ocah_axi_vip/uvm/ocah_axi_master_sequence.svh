// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// VIP-level base sequence: the reusable AXI stimulus API over ocah_axi_item
// (basename and operation parity with the cocotb ocah_axi_master_sequence.py
// surface). Tests and DUT sequence libraries extend this class and drive the
// master ONLY through these operations — missing operations get added here
// first, never open-coded in a test.
//
// Every blocking operation returns the completed ocah_axi_item as the result
// object (the SV analogue of OcahAxiWriteResult/OcahAxiReadResult): the
// driver fills resp_list, read data_words, timed_out, and the live-sampled
// observed_id before finish_item() returns. `check_response` escalates a
// non-OKAY response to uvm_error (the OcahAxiMasterError mirror);
// `allow_timeout` downgrades a handshake watchdog expiry from uvm_error to
// a result with timed_out set.
//
// Geometry defaults (full-beat size/strobes) come from the agent's
// ocah_axi_master_config, resolved from the sequencer scope on first use.
// Sub-beat transfers take explicit size/strb, with data positioned at the
// addressed lanes (raw-bus-word item semantics).

class ocah_axi_master_sequence extends uvm_sequence #(ocah_axi_item);
  `uvm_object_utils(ocah_axi_master_sequence)

  // Resolved lazily from the sequencer scope; a DUT layer may also assign
  // it directly before start().
  ocah_axi_master_config cfg;

  // Statistics (parity with the cocotb wrapper counters).
  int unsigned write_transactions;
  int unsigned read_transactions;

  function new(string name = "ocah_axi_master_sequence");
    super.new(name);
  endfunction

  task do_axi(ocah_axi_item it);
    start_item(it);
    finish_item(it);
  endtask

  protected function ocah_axi_master_config resolve_cfg();
    if (cfg == null) begin
      if (m_sequencer == null || !uvm_config_db#(ocah_axi_master_config)::get(
              m_sequencer, "", "cfg", cfg
          ) || cfg == null)
        `uvm_fatal(get_type_name(),
                   "ocah_axi_master_config `cfg` not resolvable from the sequencer scope")
    end
    return cfg;
  endfunction

  // Full-beat AxSIZE unless the caller passed an explicit size (>= 0).
  protected function int unsigned resolve_size(int size);
    return (size < 0) ? $clog2(resolve_cfg().beat_bytes()) : unsigned'(size);
  endfunction

  // Strobes are lane-masked to the bus geometry (the 8'hFF default becomes
  // the full-beat mask on narrower buses).
  protected function bit [7:0] resolve_strb(bit [7:0] strb);
    return strb & resolve_cfg().full_strb();
  endfunction

  // Timeout/response escalation shared by every blocking operation.
  protected function void enforce_result(ocah_axi_item it, string verb, bit check_response,
                                         bit allow_timeout);
    if (it.timed_out) begin
      if (!allow_timeout)
        `uvm_error(get_type_name(), $sformatf(
                   "%s 0x%0h timed out: %s", verb, it.address, it.convert2string()))
      return;
    end
    if (check_response && !it.is_ok())
      `uvm_error(get_type_name(), $sformatf(
                 "%s 0x%0h returned response=%s", verb, it.address, it.worst_resp().name()))
  endfunction

  // ------------------------------------------------------------------
  // Blocking checked transactions.
  // ------------------------------------------------------------------

  // Single-beat write; `result` is the completed item (response, timeout,
  // issued transaction_id, live-sampled observed_id).
  task write_result(input bit [63:0] addr, input bit [63:0] data, output ocah_axi_item result,
                    input bit [15:0] id = '0, input bit [7:0] strb = 8'hFF, input int size = -1,
                    input ocah_axi_burst_e burst = OCAH_AXI_BURST_INCR, input bit [2:0] prot = '0,
                    input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("write");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_WRITE;
    it.address        = addr;
    it.data_words.push_back(data);
    it.strobes.push_back(resolve_strb(strb));
    it.size           = resolve_size(size);
    it.burst          = burst;
    it.transaction_id = id;
    it.prot           = prot;
    it.expected_beats = 1;
    do_axi(it);
    write_transactions++;
    enforce_result(it, "write to", check_response, allow_timeout);
    result = it;
  endtask

  // Single-beat write returning only the response code.
  task write(input bit [63:0] addr, input bit [63:0] data, output ocah_axi_resp_e resp,
             input bit [15:0] id = '0, input bit [7:0] strb = 8'hFF, input int size = -1,
             input bit [2:0] prot = '0);
    ocah_axi_item result;
    write_result(addr, data, result, id, strb, size, OCAH_AXI_BURST_INCR, prot);
    resp = result.worst_resp();
  endtask

  // Single-beat read; `result` carries data_words[0] plus the response/ID
  // fields.
  task read_result(input bit [63:0] addr, output ocah_axi_item result, input bit [15:0] id = '0,
                   input int size = -1, input ocah_axi_burst_e burst = OCAH_AXI_BURST_INCR,
                   input bit [2:0] prot = '0, input bit check_response = 1'b1,
                   input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("read");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_READ;
    it.address        = addr;
    it.size           = resolve_size(size);
    it.burst          = burst;
    it.transaction_id = id;
    it.prot           = prot;
    it.expected_beats = 1;
    do_axi(it);
    read_transactions++;
    enforce_result(it, "read from", check_response, allow_timeout);
    result = it;
  endtask

  // Single-beat read returning only the data word.
  task read(input bit [63:0] addr, output bit [63:0] data, input bit [15:0] id = '0,
            input int size = -1, input bit [2:0] prot = '0);
    ocah_axi_item result;
    read_result(addr, result, id, size, OCAH_AXI_BURST_INCR, prot);
    data = result.first_data();
  endtask

  // Single-beat write with explicit channel skew (the cocotb write_skewed
  // parity operation): aw/w_valid_delay hold that channel's VALID low for N
  // cycles before it launches — AXI permits either arrival order, so
  // demux/regblock channel-ordering paths are exercised — and
  // b_ready_delay defers the BREADY assert after the data phase.
  task write_skewed_result(
      input bit [63:0] addr, input bit [63:0] data, output ocah_axi_item result,
      input int unsigned aw_valid_delay = 0, input int unsigned w_valid_delay = 0,
      input int unsigned b_ready_delay = 0, input bit [7:0] strb = 8'hFF, input int size = -1,
      input bit [2:0] prot = '0, input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("write_skewed");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_WRITE;
    it.address        = addr;
    it.data_words.push_back(data);
    it.strobes.push_back(resolve_strb(strb));
    it.size           = resolve_size(size);
    it.prot           = prot;
    it.expected_beats = 1;
    it.aw_valid_delay = aw_valid_delay;
    it.w_valid_delay  = w_valid_delay;
    it.b_ready_delay  = b_ready_delay;
    do_axi(it);
    write_transactions++;
    enforce_result(it, "skewed write to", check_response, allow_timeout);
    result = it;
  endtask

  // Single-beat read holding RREADY low for hold_cycles after RVALID
  // asserts (the cocotb read_with_rready_hold parity operation);
  // result.hold_stable reports RDATA/RRESP stability across the hold.
  task read_hold_result(input bit [63:0] addr, input int unsigned hold_cycles,
                        output ocah_axi_item result, input int size = -1, input bit [2:0] prot = '0,
                        input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("read_hold");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_READ;
    it.address        = addr;
    it.size           = resolve_size(size);
    it.prot           = prot;
    it.expected_beats = 1;
    it.r_ready_delay  = hold_cycles;
    do_axi(it);
    read_transactions++;
    enforce_result(it, "held read from", check_response, allow_timeout);
    result = it;
  endtask

  // Two single-beat writes queued back to back (the cocotb
  // write_pair_skewed_result parity operation): the second write's AW and
  // W launch as soon as the first's are accepted, so under a W delay the
  // second AW meets the responder while the first W is pending; BREADY is
  // deferred b_ready_delay cycles after the first write's request phase
  // and both B responses are accepted in order. `first` and `second` are
  // the completed items in issue order; first.ax_stall_cycles and
  // first.ax_stable observe the AW channel across the pair.
  task write_pair_skewed_result(
      input bit [63:0] addr_a, input bit [63:0] data_a, input bit [63:0] addr_b,
      input bit [63:0] data_b, output ocah_axi_item first, output ocah_axi_item second,
      input int unsigned aw_valid_delay = 0, input int unsigned w_valid_delay = 0,
      input int unsigned b_ready_delay = 0, input bit [7:0] strb_a = 8'hFF,
      input bit [7:0] strb_b = 8'hFF, input int size = -1, input bit [2:0] prot = '0,
      input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("write_pair");
    ocah_axi_item pair = ocah_axi_item::type_id::create("write_pair_second");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_WRITE;
    it.address        = addr_a;
    it.data_words.push_back(data_a);
    it.strobes.push_back(resolve_strb(strb_a));
    it.size           = resolve_size(size);
    it.prot           = prot;
    it.expected_beats = 1;
    it.aw_valid_delay = aw_valid_delay;
    it.w_valid_delay  = w_valid_delay;
    it.b_ready_delay  = b_ready_delay;
    pair.protocol       = it.protocol;
    pair.direction      = OCAH_AXI_DIR_WRITE;
    pair.address        = addr_b;
    pair.data_words.push_back(data_b);
    pair.strobes.push_back(resolve_strb(strb_b));
    pair.size           = it.size;
    pair.prot           = prot;
    pair.expected_beats = 1;
    it.pair             = pair;
    do_axi(it);
    write_transactions += 2;
    enforce_result(it, "paired write to", check_response, allow_timeout);
    enforce_result(pair, "paired write to", check_response, allow_timeout);
    first  = it;
    second = pair;
  endtask

  // Two single-beat reads with the second AR presented under an RREADY hold
  // (the cocotb read_pair_hold_result parity operation): AR(b) launches as
  // soon as AR(a) is accepted while RREADY stays low for hold_cycles after
  // the first RVALID, so a responder that admits one read at a time stalls
  // AR(b). first.hold_stable reports the hold window; first.ax_stall_cycles
  // and first.ax_stable observe the AR channel across the pair.
  task read_pair_hold_result(
      input bit [63:0] addr_a, input bit [63:0] addr_b, input int unsigned hold_cycles,
      output ocah_axi_item first, output ocah_axi_item second, input int size = -1,
      input bit [2:0] prot = '0, input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("read_pair");
    ocah_axi_item pair = ocah_axi_item::type_id::create("read_pair_second");
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_READ;
    it.address        = addr_a;
    it.size           = resolve_size(size);
    it.prot           = prot;
    it.expected_beats = 1;
    it.r_ready_delay  = hold_cycles;
    pair.protocol       = it.protocol;
    pair.direction      = OCAH_AXI_DIR_READ;
    pair.address        = addr_b;
    pair.size           = it.size;
    pair.prot           = prot;
    pair.expected_beats = 1;
    it.pair             = pair;
    do_axi(it);
    read_transactions += 2;
    enforce_result(it, "paired read from", check_response, allow_timeout);
    enforce_result(pair, "paired read from", check_response, allow_timeout);
    first  = it;
    second = pair;
  endtask

  // Multi-beat write burst (one raw bus word per beat; strb_words empty =
  // full-beat strobes on every beat). AXI4 only.
  task burst_write_result(
      input bit [63:0] addr, input bit [63:0] data_words[$], output ocah_axi_item result,
      input bit [15:0] id = '0, input bit [7:0] strb_words[$] = {}, input int size = -1,
      input ocah_axi_burst_e burst = OCAH_AXI_BURST_INCR, input bit [2:0] prot = '0,
      input bit check_response = 1'b1, input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("burst_write");
    if (data_words.size() == 0)
      `uvm_fatal(get_type_name(), "burst_write_result called with empty data_words")
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_WRITE;
    it.address        = addr;
    it.data_words     = data_words;
    foreach (data_words[i])
      it.strobes.push_back((i < strb_words.size()) ? resolve_strb(strb_words[i]) : cfg.full_strb());
    it.size           = resolve_size(size);
    it.burst          = burst;
    it.transaction_id = id;
    it.prot           = prot;
    it.expected_beats = data_words.size();
    do_axi(it);
    write_transactions++;
    enforce_result(it, "burst write to", check_response, allow_timeout);
    result = it;
  endtask

  // Multi-beat write burst returning only the response code.
  task burst_write(input bit [63:0] addr, input bit [63:0] data_words[$],
                   output ocah_axi_resp_e resp, input bit [15:0] id = '0);
    ocah_axi_item result;
    burst_write_result(addr, data_words, result, id);
    resp = result.worst_resp();
  endtask

  // Multi-beat read burst of `beats` beats; `result.data_words` carries one
  // raw bus word per beat. AXI4 only.
  task burst_read_result(input bit [63:0] addr, input int unsigned beats,
                         output ocah_axi_item result, input bit [15:0] id = '0, input int size = -1,
                         input ocah_axi_burst_e burst = OCAH_AXI_BURST_INCR,
                         input bit [2:0] prot = '0, input bit check_response = 1'b1,
                         input bit allow_timeout = 1'b0);
    ocah_axi_item it = ocah_axi_item::type_id::create("burst_read");
    if (beats == 0) `uvm_fatal(get_type_name(), "burst_read_result called with beats == 0")
    it.protocol       = resolve_cfg().protocol;
    it.direction      = OCAH_AXI_DIR_READ;
    it.address        = addr;
    it.size           = resolve_size(size);
    it.burst          = burst;
    it.transaction_id = id;
    it.prot           = prot;
    it.expected_beats = beats;
    do_axi(it);
    read_transactions++;
    enforce_result(it, "burst read from", check_response, allow_timeout);
    result = it;
  endtask

  // Multi-beat read burst returning only the data words.
  task burst_read(input bit [63:0] addr, input int unsigned beats, output bit [63:0] data_words[$],
                  input bit [15:0] id = '0);
    ocah_axi_item result;
    burst_read_result(addr, beats, result, id);
    data_words = result.data_words;
  endtask

endclass : ocah_axi_master_sequence
