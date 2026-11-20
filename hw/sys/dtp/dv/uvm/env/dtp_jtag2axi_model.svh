// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI bridge model: the JTAG-visible state of the three tdr2axi bridges.
//
// Each bridge is a DTMCS TDR and a DMI TDR in front of a RISC-V Debug Module
// whose System Bus Access drives the bridge port
// (hw/ip/jtag/jtag_ptap/doc/architecture.adoc, "PTAP JTAG2AXI Support"). The
// model rebuilds every bridge from the decoded DR scans on the primary TAP and
// the transactions the passive monitors observe on its port:
//
//   DMI update   Without a sticky error, an update loads the scanned address
//                and data; op 1 reads and op 2 writes that Debug Module
//                register. Op 3 clears the sticky error; while the error is
//                set the bridge ignores every other update.
//   DMI capture  {address, data, status}: the last loaded address, the last
//                loaded data or the read response, and the sticky status. A
//                busy response from the Debug Module sets the status to BUSY
//                and, for a read, the data to 0xB051B051.
//   DTMCS        Capture: version 1, abits 7, idle 7, and the DMI sticky
//                status in dmistat. An update with dmireset gives the DMI an
//                op-3 update carrying its own address and data.
//   dmcontrol    While dmactive is 0 the Debug Module holds sbcs at its reset
//                value (sbaccess 2, sbversion and sbasize 0) and sbaddress and
//                sbdata at 0; a write of sbdata0 in that state starts a bus
//                write of 0 at address 0.
//   sbcs         A write sets sbreadonaddr, sbaccess, sbautoincrement and
//                sbreadondata and clears sbbusyerror and sberror where it
//                writes 1. sbversion, sbasize and the sbaccess* bits publish
//                the bridge's geometry.
//   sbaddress    An sbaddress0 write with sbreadonaddr starts a read. The
//                address holds sbasize bits; the bits above it read 0.
//   sbdata       An sbdata0 write starts a write; an sbdata0 read returns the
//                data and, with sbreadondata, then starts a read. An sbaddress
//                or sbdata access while sbbusyerror is set is a busy response
//                that leaves the register unchanged.
//   bus access   Starts only while sberror is 0. An sbaccess above the beat
//                width sets sberror 4 and an address not aligned to it sets 3,
//                without a transaction. Otherwise one beat of 2**sbaccess
//                bytes on the lanes the address selects; SLVERR or DECERR set
//                sberror 2. A completed read loads sbdata with the beat
//                shifted down to the address; a completed write loads it with
//                the read-data lanes, which carry no contract.
//                sbautoincrement advances the address by the size on every
//                completion. With the bridge's lifecycle disable asserted the
//                access completes as DECERR without reaching the port, and a
//                read returns 0xBADCAB1E per word.
//
// A system reset returns every bridge to its reset state; a TAP reset leaves
// them unchanged. A DMI operation is applied on the TCK cycle that leaves its
// Update-DR, and a bus completion at the first update at least one TCK cycle
// after the port handshake. The model predicts a bridge only where no DMI
// operation is in flight and no bus access races a Debug Module access: every
// DMI capture or update falls DtpDmiSettleTck TCK cycles or more after the
// last read or write update, and only sbcs is accessed while a bus access is
// outstanding. A scan outside that scope is a UVM error and carries no
// prediction. dtp_jtag2axi_tracker applies the scan, event and port streams
// to one model for each JTAG2AXI reference model. The cocotb twin is
// env/dtp_jtag2axi_model.py.

