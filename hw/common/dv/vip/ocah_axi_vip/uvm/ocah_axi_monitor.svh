// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// Passive AXI4 / AXI4-Lite transaction monitor over ocah_axi_if.mon_cb.
//
// Reconstruction mirrors the cocotb OcahAxiMonitor: writes publish one item at
// the B handshake (AW paired FIFO with completed W bursts — AXI4 mandates W
// order matches AW order — then matched to B by ID), reads accumulate beats
// per RID and publish at RLAST against the per-ARID address queue. AXI4-Lite
// integrations tie awlen=0/wlast=1/rlast=1/ids=0 (see ocah_axi_if), so the
// same reconstruction path serves both protocols. Sampled values are masked
// to cfg.{addr,data,id}_width. All pending state flushes while aresetn is low.
//
// Publishes raw observations only; checking belongs to the ref model and
// scoreboard subscribers (same ownership split as ocah_jtag_master_monitor).

class ocah_axi_monitor extends uvm_monitor;
  `uvm_component_utils(ocah_axi_monitor)

  ocah_axi_config cfg;
  uvm_analysis_port #(ocah_axi_item) item_ap;

  int unsigned item_count;
  int unsigned write_count;
  int unsigned read_count;
  // Completions with no matching request phase: retained as findings,
  // never published as transactions; fails in check_phase.
  int unsigned orphan_responses;

  // Request-channel VALID rising-edge counters (no-activity evidence).
  int unsigned aw_activity;
  int unsigned w_activity;
  int unsigned ar_activity;

  typedef struct {
    bit [63:0]   address;
    bit [15:0]   id;
    int unsigned size;
    bit [1:0]    burst;
    bit [2:0]    prot;
    int unsigned length;
    time         start_time;
  } addr_info_t;

  typedef struct {
    bit [63:0] data;
    bit [7:0]  strb;
  } w_beat_t;

  protected addr_info_t m_aw_q[$];
  protected w_beat_t    m_wburst_q[$][$];
  protected w_beat_t    m_cur_w[$];
  protected addr_info_t m_paired_wr[bit [15:0]][$];
  protected w_beat_t    m_paired_beats[bit [15:0]][$][$];
  protected addr_info_t m_ar_q[bit [15:0]][$];
  protected ocah_axi_item m_cur_rd[bit [15:0]];
  // Read bursts whose first data beat arrived before any AR for that ID.
  protected bit m_r_no_ar[bit [15:0]];

  protected bit m_prev_awvalid, m_prev_wvalid, m_prev_arvalid;

  function new(string name = "ocah_axi_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(ocah_axi_config)::get(this, "", "cfg", cfg) || cfg == null)
      `uvm_fatal(get_type_name(), "ocah_axi_config `cfg` not found in uvm_config_db")
    if (cfg.vif == null) `uvm_fatal(get_type_name(), "ocah_axi_config.vif is null")
    item_ap = new("item_ap", this);
  endfunction

  protected function bit [63:0] mask_addr(bit [63:0] value);
    return (cfg.addr_width >= 64) ? value : (value & ((64'd1 << cfg.addr_width) - 1));
  endfunction

  protected function bit [63:0] mask_data(bit [63:0] value);
    return (cfg.data_width >= 64) ? value : (value & ((64'd1 << cfg.data_width) - 1));
  endfunction

  protected function bit [15:0] mask_id(bit [15:0] value);
    return (cfg.id_width == 0) ? '0 : (value & ((16'd1 << cfg.id_width) - 1));
  endfunction

  protected function void flush();
    m_aw_q.delete();
    m_wburst_q.delete();
    m_cur_w.delete();
    m_paired_wr.delete();
    m_paired_beats.delete();
    m_ar_q.delete();
    m_cur_rd.delete();
    m_r_no_ar.delete();
  endfunction

  // In-flight requests awaiting completion (drain obligation).
  function int unsigned pending_count();
    int unsigned total = m_aw_q.size() + m_wburst_q.size()
                             + (m_cur_w.size() ? 1 : 0) + m_cur_rd.num();
    foreach (m_paired_wr[id]) total += m_paired_wr[id].size();
    foreach (m_ar_q[id]) total += m_ar_q[id].size();
    return total;
  endfunction

  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if (pending_count() > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d in-flight transaction(s) never completed (drain)", pending_count()))
    if (orphan_responses > 0)
      `uvm_error(cfg.name_tag, $sformatf(
                 "%0d orphan completion(s) had no request phase", orphan_responses))
  endfunction

  protected function void record_orphan(string channel, string detail);
    orphan_responses++;
    `uvm_error(cfg.name_tag, $sformatf(
               "orphan %s response (no matching request phase): %s", channel, detail))
  endfunction

  task run_phase(uvm_phase phase);
    forever begin
      @(cfg.vif.mon_cb);
      if (cfg.vif.aresetn !== 1'b1) begin
        flush();
        continue;
      end
      track_activity();
      sample_aw();
      sample_w();
      pair_writes();
      sample_b();
      sample_ar();
      sample_r();
    end
  endtask

  protected function void track_activity();
    if (cfg.vif.mon_cb.awvalid === 1'b1 && !m_prev_awvalid) aw_activity++;
    if (cfg.vif.mon_cb.wvalid === 1'b1 && !m_prev_wvalid) w_activity++;
    if (cfg.vif.mon_cb.arvalid === 1'b1 && !m_prev_arvalid) ar_activity++;
    m_prev_awvalid = (cfg.vif.mon_cb.awvalid === 1'b1);
    m_prev_wvalid  = (cfg.vif.mon_cb.wvalid === 1'b1);
    m_prev_arvalid = (cfg.vif.mon_cb.arvalid === 1'b1);
  endfunction

  protected function void sample_aw();
    addr_info_t info;
    if (!(cfg.vif.mon_cb.awvalid === 1'b1 && cfg.vif.mon_cb.awready === 1'b1)) return;
    info.address    = mask_addr(cfg.vif.mon_cb.awaddr);
    info.id         = mask_id(cfg.vif.mon_cb.awid);
    info.size       = int'(cfg.vif.mon_cb.awsize);
    info.burst      = cfg.vif.mon_cb.awburst;
    info.prot       = cfg.vif.mon_cb.awprot;
    info.length     = int'(cfg.vif.mon_cb.awlen) + 1;
    info.start_time = $time;
    m_aw_q.push_back(info);
  endfunction

  protected function void sample_w();
    w_beat_t beat;
    if (!(cfg.vif.mon_cb.wvalid === 1'b1 && cfg.vif.mon_cb.wready === 1'b1)) return;
    beat.data = mask_data(cfg.vif.mon_cb.wdata);
    beat.strb = cfg.vif.mon_cb.wstrb[7:0];
    m_cur_w.push_back(beat);
    if (cfg.vif.mon_cb.wlast === 1'b1) begin
      m_wburst_q.push_back(m_cur_w);
      m_cur_w.delete();
    end
  endfunction

  // Pair oldest AW with oldest completed W burst; the pair waits per-ID
  // for its (possibly out-of-order) B response.
  protected function void pair_writes();
    while (m_aw_q.size() > 0 && m_wburst_q.size() > 0) begin
      addr_info_t info = m_aw_q.pop_front();
      w_beat_t beats[$] = m_wburst_q.pop_front();
      m_paired_wr[info.id].push_back(info);
      m_paired_beats[info.id].push_back(beats);
    end
  endfunction

  protected function void sample_b();
    addr_info_t info;
    w_beat_t beats[$];
    ocah_axi_item wr_item;
    bit [15:0] id;
    if (!(cfg.vif.mon_cb.bvalid === 1'b1 && cfg.vif.mon_cb.bready === 1'b1)) return;
    id = mask_id(cfg.vif.mon_cb.bid);
    if (!(m_paired_wr.exists(id) && m_paired_wr[id].size() > 0)) begin
      record_orphan("B", $sformatf("bid=0x%0h bresp=%0d time=%0t", id, cfg.vif.mon_cb.bresp, $time
                    ));
      return;
    end
    info  = m_paired_wr[id].pop_front();
    beats = m_paired_beats[id].pop_front();
    wr_item = ocah_axi_item::type_id::create("wr_item");
    wr_item.protocol       = cfg.protocol;
    wr_item.direction      = OCAH_AXI_DIR_WRITE;
    wr_item.address        = info.address;
    foreach (beats[i]) begin
      wr_item.data_words.push_back(beats[i].data);
      wr_item.strobes.push_back(beats[i].strb);
    end
    wr_item.size           = info.size;
    wr_item.burst          = ocah_axi_burst_e'(info.burst);
    wr_item.transaction_id = id;
    wr_item.prot           = info.prot;
    wr_item.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.bresp));
    wr_item.expected_beats = info.length;
    wr_item.start_time     = info.start_time;
    wr_item.end_time       = $time;
    wr_item.source         = get_full_name();
    publish(wr_item);
  endfunction

  protected function void sample_ar();
    addr_info_t info;
    if (!(cfg.vif.mon_cb.arvalid === 1'b1 && cfg.vif.mon_cb.arready === 1'b1)) return;
    info.address    = mask_addr(cfg.vif.mon_cb.araddr);
    info.id         = mask_id(cfg.vif.mon_cb.arid);
    info.size       = int'(cfg.vif.mon_cb.arsize);
    info.burst      = cfg.vif.mon_cb.arburst;
    info.prot       = cfg.vif.mon_cb.arprot;
    info.length     = int'(cfg.vif.mon_cb.arlen) + 1;
    info.start_time = $time;
    m_ar_q[info.id].push_back(info);
  endfunction

  protected function void sample_r();
    ocah_axi_item rd_item;
    addr_info_t info;
    bit info_valid;
    bit [15:0] id;
    if (!(cfg.vif.mon_cb.rvalid === 1'b1 && cfg.vif.mon_cb.rready === 1'b1)) return;
    id = mask_id(cfg.vif.mon_cb.rid);
    if (!m_cur_rd.exists(id)) begin
      rd_item = ocah_axi_item::type_id::create("rd_item");
      rd_item.protocol  = cfg.protocol;
      rd_item.direction = OCAH_AXI_DIR_READ;
      rd_item.transaction_id = id;
      rd_item.source    = get_full_name();
      m_cur_rd[id] = rd_item;
      // Read DATA before any AR for this ID is a protocol violation;
      // the burst stays tainted even if an AR arrives before RLAST.
      if (!(m_ar_q.exists(id) && m_ar_q[id].size() > 0)) m_r_no_ar[id] = 1'b1;
    end
    rd_item = m_cur_rd[id];
    rd_item.data_words.push_back(mask_data(cfg.vif.mon_cb.rdata));
    rd_item.resp_list.push_back(ocah_axi_resp_e'(cfg.vif.mon_cb.rresp));
    if (cfg.vif.mon_cb.rlast === 1'b1) begin
      if (m_r_no_ar.exists(id)) begin
        m_r_no_ar.delete(id);
        m_cur_rd.delete(id);
        // A late AR (if any) stays pending: the drain check also
        // flags the never-served request.
        record_orphan("R", $sformatf(
                      "rid=0x%0h beats=%0d data began before AR time=%0t",
                      id,
                      rd_item.data_words.size(),
                      $time
                      ));
        return;
      end
      info_valid = m_ar_q.exists(id) && (m_ar_q[id].size() > 0);
      if (!info_valid) begin
        m_cur_rd.delete(id);
        record_orphan("R", $sformatf(
                      "rid=0x%0h beats=%0d time=%0t", id, rd_item.data_words.size(), $time));
        return;
      end
      info = m_ar_q[id].pop_front();
      rd_item.address        = info.address;
      rd_item.size           = info.size;
      rd_item.burst          = ocah_axi_burst_e'(info.burst);
      rd_item.prot           = info.prot;
      rd_item.expected_beats = info.length;
      rd_item.start_time     = info.start_time;
      rd_item.end_time = $time;
      m_cur_rd.delete(id);
      publish(rd_item);
    end
  endfunction

  protected function void publish(ocah_axi_item item);
    item_count++;
    if (item.direction == OCAH_AXI_DIR_WRITE) write_count++;
    else read_count++;
    `uvm_info(get_type_name(), {"observed ", item.convert2string()}, UVM_HIGH)
    item_ap.write(item);
  endfunction

endclass : ocah_axi_monitor
