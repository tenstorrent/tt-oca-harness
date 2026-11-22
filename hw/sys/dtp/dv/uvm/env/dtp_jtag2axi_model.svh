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
//   operation    A read or write is in progress from its Update-DR until the
//                Debug Module's response returns. A DMI capture during a read
//                sets the status to BUSY and returns the operation's own
//                address and data; an update during either sets the status to
//                BUSY, or to 0 for op 3, and loads nothing.
//   DTMCS        Capture: version 1, abits 7, idle 7, and the DMI sticky
//                status in dmistat. An update with dmireset gives the DMI an
//                op-3 update carrying its own address and data.
//   dmcontrol    While dmactive is 0 the Debug Module holds sbcs at its reset
//                value (sbaccess 2, sbversion and sbasize 0) and sbaddress and
//                sbdata at 0, and no System Bus Access starts.
//   sbcs         A write sets sbreadonaddr, sbaccess, sbautoincrement and
//                sbreadondata and clears sbbusyerror and sberror where it
//                writes 1. sbversion, sbasize and the sbaccess* bits publish
//                the bridge's geometry. A write while a bus access is
//                outstanding is a busy response that sets sbbusyerror and
//                writes nothing.
//   sbaddress    An sbaddress0 write with sbreadonaddr starts a read. The
//                address holds sbasize bits; the bits above it read 0.
//   sbdata       An sbdata0 write starts a write; an sbdata0 read returns the
//                data and, with sbreadondata, then starts a read. An sbaddress
//                or sbdata access while a bus access is outstanding or
//                sbbusyerror is set is a busy response that sets sbbusyerror
//                and leaves the register unchanged.
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
// them unchanged. Captures and updates come from the TCK steps, so a DR scan
// of any length counts: its update loads the captured value shifted by the
// bits the scan shifted, and only those bits of its capture are compared. A
// DMI operation is applied on the TCK cycle that leaves its Update-DR, and a
// bus completion at the first update at least one TCK cycle after the port
// handshake. A capture or update within DtpDmiBusyTck TCK cycles of the last
// read or write update finds that operation in progress, and one
// DtpDmiSettleTck cycles or more after it finds it complete; between the two
// the clock ratio decides, and the model has no prediction. While a bus
// access is outstanding only sbcs is read, unless the bridge's response hold
// for that access is set, which keeps the access outstanding until the hold
// releases. A scan outside that scope is a UVM error and carries no
// prediction. dtp_jtag2axi_tracker applies the scan, event and port streams
// to one model for each JTAG2AXI reference model. The cocotb twin is
// env/dtp_jtag2axi_model.py.