class dtp_jtag2axi_model;

  typedef struct {
    bit          is_read;
    int unsigned size;
    int unsigned offset;
  } access_t;

  typedef struct {
    // DMI TDR bridge.
    bit [6:0]    address;
    bit [31:0]   data;
    bit [31:0]   data_mask;
    bit [1:0]    error;
    bit          op_seen;
    int unsigned last_op_tck;
    // Debug Module. `ctrl` holds the sbcs fields a write or an access sets.
    bit          dmactive;
    bit          ndmreset;
    dtp_sbcs_t   ctrl;
    bit [63:0]   sbaddr;
    bit [63:0]   sbdata;
    bit [63:0]   sbdata_mask;
    bit          inflight_valid;
    access_t     inflight;
    // Completions due for accesses a system reset discarded.
    int unsigned orphans;
  } bridge_t;

  typedef struct {
    bit [31:0] data;
    bit [31:0] data_mask;
    bit        busy;
  } dm_response_t;

  localparam bit [31:0] DataBusy = 32'hB051_B051;
  localparam bit [31:0] ErrSlaveWord = 32'hBADC_AB1E;
  localparam bit [2:0] SberrorBus = 3'd2;
  localparam bit [2:0] SberrorAlign = 3'd3;
  localparam bit [2:0] SberrorSize = 3'd4;
  localparam bit [2:0] SbcsResetSbaccess = 3'd2;

  protected bridge_t      m_bridge     [string];
  protected ocah_axi_item m_completed_q[string] [$];

  function new();
    reset();
  endfunction

  // System reset: every bridge back to its reset state; accesses in flight
  // are discarded.
  function void reset();
    string names[3] = '{"smc_otp", "sep_otp", "smc_axi"};
    foreach (names[i]) begin
      string   n = names[i];
      bridge_t fresh = new_bridge();
      if (m_bridge.exists(n))
        fresh.orphans = m_bridge[n].orphans +
            int'(m_bridge[n].inflight_valid && m_completed_q[n].size() == 0);
      m_bridge[n] = fresh;
      m_completed_q[n] = {};
    end
  endfunction

  // Which bridge register a DR scan under `ir` addressed; SCAN_NONE when the
  // length does not fit it.
  static function dtp_j2a_scan_kind_e classify(bit [DtpIrWidth-1:0] ir, ocah_jtag_scan_item scan,
                                               output dtp_j2a_target_t t);
    dtp_j2a_scan_kind_e kind = dtp_j2a_classify_instr(ir, t);
    if (kind == DTP_J2A_SCAN_NONE || scan.bit_count != dtp_j2a_scan_len(kind))
      return DTP_J2A_SCAN_NONE;
    return kind;
  endfunction

  // Expected Capture-DR of a DTMCS or DMI scan on TCK cycle `tck`, into
  // `exp`; 0 when the capture is outside the model's scope.
  function bit predict_capture(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, int unsigned tck,
                               dtp_jtag2axi_status_item exp);
    bridge_t b = m_bridge[t.name];
    if (!check_settled(t, tck, "capture")) return 1'b0;
    exp.compare = 1'b1;
    exp.target  = t.name;
    exp.kind    = kind;
    if (kind == DTP_J2A_SCAN_DTMCS) begin
      exp.expected = 64'(DtpExpectedDtmcs | (32'(b.error) << DtpDtmcsDmistatLsb));
      exp.mask     = 64'hFFFF_FFFF;
    end else begin
      exp.expected = dtp_j2a_pack_dmi(b.address, b.data, b.error);
      exp.mask     = dtp_j2a_pack_dmi('1, b.data_mask, '1);
    end
    return 1'b1;
  endfunction

  // Update-DR of a DTMCS or DMI scan on TCK cycle `tck`; 1 with `launched`
  // the bus transaction it starts. Completions at or before `visible` have
  // reached the Debug Module; `gated` is the bridge's lifecycle disable.
  function bit update(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, bit [63:0] tdi,
                      int unsigned tck, time visible, bit gated, output ocah_axi_item launched);
    string        n = t.name;
    dtp_dmi_t     dmi;
    dm_response_t rsp;
    launched = null;
    if (kind == DTP_J2A_SCAN_DTMCS) begin
      if (!tdi[DtpDtmcsDmiresetBit]) return 1'b0;
      dmi = '{address: m_bridge[n].address, data: m_bridge[n].data, op: DTP_DMI_OP_CLEAR};
    end else dmi = dtp_j2a_unpack_dmi(tdi);
    if (!check_settled(t, tck, "update")) return 1'b0;
    apply_completions(t, visible);
    if (m_bridge[n].error != DTP_DMI_SUCCESS) begin
      if (dmi.op == DTP_DMI_OP_CLEAR) m_bridge[n].error = DTP_DMI_SUCCESS;
      return 1'b0;
    end
    m_bridge[n].address   = dmi.address;
    m_bridge[n].data      = dmi.data;
    m_bridge[n].data_mask = '1;
    if (dmi.op != DTP_DMI_OP_READ && dmi.op != DTP_DMI_OP_WRITE) return 1'b0;
    m_bridge[n].op_seen     = 1'b1;
    m_bridge[n].last_op_tck = tck;
    if (dmi.op == DTP_DMI_OP_READ) begin
      rsp = dm_read(t, dmi.address, gated, launched);
      m_bridge[n].data      = rsp.data;
      m_bridge[n].data_mask = rsp.data_mask;
    end else rsp = dm_write(t, dmi.address, dmi.data, gated, launched);
    if (rsp.busy) begin
      m_bridge[n].error = DTP_DMI_BUSY;
      if (dmi.op == DTP_DMI_OP_READ) begin
        m_bridge[n].data      = DataBusy;
        m_bridge[n].data_mask = '1;
      end
    end
    return launched != null;
  endfunction

  // A transaction observed on a bridge port, applied at a later update.
  function void complete(string target, ocah_axi_item observed);
    if (m_bridge[target].orphans != 0) begin
      m_bridge[target].orphans--;
      return;
    end
    m_completed_q[target].push_back(observed);
  endfunction

  // ------------------------------------------------------------------
  // Debug Module.
  // ------------------------------------------------------------------

  protected static function dtp_sbcs_t sbcs_reset();
    dtp_sbcs_t s = '0;
    s.sbaccess = SbcsResetSbaccess;
    return s;
  endfunction

  protected static function bridge_t new_bridge();
    bridge_t b;
    b.address        = '0;
    b.data           = '0;
    b.data_mask      = '1;
    b.error          = DTP_DMI_SUCCESS;
    b.op_seen        = 1'b0;
    b.last_op_tck    = 0;
    b.dmactive       = 1'b0;
    b.ndmreset       = 1'b0;
    b.ctrl           = sbcs_reset();
    b.sbaddr         = '0;
    b.sbdata         = '0;
    b.sbdata_mask    = '1;
    b.inflight_valid = 1'b0;
    b.inflight       = '{is_read: 1'b0, size: 0, offset: 0};
    b.orphans        = 0;
    return b;
  endfunction

  // The Debug Module's synchronous reset while dmactive is 0.
  protected function void reset_dm(string n);
    m_bridge[n].ndmreset    = 1'b0;
    m_bridge[n].ctrl        = sbcs_reset();
    m_bridge[n].sbaddr      = '0;
    m_bridge[n].sbdata      = '0;
    m_bridge[n].sbdata_mask = '1;
  endfunction

  protected function void scope_error(dtp_j2a_target_t t, string msg);
    `uvm_error("dtp_jtag2axi_model", {t.name, ": ", msg})
  endfunction

  protected function bit check_settled(dtp_j2a_target_t t, int unsigned tck, string what);
    int unsigned since = tck - m_bridge[t.name].last_op_tck;
    string       window = $sformatf("inside the %0d-TCK settle window", DtpDmiSettleTck);
    if (!m_bridge[t.name].op_seen || since >= DtpDmiSettleTck) return 1'b1;
    scope_error(t, $sformatf("%s %0d TCK after a DMI update, %s", what, since, window));
    return 1'b0;
  endfunction

  protected function bit [31:0] sbcs_value(dtp_j2a_target_t t);
    dtp_sbcs_t s = m_bridge[t.name].ctrl;
    if (!m_bridge[t.name].dmactive) return 32'(sbcs_reset());
    s.sbversion  = 3'd1;
    s.sbbusy     = m_bridge[t.name].inflight_valid;
    s.sbasize    = 7'(t.addr_width);
    s.sbaccess64 = (t.data_width >= 64);
    s.sbaccess32 = 1'b1;
    s.sbaccess16 = 1'b1;
    s.sbaccess8  = 1'b1;
    return 32'(s);
  endfunction

  // 1 when an sbaddress or sbdata access does not proceed: while sbbusyerror
  // is set it is a busy response, which `rsp` returns, and while a bus access
  // is outstanding it is outside the model's scope.
  protected function bit sba_blocked(dtp_j2a_target_t t, bit [6:0] address,
                                     inout dm_response_t rsp);
    if (m_bridge[t.name].inflight_valid) begin
      scope_error(t, $sformatf("DM register 0x%02h accessed during a bus access", address));
      return 1'b1;
    end
    rsp.busy = m_bridge[t.name].ctrl.sbbusyerror;
    return rsp.busy;
  endfunction

  protected function dm_response_t dm_read(dtp_j2a_target_t t, bit [6:0] address, bit gated,
                                           output ocah_axi_item launched);
    string        n = t.name;
    dm_response_t rsp = '{data: '0, data_mask: '0, busy: 1'b0};
    launched = null;
    case (address)
      DTP_DM_DMCONTROL: begin
        rsp.data      = {30'd0, m_bridge[n].ndmreset, m_bridge[n].dmactive};
        rsp.data_mask = 32'h3;
      end
      DTP_DM_SBCS: begin
        // An outstanding access may complete before the read reaches the
        // Debug Module.
        dtp_sbcs_t unknown = '0;
        if (m_bridge[n].dmactive && m_bridge[n].inflight_valid) begin
          unknown.sbbusy  = 1'b1;
          unknown.sberror = '1;
        end
        rsp.data      = sbcs_value(t);
        rsp.data_mask = ~32'(unknown);
      end
      DTP_DM_SBADDRESS0, DTP_DM_SBADDRESS1: begin
        if (m_bridge[n].inflight_valid) begin
          scope_error(t, "sbaddress read while a bus access is outstanding");
          return rsp;
        end
        rsp.data      = 32'(m_bridge[n].sbaddr >> ((address == DTP_DM_SBADDRESS0) ? 0 : 32));
        rsp.data_mask = '1;
      end
      DTP_DM_SBDATA0, DTP_DM_SBDATA1: begin
        int unsigned shift = (address == DTP_DM_SBDATA0) ? 0 : 32;
        if (sba_blocked(t, address, rsp)) return rsp;
        rsp.data      = 32'(m_bridge[n].sbdata >> shift);
        rsp.data_mask = 32'(m_bridge[n].sbdata_mask >> shift);
        if (address == DTP_DM_SBDATA0 && m_bridge[n].ctrl.sbreadondata &&
            m_bridge[n].ctrl.sberror == 0)
          launched = launch(t, 1'b1, gated);
      end
      default: ;
    endcase
    return rsp;
  endfunction

  protected function dm_response_t dm_write(dtp_j2a_target_t t, bit [6:0] address, bit [31:0] data,
                                            bit gated, output ocah_axi_item launched);
    string        n = t.name;
    dm_response_t rsp = '{data: '0, data_mask: '0, busy: 1'b0};
    int unsigned  shift;
    launched = null;
    case (address)
      DTP_DM_DMCONTROL: begin
        m_bridge[n].ndmreset = m_bridge[n].dmactive && data[1];
        m_bridge[n].dmactive = data[0];
        if (!data[0]) reset_dm(n);
      end
      DTP_DM_SBCS: begin
        dtp_sbcs_t w = dtp_sbcs_t'(data);
        if (m_bridge[n].inflight_valid) begin
          scope_error(t, "sbcs written while a bus access is outstanding");
          return rsp;
        end
        if (m_bridge[n].dmactive) begin
          m_bridge[n].ctrl.sbreadonaddr    = w.sbreadonaddr;
          m_bridge[n].ctrl.sbaccess        = w.sbaccess;
          m_bridge[n].ctrl.sbautoincrement = w.sbautoincrement;
          m_bridge[n].ctrl.sbreadondata    = w.sbreadondata;
          if (w.sbbusyerror) m_bridge[n].ctrl.sbbusyerror = 1'b0;
          if (w.sberror != 0) m_bridge[n].ctrl.sberror = '0;
        end
      end
      DTP_DM_SBADDRESS0, DTP_DM_SBADDRESS1: begin
        if (sba_blocked(t, address, rsp) || !m_bridge[n].dmactive) return rsp;
        shift = (address == DTP_DM_SBADDRESS0) ? 0 : 32;
        m_bridge[n].sbaddr =
            ((m_bridge[n].sbaddr & ~(64'hFFFF_FFFF << shift)) | (64'(data) << shift)) &
            ocah_rng::bit_mask(t.addr_width);
        if (address == DTP_DM_SBADDRESS0 && m_bridge[n].ctrl.sbreadonaddr &&
            m_bridge[n].ctrl.sberror == 0)
          launched = launch(t, 1'b1, gated);
      end
      DTP_DM_SBDATA0, DTP_DM_SBDATA1: begin
        if (sba_blocked(t, address, rsp)) return rsp;
        shift = (address == DTP_DM_SBDATA0) ? 0 : 32;
        if (m_bridge[n].dmactive) begin
          m_bridge[n].sbdata =
              (m_bridge[n].sbdata & ~(64'hFFFF_FFFF << shift)) | (64'(data) << shift);
          m_bridge[n].sbdata_mask |= 64'hFFFF_FFFF << shift;
        end
        if (address == DTP_DM_SBDATA0 && m_bridge[n].ctrl.sberror == 0)
          launched = launch(t, 1'b0, gated);
      end
      default: ;
    endcase
    return rsp;
  endfunction

  // ------------------------------------------------------------------
  // System bus access.
  // ------------------------------------------------------------------

  protected function ocah_axi_item launch(dtp_j2a_target_t t, bit is_read, bit gated);
    string        n = t.name;
    int unsigned  size = m_bridge[n].ctrl.sbaccess;
    access_t      access;
    bit    [63:0] written;
    bit    [63:0] wdata;
    ocah_axi_item item;

    bit [7:0] lanes;
    // The alignment error takes precedence over the size error.
    if ((m_bridge[n].sbaddr & ocah_rng::bit_mask(size)) != 0) begin
      m_bridge[n].ctrl.sberror = SberrorAlign;
      return null;
    end
    if (size > t.default_size) begin
      m_bridge[n].ctrl.sberror = SberrorSize;
      return null;
    end
    access = '{is_read: is_read, size: size, offset: int'(m_bridge[n].sbaddr % t.beat_bytes)};
    if (gated) begin
      finish(t, access, 1'b1, err_slave_beat(t));
      return null;
    end
    lanes   = 8'(dtp_j2a_full_wstrb(size) << access.offset);
    written = dtp_j2a_strobe_lanes(lanes);
    if (!is_read && ((m_bridge[n].sbdata_mask << (8 * access.offset)) & written) != written) begin
      scope_error(t, "bus write of sbdata bits without a contract");
      return null;
    end
    m_bridge[n].inflight_valid = 1'b1;
    m_bridge[n].inflight       = access;
    item                       = ocah_axi_item::type_id::create("item");
    item.protocol              = t.protocol;
    item.direction             = is_read ? OCAH_AXI_DIR_READ : OCAH_AXI_DIR_WRITE;
    item.address               = m_bridge[n].sbaddr;
    item.size                  = size;
    item.expected_beats        = 1;
    if (!is_read) begin
      wdata = (m_bridge[n].sbdata << (8 * access.offset)) & ocah_rng::bit_mask(t.data_width);
      item.data_words.push_back(wdata);
      item.strobes.push_back(lanes);
    end
    return item;
  endfunction

  protected static function bit [63:0] err_slave_beat(dtp_j2a_target_t t);
    return {2{ErrSlaveWord}} & ocah_rng::bit_mask(t.data_width);
  endfunction

  protected function void finish(dtp_j2a_target_t t, access_t access, bit resp_error,
                                 bit [63:0] rdata);
    string n = t.name;
    m_bridge[n].inflight_valid = 1'b0;
    if (!m_bridge[n].dmactive) return;
    if (resp_error) m_bridge[n].ctrl.sberror = SberrorBus;
    m_bridge[n].sbdata = (rdata >> (8 * access.offset)) & ocah_rng::bit_mask(t.data_width);
    m_bridge[n].sbdata_mask = access.is_read ? ocah_rng::bit_mask(t.data_width) : '0;
    if (m_bridge[n].ctrl.sbautoincrement) begin
      m_bridge[n].sbaddr += dtp_j2a_size_bytes(access.size);
      m_bridge[n].sbaddr &= ocah_rng::bit_mask(t.addr_width);
    end
  endfunction

  protected function void apply_completions(dtp_j2a_target_t t, time visible);
    string n = t.name;
    while (m_completed_q[n].size() > 0 && m_completed_q[n][0].end_time <= visible) begin
      ocah_axi_item observed = m_completed_q[n].pop_front();
      // A transaction nothing launched: the scoreboard reports it as
      // unpredicted.
      if (m_bridge[n].inflight_valid)
        finish(t, m_bridge[n].inflight,
               observed.worst_resp() inside {OCAH_AXI_RESP_SLVERR, OCAH_AXI_RESP_DECERR},
               (observed.direction == OCAH_AXI_DIR_READ) ? observed.first_data() : '0);
    end
  endfunction

endclass : dtp_jtag2axi_model

// The scan, TCK-event and port streams applied to one dtp_jtag2axi_model,
// shared by the two JTAG2AXI reference models: a DR scan addressing a bridge
// register yields its expected capture when the PTAP 3DCR select is clear,
// its Update-DR is applied on the TCK cycle that leaves Update-DR, and the
// transaction it launches is returned from on_event with the bridge's name.
// The debug disable of the bridge is read from dtp_tb_if at that cycle.
class dtp_jtag2axi_tracker;

  virtual dtp_tb_if             tb_vif;
  dtp_jtag_ir_model             ir;
  dtp_jtag2axi_model            bridges;
  protected string              m_target_by_source[string];
  protected bit          [31:0] m_sys_rst_seen;
  protected int unsigned        m_tck;
  protected int unsigned        m_capture_tck;
  protected time                m_prev_step;
  // The bridge scan waiting for the TAP to leave Update-DR.
  protected bit                 m_pending;
  protected dtp_j2a_target_t    m_pending_target;
  protected dtp_j2a_scan_kind_e m_pending_kind;
  protected bit          [63:0] m_pending_tdi;

  function new(virtual dtp_tb_if tb_vif);
    this.tb_vif = tb_vif;
    ir          = new();
    bridges     = new();
  endfunction

  // Name the monitor whose items carry a bridge's transactions.
  function void bind_port(string target, string source);
    m_target_by_source[source] = target;
  endfunction

  // One reconstructed scan; its expected capture, or no contract.
  function dtp_jtag2axi_status_item on_scan(ocah_jtag_scan_item t);
    dtp_jtag2axi_status_item exp = dtp_jtag2axi_status_item::type_id::create("exp");
    dtp_j2a_target_t         target;
    dtp_j2a_scan_kind_e      kind;
    exp.compare   = 1'b0;
    exp.timestamp = t.end_time;
    sync_reset();
    if (t.is_ir) begin
      ir.on_ir_scan(t);
      return exp;
    end
    ir.on_dr_scan(t);
    if (!ir.ir_known()) return exp;
    kind = dtp_jtag2axi_model::classify(ir.ir(), t, target);
    if (kind == DTP_J2A_SCAN_NONE) return exp;
    m_pending        = 1'b1;
    m_pending_target = target;
    m_pending_kind   = kind;
    m_pending_tdi    = t.tdi_value();
    if (!ir.ptap_select_clear()) return exp;
    exp.context_s = $sformatf("%s %s tdi=0x%0h", target.name, kind.name(), m_pending_tdi);
    void'(bridges.predict_capture(target, kind, m_capture_tck, exp));
    return exp;
  endfunction

  // One TCK event; 1 with the bridge and transaction an update on it
  // launches.
  function bit on_event(ocah_jtag_event t, output string target, output ocah_axi_item launched);
    bit started = 1'b0;
    bit gated;
    launched = null;
    sync_reset();
    if (t.kind == OCAH_JTAG_EV_STEP && t.trst_n) begin
      m_tck++;
      if (ir.tap_state() == OCAH_JTAG_CAPTURE_DR) m_capture_tck = m_tck;
      else if (ir.tap_state() == OCAH_JTAG_UPDATE_DR && m_pending) begin
        m_pending = 1'b0;
        target    = m_pending_target.name;
        gated     = dtp_dbg_path_disabled(tb_vif.dbg_disable, m_pending_target.dbg_path);
        started   = bridges.update(m_pending_target, m_pending_kind, m_pending_tdi, m_tck,
                                   m_prev_step, gated, launched);
      end
      m_prev_step = t.timestamp;
    end
    void'(ir.on_event(t));
    if (ir.take_tap_reset()) m_pending = 1'b0;
    return started;
  endfunction

  function void on_axi(ocah_axi_item t);
    if (!m_target_by_source.exists(t.source))
      `uvm_fatal("dtp_jtag2axi_tracker", $sformatf("AXI item from unbound port `%s`", t.source))
    bridges.complete(m_target_by_source[t.source], t);
  endfunction

  // Power-on reset resets the TAP; a system reset resets every bridge.
  protected function void sync_reset();
    void'(ir.sync_power_on_reset(tb_vif.por_assert_count));
    if (ir.take_tap_reset()) m_pending = 1'b0;
    if (tb_vif.sys_rst_assert_count !== m_sys_rst_seen) begin
      m_sys_rst_seen = tb_vif.sys_rst_assert_count;
      bridges.reset();
    end
  endfunction

endclass : dtp_jtag2axi_tracker
