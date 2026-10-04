// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Base of the pipeline scenario sequences: the handles the test binds, a
// per-cycle recorder of the master's own interface, and the queries the
// scenarios judge the recording with. recorded_pipeline() runs
// pipeline_result under the recorder, which keeps sampling for `tail`
// cycles after the operation returns; handshakes() and stalls() reduce the
// recording per channel, and valid_at / ready_at / payload_at read one
// sample.

class ocah_axi_pipeline_base_test_seq extends ocah_axi_master_sequence;
  `uvm_object_utils(ocah_axi_pipeline_base_test_seq)

  // Handshake bound the timeout scenarios shorten cfg.timeout_cycles to.
  localparam int unsigned ShortTimeout = 50;

  typedef struct {
    bit        awvalid, awready, wvalid, wready, bvalid, bready;
    bit        arvalid, arready, rvalid, rready, rlast;
    bit [63:0] awaddr, wdata, araddr;
  } sample_t;

  // Bound by the test before start().
  ocah_axi_checker        evidence;
  ocah_axi_slave_sequence slave_seq;

  protected sample_t m_samples[$];
  protected bit      m_stop;

  function new(string name = "ocah_axi_pipeline_base_test_seq");
    super.new(name);
  endfunction

  protected task record();
    m_samples.delete();
    while (!m_stop) begin
      sample_t row;
      @(cfg.vif.mon_cb);
      row.awvalid = cfg.vif.mon_cb.awvalid === 1'b1;
      row.awready = cfg.vif.mon_cb.awready === 1'b1;
      row.wvalid  = cfg.vif.mon_cb.wvalid === 1'b1;
      row.wready  = cfg.vif.mon_cb.wready === 1'b1;
      row.bvalid  = cfg.vif.mon_cb.bvalid === 1'b1;
      row.bready  = cfg.vif.mon_cb.bready === 1'b1;
      row.arvalid = cfg.vif.mon_cb.arvalid === 1'b1;
      row.arready = cfg.vif.mon_cb.arready === 1'b1;
      row.rvalid  = cfg.vif.mon_cb.rvalid === 1'b1;
      row.rready  = cfg.vif.mon_cb.rready === 1'b1;
      row.rlast   = cfg.vif.mon_cb.rlast === 1'b1;
      row.awaddr  = 64'(cfg.vif.mon_cb.awaddr);
      row.wdata   = 64'(cfg.vif.mon_cb.wdata);
      row.araddr  = 64'(cfg.vif.mon_cb.araddr);
      m_samples.push_back(row);
    end
  endtask

  // chan: 0 AW, 1 W, 2 B, 3 AR, 4 R.
  protected function bit valid_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awvalid;
      1: return m_samples[c].wvalid;
      2: return m_samples[c].bvalid;
      3: return m_samples[c].arvalid;
      default: return m_samples[c].rvalid;
    endcase
  endfunction

  protected function bit ready_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awready;
      1: return m_samples[c].wready;
      2: return m_samples[c].bready;
      3: return m_samples[c].arready;
      default: return m_samples[c].rready;
    endcase
  endfunction

  protected function bit [63:0] payload_at(int unsigned chan, int unsigned c);
    case (chan)
      0: return m_samples[c].awaddr;
      1: return m_samples[c].wdata;
      default: return m_samples[c].araddr;
    endcase
  endfunction

  protected function void handshakes(int unsigned chan, ref int unsigned hs[$]);
    hs.delete();
    foreach (m_samples[c]) if (valid_at(chan, c) && ready_at(chan, c)) hs.push_back(c);
  endfunction

  protected function int unsigned stalls(int unsigned chan);
    int unsigned n = 0;
    foreach (m_samples[c]) if (valid_at(chan, c) && !ready_at(chan, c)) n++;
    return n;
  endfunction

  // pipeline_result under the per-cycle recorder, which keeps sampling for
  // `tail` cycles after the operation returns.
  protected task recorded_pipeline(input ocah_axi_item ops[$], output ocah_axi_item result,
                                   input int unsigned b_hold = 0, input int unsigned r_hold = 0,
                                   input bit allow_timeout = 1'b0, input int unsigned tail = 0);
    m_stop = 1'b0;
    fork
      record();
      begin
        pipeline_result(ops, result, b_hold, r_hold, 1'b1, allow_timeout);
        repeat (tail) @(cfg.vif.mon_cb);
        m_stop = 1'b1;
      end
    join
  endtask

endclass : ocah_axi_pipeline_base_test_seq
