// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive AXI transaction record, mirroring the cocotb OcahAxiItem fields at
// maximum storage widths (actual bus geometry lives in ocah_axi_config). One
// object represents one completed transaction: a write published at its B
// handshake, or a read published at its RLAST beat.
//
// The item doubles as the master sequence item and result object (the SV
// analogue of OcahAxiWriteResult/OcahAxiReadResult): transaction_id carries
// the issued AWID/ARID and the master driver fills the master-result extras
// (observed_id/observed_id_valid/timed_out) at completion. The passive
// monitor leaves those extras at defaults — its transaction_id is already
// wire truth.

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

  // Master stimulus-shaping knobs (cross-flow parity with the cocotb flat
  // master's skewed accesses). AXI permits the write address and data
  // channels to arrive independently: aw/w_valid_delay hold that channel's
  // VALID low for N sampled cycles before it launches, b_ready_delay defers
  // the BREADY assert after the last data beat, and r_ready_delay holds
  // RREADY low for N cycles after RVALID asserts while the driver samples
  // RDATA/RRESP stability. All-zero keeps the plain concurrent-channel
  // master timing.
  int unsigned        aw_valid_delay;
  int unsigned        w_valid_delay;
  int unsigned        b_ready_delay;
  int unsigned        r_ready_delay;

  // Master-result extras (cross-flow parity with the cocotb result
  // contract): observed_id is the BID/RID sampled live from the completing
  // response handshake (RLAST beat for reads) — never a copy of the issued
  // transaction_id. observed_id_valid stays 0 on ID-less buses
  // (cfg.id_width == 0) and on timeouts; timed_out reports a handshake
  // watchdog expiry (see ocah_axi_master_config.timeout_cycles).
  // hold_stable reports that RVALID stayed asserted with RDATA/RRESP
  // unchanged across a nonzero r_ready_delay window (stays 1 otherwise).
  bit [15:0]          observed_id;
  bit                 observed_id_valid;
  bit                 timed_out;
  bit                 hold_stable = 1'b1;

  // Two-outstanding operations (write_pair_skewed_result /
  // read_pair_hold_result, the cocotb pair-result parity): `pair` is the
  // second single-beat transaction the master driver launches before this
  // one completes, filled like a plain result. ax_stall_cycles counts the
  // cycles the address channel held VALID while READY was low across the
  // pair; ax_stable reports VALID and the address held through every such
  // stall (IHI 0022 A3.2.1).
  ocah_axi_item       pair;
  int unsigned        ax_stall_cycles;
  bit                 ax_stable = 1'b1;

  // Pipelined operation (pipeline_result, the cocotb pipeline_result
  // parity): `ops` are single-beat reads and writes the master driver keeps
  // in flight together, each filled like a plain result. In an op,
  // aw/w/ar_valid_delay count the cycles from the start of the operation
  // before that channel's VALID may assert; on the carrier item,
  // b_ready_delay and r_ready_delay hold BREADY and RREADY low for that many
  // cycles after the first BVALID and RVALID, and aw/w/ar_stall_cycles count
  // the cycles each request channel held VALID while READY was low.
  ocah_axi_item       ops[$];
  int unsigned        ar_valid_delay;
  int unsigned        aw_stall_cycles;
  int unsigned        w_stall_cycles;
  int unsigned        ar_stall_cycles;

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
    if (data_words.size() > 0) return data_words.size();
    if (resp_list.size() > 0) return resp_list.size();
    return 1;
  endfunction

  function bit [63:0] first_data();
    return (data_words.size() > 0) ? data_words[0] : '0;
  endfunction

  // True when a live response ID was captured and it echoes the issued ID.
  // Gate on observed_id_valid to distinguish "mismatch" from "no ID
  // captured" (the cocotb id_match None state).
  function bit id_match();
    return observed_id_valid && (observed_id === transaction_id);
  endfunction

  function string convert2string();
    return $sformatf(
        "%s %s addr=0x%0h beats=%0d resp=%s id=0x%0h size=%0d data0=0x%0h",
        protocol.name(),
        direction.name(),
        address,
        beat_count(),
        worst_resp().name(),
        transaction_id,
        size,
        first_data()
    );
  endfunction

  function void do_copy(uvm_object rhs);
    ocah_axi_item rhs_item;
    super.do_copy(rhs);
    if (!$cast(rhs_item, rhs)) `uvm_fatal(get_type_name(), "do_copy type mismatch")
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
    aw_valid_delay = rhs_item.aw_valid_delay;
    w_valid_delay  = rhs_item.w_valid_delay;
    b_ready_delay  = rhs_item.b_ready_delay;
    r_ready_delay  = rhs_item.r_ready_delay;
    ar_valid_delay = rhs_item.ar_valid_delay;
    observed_id       = rhs_item.observed_id;
    observed_id_valid = rhs_item.observed_id_valid;
    timed_out         = rhs_item.timed_out;
    hold_stable       = rhs_item.hold_stable;
    pair              = rhs_item.pair;
    ax_stall_cycles   = rhs_item.ax_stall_cycles;
    ax_stable         = rhs_item.ax_stable;
    ops               = rhs_item.ops;
    aw_stall_cycles   = rhs_item.aw_stall_cycles;
    w_stall_cycles    = rhs_item.w_stall_cycles;
    ar_stall_cycles   = rhs_item.ar_stall_cycles;
  endfunction

endclass : ocah_axi_item