class dtp_jtag2axi_model;

  typedef struct {
    bit          is_read;
    int unsigned size;
    int unsigned offset;
  } access_t;

  // A bridge's response holds: `b` keeps write responses from it, `r` read
  // responses.
  typedef struct {
    bit b;
    bit r;
  } holds_t;

  typedef struct {
    bit [31:0] data;
    bit [31:0] data_mask;
    bit        busy;
  } dm_response_t;

  typedef enum {
    OP_IDLE,
    OP_IN_PROGRESS,
    OP_UNKNOWN
  } op_state_e;

  typedef struct {
    // DMI TDR bridge.
    bit [6:0]     address;
    bit [31:0]    data;
    bit [31:0]    data_mask;
    bit [1:0]     error;
    int unsigned  last_op_tck;
    bit           op_read;
    // The Debug Module's response to the read or write in progress, applied
    // when it returns.
    bit           pending_valid;
    dm_response_t pending;
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

  localparam bit [31:0] DataBusy = 32'hB051_B051;
  localparam bit [31:0] ErrSlaveWord = 32'hBADC_AB1E;
  localparam bit [2:0] SberrorBus = 3'd2;
  localparam bit [2:0] SberrorAlign = 3'd3;
  localparam bit [2:0] SberrorSize = 3'd4;
  localparam bit [2:0] SbcsResetSbaccess = 3'd2;

  // Leaves the status at 0 where a capture or update finds an operation in
  // progress, so the captures that follow must disagree with the bridge.
  bit negative;

  protected bridge_t      m_bridge     [string];
  protected ocah_axi_item m_completed_q[string] [$];

  function new(bit negative = 1'b0);
    this.negative = negative;
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

  // The value a Capture-DR on TCK cycle `tck` loads, and the mask of its
  // known bits; 0 when the capture is outside the model's scope.
  function bit capture(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, int unsigned tck,
                       output bit [63:0] value, output bit [63:0] known);
    string     n = t.name;
    op_state_e state = op_state(t, tck, "capture");
    value = '0;
    known = '0;
    if (state == OP_UNKNOWN) return 1'b0;
    if (kind == DTP_J2A_SCAN_DTMCS) begin
      value = 64'(DtpExpectedDtmcs | (32'(m_bridge[n].error) << DtpDtmcsDmistatLsb));
      known = 64'hFFFF_FFFF;
      return 1'b1;
    end
    if (state == OP_IN_PROGRESS && m_bridge[n].op_read && !negative) set_busy(n);
    value = dtp_j2a_pack_dmi(m_bridge[n].address, m_bridge[n].data, m_bridge[n].error);
    known = dtp_j2a_pack_dmi('1, m_bridge[n].data_mask, '1);
    return 1'b1;
  endfunction

  // Update-DR of a DTMCS or DMI register on TCK cycle `tck`; 1 with
  // `launched` the bus transaction it starts. `value` is the update stage's
  // content and `known` the mask of its bits the model knows. Completions at
  // or before `visible` have reached the Debug Module; `gated` is the
  // bridge's lifecycle disable and `held` its response holds.
  function bit update(dtp_j2a_target_t t, dtp_j2a_scan_kind_e kind, bit [63:0] value,
                      bit [63:0] known, int unsigned tck, time visible, bit gated, holds_t held,
                      output ocah_axi_item launched);
    string        n = t.name;
    dtp_dmi_t     dmi;
    bit    [31:0] data_mask;
    op_state_e    state;
    launched = null;
    if (kind == DTP_J2A_SCAN_DTMCS) begin
      if (!require_known(t, known, 64'(1) << DtpDtmcsDmiresetBit, "dmireset")) return 1'b0;
      if (!value[DtpDtmcsDmiresetBit]) return 1'b0;
      dmi       = '{address: m_bridge[n].address, data: m_bridge[n].data, op: DTP_DMI_OP_CLEAR};
      data_mask = m_bridge[n].data_mask;
    end else begin
      if (!require_known(t, known, 64'h3, "op")) return 1'b0;
      dmi       = dtp_j2a_unpack_dmi(value);
      data_mask = dtp_j2a_unpack_dmi(known).data;
    end
    state = op_state(t, tck, "update");
    if (state == OP_UNKNOWN) return 1'b0;
    if (state == OP_IN_PROGRESS) begin
      if (dmi.op == DTP_DMI_OP_CLEAR) m_bridge[n].error = DTP_DMI_SUCCESS;
      else if (!negative) set_busy(n);
      return 1'b0;
    end
    apply_completions(t, visible);
    if (m_bridge[n].error != DTP_DMI_SUCCESS) begin
      if (dmi.op == DTP_DMI_OP_CLEAR) m_bridge[n].error = DTP_DMI_SUCCESS;
      return 1'b0;
    end
    m_bridge[n].address   = dmi.address;
    m_bridge[n].data      = dmi.data;
    m_bridge[n].data_mask = data_mask;
    if (dmi.op != DTP_DMI_OP_READ && dmi.op != DTP_DMI_OP_WRITE) return 1'b0;
    if (dmi.op == DTP_DMI_OP_WRITE) begin
      if (!require_known(t, 64'(data_mask), 64'hFFFF_FFFF, "write data")) return 1'b0;
    end
    m_bridge[n].last_op_tck   = tck;
    m_bridge[n].op_read       = (dmi.op == DTP_DMI_OP_READ);
    m_bridge[n].pending_valid = 1'b1;
    if (m_bridge[n].op_read) m_bridge[n].pending = dm_read(t, dmi.address, gated, held, launched);
    else m_bridge[n].pending = dm_write(t, dmi.address, dmi.data, gated, held, launched);
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
    b.last_op_tck    = 0;
    b.op_read        = 1'b0;
    b.pending_valid  = 1'b0;
    b.pending        = '{data: '0, data_mask: '0, busy: 1'b0};
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

  // Whether the read or write of the last update is in progress on TCK cycle
  // `tck`, OP_UNKNOWN between the busy and settle bounds. An operation found
  // complete has its response applied first.
  protected function op_state_e op_state(dtp_j2a_target_t t, int unsigned tck, string what);
    string        n = t.name;
    int unsigned  elapsed = tck - m_bridge[n].last_op_tck;
    dm_response_t rsp = m_bridge[n].pending;
    if (!m_bridge[n].pending_valid) return OP_IDLE;
    if (elapsed <= DtpDmiBusyTck) return OP_IN_PROGRESS;
    if (elapsed < DtpDmiSettleTck) begin
      scope_error(t, $sformatf(
                  "%s %0d TCK after a DMI read or write update, between the %0d-TCK busy and %0d-TCK settle bounds",
                  what,
                  elapsed,
                  DtpDmiBusyTck,
                  DtpDmiSettleTck
                  ));
      return OP_UNKNOWN;
    end
    m_bridge[n].pending_valid = 1'b0;
    if (m_bridge[n].op_read) begin
      m_bridge[n].data      = rsp.busy ? DataBusy : rsp.data;
      m_bridge[n].data_mask = rsp.busy ? '1 : rsp.data_mask;
    end
    if (rsp.busy) set_busy(n);
    return OP_IDLE;
  endfunction

  protected function void set_busy(string n);
    if (m_bridge[n].error == DTP_DMI_SUCCESS) m_bridge[n].error = DTP_DMI_BUSY;
  endfunction

  protected function bit require_known(dtp_j2a_target_t t, bit [63:0] known, bit [63:0] bits,
                                       string field);
    if ((known & bits) == bits) return 1'b1;
    scope_error(t, {"Update-DR ", field, " comes from captured bits without a contract"});
    return 1'b0;
  endfunction

  // Whether the hold of the outstanding access's direction keeps it
  // outstanding.
  protected function bit keeps(dtp_j2a_target_t t, holds_t held);
    return m_bridge[t.name].inflight_valid && (m_bridge[t.name].inflight.is_read ? held.r : held.b);
  endfunction

  // An outstanding access may complete before a DMI access reaches the Debug
  // Module unless a response hold keeps it outstanding; 0 with a scope error
  // then.
  protected function bit require_held(dtp_j2a_target_t t, holds_t held, string what);
    if (!m_bridge[t.name].inflight_valid || keeps(t, held)) return 1'b1;
    scope_error(t, {what, " while a bus access is outstanding"});
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

  // 1 when an sbaddress or sbdata access does not proceed: while a bus
  // access is outstanding or sbbusyerror is set it is a busy response, which
  // `rsp` returns, and it sets sbbusyerror.
  protected function bit sba_blocked(dtp_j2a_target_t t, bit [6:0] address, holds_t held,
                                     inout dm_response_t rsp);
    string n = t.name;
    if (!require_held(t, held, $sformatf("Debug Module register 0x%02h accessed", address)))
      return 1'b1;
    if (!m_bridge[n].inflight_valid && !m_bridge[n].ctrl.sbbusyerror) return 1'b0;
    m_bridge[n].ctrl.sbbusyerror = 1'b1;
    rsp.busy                     = 1'b1;
    return 1'b1;
  endfunction

  protected function dm_response_t dm_read(dtp_j2a_target_t t, bit [6:0] address, bit gated,
                                           holds_t held, output ocah_axi_item launched);
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
        // Debug Module unless a response hold keeps it outstanding.
        dtp_sbcs_t unknown = '0;
        if (m_bridge[n].dmactive && m_bridge[n].inflight_valid && !keeps(t, held)) begin
          unknown.sbbusy  = 1'b1;
          unknown.sberror = '1;
        end
        rsp.data      = sbcs_value(t);
        rsp.data_mask = ~32'(unknown);
      end
      DTP_DM_SBADDRESS0, DTP_DM_SBADDRESS1: begin
        if (!require_held(t, held, "sbaddress read")) return rsp;
        rsp.data      = 32'(m_bridge[n].sbaddr >> ((address == DTP_DM_SBADDRESS0) ? 0 : 32));
        rsp.data_mask = '1;
      end
      DTP_DM_SBDATA0, DTP_DM_SBDATA1: begin
        int unsigned shift = (address == DTP_DM_SBDATA0) ? 0 : 32;
        if (sba_blocked(t, address, held, rsp)) return rsp;
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
                                            bit gated, holds_t held, output ocah_axi_item launched);
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
        if (!require_held(t, held, "sbcs written")) return rsp;
        if (m_bridge[n].inflight_valid) begin
          m_bridge[n].ctrl.sbbusyerror = 1'b1;
          rsp.busy                     = 1'b1;
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
        if (sba_blocked(t, address, held, rsp) || !m_bridge[n].dmactive) return rsp;
        shift = (address == DTP_DM_SBADDRESS0) ? 0 : 32;
        m_bridge[n].sbaddr =
            ((m_bridge[n].sbaddr & ~(64'hFFFF_FFFF << shift)) | (64'(data) << shift)) &
            ocah_rng::bit_mask(t.addr_width);
        if (address == DTP_DM_SBADDRESS0 && m_bridge[n].ctrl.sbreadonaddr &&
            m_bridge[n].ctrl.sberror == 0)
          launched = launch(t, 1'b1, gated);
      end
      DTP_DM_SBDATA0, DTP_DM_SBDATA1: begin
        if (sba_blocked(t, address, held, rsp)) return rsp;
        shift = (address == DTP_DM_SBDATA0) ? 0 : 32;
        if (m_bridge[n].dmactive) begin
          m_bridge[n].sbdata =
              (m_bridge[n].sbdata & ~(64'hFFFF_FFFF << shift)) | (64'(data) << shift);
          m_bridge[n].sbdata_mask |= 64'hFFFF_FFFF << shift;
          if (address == DTP_DM_SBDATA0 && m_bridge[n].ctrl.sberror == 0)
            launched = launch(t, 1'b0, gated);
        end
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
// shared by the two JTAG2AXI reference models. A bridge register captures on
// the TCK cycle that leaves Capture-DR and updates on the one that leaves
// Update-DR, whatever the scan shifted in between, and the transaction an
// update launches is returned from on_event with the bridge's name. Each
// reconstructed scan of a bridge register yields its expected capture on the
// bits it shifted out when the PTAP 3DCR select is clear. The debug disable
// and the response holds of the bridge are read from dtp_tb_if on the update
// cycle.
class dtp_jtag2axi_tracker;

  virtual dtp_tb_if             tb_vif;
  dtp_jtag_ir_model             ir;
  dtp_jtag2axi_model            bridges;
  protected string              m_target_by_source[string];
  protected bit          [31:0] m_sys_rst_seen;
  protected int unsigned        m_tck;
  protected time                m_prev_step;
  // The bridge register captured in the DR scan in progress: its value and
  // known bits.
  protected bit                 m_captured;
  protected dtp_j2a_target_t    m_target;
  protected dtp_j2a_scan_kind_e m_kind;
  protected bit          [63:0] m_value;
  protected bit          [63:0] m_known;
  // Bits the scan in progress has shifted, and the TDI bits that end in the
  // register, LSB first.
  protected int unsigned        m_shift_bits;
  protected bit          [63:0] m_shift_tdi;

  function new(virtual dtp_tb_if tb_vif, bit negative = 1'b0);
    this.tb_vif = tb_vif;
    ir          = new();
    bridges     = new(negative);
  endfunction

  // Name the monitor whose items carry a bridge's transactions.
  function void bind_port(string target, string source);
    m_target_by_source[source] = target;
  endfunction

  // One reconstructed scan; its expected capture, or no contract.
  function dtp_jtag2axi_status_item on_scan(ocah_jtag_scan_item t);
    dtp_jtag2axi_status_item exp = dtp_jtag2axi_status_item::type_id::create("exp");
    int unsigned             width;
    int unsigned             kept;
    exp.compare   = 1'b0;
    exp.timestamp = t.end_time;
    sync_reset();
    if (t.is_ir) begin
      ir.on_ir_scan(t);
      return exp;
    end
    ir.on_dr_scan(t);
    if (!m_captured) return exp;
    width        = dtp_j2a_scan_len(m_kind);
    kept         = (t.bit_count < width) ? t.bit_count : width;
    m_shift_bits = t.bit_count;
    m_shift_tdi  = '0;
    for (int unsigned i = 0; i < kept; i++) m_shift_tdi[i] = t.tdi_bits[t.bit_count-kept+i];
    if (!ir.ptap_select_clear()) return exp;
    exp.compare   = 1'b1;
    exp.target    = m_target.name;
    exp.kind      = m_kind;
    exp.expected  = m_value;
    exp.mask      = m_known & ocah_rng::bit_mask(kept);
    exp.context_s = $sformatf("%s %s bits=%0d tdi=0x%0h", m_target.name, m_kind.name(),
                              t.bit_count, t.tdi_value());
    return exp;
  endfunction

  // One TCK event; 1 with the bridge and transaction an update on it
  // launches.
  function bit on_event(ocah_jtag_event t, output string target, output ocah_axi_item launched);
    bit started = 1'b0;
    launched = null;
    sync_reset();
    if (t.kind == OCAH_JTAG_EV_STEP && t.trst_n) begin
      m_tck++;
      if (ir.tap_state() == OCAH_JTAG_CAPTURE_DR) capture();
      else if (ir.tap_state() == OCAH_JTAG_UPDATE_DR && m_captured) begin
        target  = m_target.name;
        started = update(launched);
      end
      m_prev_step = t.timestamp;
    end
    void'(ir.on_event(t));
    if (ir.take_tap_reset()) m_captured = 1'b0;
    return started;
  endfunction

  function void on_axi(ocah_axi_item t);
    if (!m_target_by_source.exists(t.source))
      `uvm_fatal("dtp_jtag2axi_tracker", $sformatf("AXI item from unbound port `%s`", t.source))
    bridges.complete(m_target_by_source[t.source], t);
  endfunction

  protected function void capture();
    m_captured   = 1'b0;
    m_shift_bits = 0;
    m_shift_tdi  = '0;
    if (!ir.ir_known()) return;
    m_kind = dtp_j2a_classify_instr(ir.ir(), m_target);
    if (m_kind == DTP_J2A_SCAN_NONE) return;
    m_captured = bridges.capture(m_target, m_kind, m_tck, m_value, m_known);
  endfunction

  // The update stage loads the shift register: the captured value moved down
  // by the bits shifted, with the shifted TDI above it.
  protected function bit update(output ocah_axi_item launched);
    int unsigned                width = dtp_j2a_scan_len(m_kind);
    bit                  [63:0] mask = ocah_rng::bit_mask(width);
    bit                  [63:0] value;
    bit                  [63:0] known;
    dtp_jtag2axi_model::holds_t held;
    bit                         gated;
    m_captured = 1'b0;
    if (m_shift_bits >= width) begin
      value = m_shift_tdi;
      known = mask;
    end else begin
      value = ((m_value >> m_shift_bits) | (m_shift_tdi << (width - m_shift_bits))) & mask;
      known = ((m_known >> m_shift_bits) |
               (ocah_rng::bit_mask(m_shift_bits) << (width - m_shift_bits))) & mask;
    end
    held.b = tb_vif.j2a_b_hold[m_target.reset_arm_bit];
    held.r = tb_vif.j2a_r_hold[m_target.reset_arm_bit];
    gated  = dtp_dbg_path_disabled(tb_vif.dbg_disable, m_target.dbg_path);
    return bridges.update(
        m_target, m_kind, value, known, m_tck, m_prev_step, gated, held, launched
    );
  endfunction

  // Power-on reset resets the TAP; a system reset resets every bridge.
  protected function void sync_reset();
    void'(ir.sync_power_on_reset(tb_vif.por_assert_count));
    if (ir.take_tap_reset()) m_captured = 1'b0;
    if (tb_vif.sys_rst_assert_count !== m_sys_rst_seen) begin
      m_sys_rst_seen = tb_vif.sys_rst_assert_count;
      bridges.reset();
    end
  endfunction

endclass : dtp_jtag2axi_tracker
