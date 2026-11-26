// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI functional coverage: the DMI operations each bridge's DTM updates
// with the status their own scan captured, and the dmireset strobes with the
// sticky status they clear (cg_j2a_dmi_status); the Debug Module registers
// each bridge reads and writes with dmactive 0 and 1, and the sbcs writes
// that set a read-only bit (cg_j2a_dm_access); the size, byte offset and
// sbautoincrement of each bus access a bridge's Debug Module starts, and the
// autoincrements that carry into address bit 32 (cg_j2a_sba_access); the
// errors each Debug Module records from its bus accesses, and the DMI writes
// it acts on while it holds one (cg_j2a_sba_error); the DMI accesses each
// Debug Module refuses while a bus access is outstanding, with the sbcs
// polls before them (cg_j2a_busy); the READY waits,
// response latencies and AW/W order each bridge port sees, and the sbcs reads
// whose access completes while the read is in flight (cg_j2a_axi_timing);
// and each bridge's security demultiplexer: the side each request takes
// under each combination of the three disables, the Debug Module accesses
// and refused accesses while the error slave is selected, the changes of a
// disable with the transfer then open, the cycles the select holds against
// a changed disable while the bridge requests, and the select through and
// out of system reset (cg_j2a_dbg_disable); and each TAP reset with the
// state of each bridge, the phase of each bridge's access at the bridge
// reset, a response held past the poll bound at it, the scans in it, a
// bridge reset that a read's AR handshake asserts, its TCK-side release
// after TCK stopped, and test mode (cg_j2a_reset); and the length of each
// scan of a bridge register, and each DR update of another register and IR
// update with the state of each bridge then (cg_j2a_isolation).
//
// One instance in the shared tb_top serves both flows. Each bridge's DMI
// capture and update strobes, its captured status, the DMI value its bridge
// state machine receives, its DTMCS dmireset strobe and its Debug Module's
// dmactive come through hierarchical references into its jtag_dmi2axi, in
// the bit order of dtp_tb_if.j2a_b_hold (0 smc_axi, 1 smc_otp, 2 sep_otp).
// Every strobe is high for the one rising TCK edge that leaves Capture-DR or
// Update-DR, which is the edge each sample is taken on. The captured status
// includes the busy a capture during a read sets. A dmcontrol write sets
// dmactive before the next scan, so it is stable at that edge.
//
// The System Bus Access samples are taken on the bridges' system clock, from
// each Debug Module's request to its bus adapter: one when the adapter grants
// a request, and one in the cycle a completion's autoincrement moves the
// address bits above bit 31. The error samples are taken on the same clock:
// one in the cycle a Debug Module records an error, which for a bus error is
// the cycle of the B or R handshake that ends the access, and one for each
// DMI write it accepts while sberror is not 0, with the sbcs it then holds.
// The busy samples are taken on the same clock, one per DMI request a Debug
// Module receives and refuses while sbbusy is 1, with the sbcs reads it
// received since its last grant.
//
// The port timing samples are taken on the same clock from each bridge
// port's handshake signals, between the bridge and its responder. A port
// carries one transfer at a time, so one counter per channel and bridge
// measures it. The sbcs race samples are taken on TCK: the Update-DR of an
// sbcs read while sbbusy is 1 records the port's completed transfers, and the
// next DMI capture, which returns that read, is sampled with the sbbusy it
// returns when the port completed a transfer in between.
//
// The demultiplexer samples are taken on the system clock from each
// jtag_dmi2axi's select register, its synchronized disable input and the
// handshakes between its bridge and the demultiplexer. A transfer is open
// from its request handshake to its B or last R handshake, on the side the
// select held at the request.
//
// The reset samples are taken where each reset acts: on TCK for an entry to
// Test-Logic-Reset by TMS and for each DMI strobe while the bridge reset is
// asserted, at each fall of TRST, power-on reset, rst_n_i and scan_rst_ni,
// and on the system clock for port handshakes in test mode, for each
// bridge's TCK-side release, from its tdr2axi's synchronized resets, and for
// the release of an rst_n_i that fell in the cycle after an AR handshake at a
// bridge's port. A sample
// at a fall reads the state from before it, since every flop the reset
// clears updates after the sample. A bridge's access phase comes from its
// port's handshakes, its DMI state machine, its Debug Module's sbbusy and
// the last DMI operation its bridge accepted.
//
// The isolation samples are taken on TCK from each bridge's DTMCS and DMI
// scan selects and the TAP state: on the edge that leaves Update-DR, a scan
// of a bridge's own register with the Shift-DR edges it took, and every
// other DR update, for each bridge it did not select, with the bridge's
// Debug Module sbbusy; and on the edge that leaves Update-IR, the same for
// every bridge.
//
// Covergroups follow the cross rules dtp_fcov.sv states.
//
// CONVENTION: no declaration initializers on always_ff-driven variables,
// which VCS rejects (initializer_driver_checks); declare wires before use.

module dtp_j2a_fcov (
  input wire            tck_i,
  input wire            tap_rst_ni,
  input wire [2:0]      capture_en_i,
  input wire [2:0]      update_en_i,
  input wire [2:0]      dmireset_i,
  input wire [2:0][1:0] capture_status_i,
  // {address 40:34, data 33:2, op 1:0}
  input wire [2:0][40:0] update_dmi_i,
  input wire [2:0]      dmactive_i,
  input wire            clk_i,
  input wire            rst_ni,
  input wire [2:0]      sba_grant_i,
  input wire [2:0]      sba_write_i,
  input wire [2:0][2:0] sba_size_i,
  // The request address modulo the bridge's beat.
  input wire [2:0][2:0] sba_offset_i,
  input wire [2:0]      sba_autoinc_i,
  input wire [2:0]      sba_carry_i,
  input wire [2:0]      sba_error_valid_i,
  input wire [2:0][2:0] sba_error_i,
  input wire [2:0][1:0] sba_bresp_i,
  input wire [2:0][1:0] sba_rresp_i,
  input wire [2:0]      dm_req_i,
  // {address 40:34, op 33:32, data 31:0}
  input wire [2:0][40:0] dm_req_dmi_i,
  input wire [2:0][31:0] dm_sbcs_i,
  input wire [2:0]      dm_sbbusy_i,
  // sbcs sbbusy in each bridge's DMI capture data.
  input wire [2:0]      capture_sbbusy_i,
  input wire [2:0]      port_awvalid_i,
  input wire [2:0]      port_awready_i,
  input wire [2:0]      port_wvalid_i,
  input wire [2:0]      port_wready_i,
  input wire [2:0]      port_bvalid_i,
  input wire [2:0]      port_bready_i,
  input wire [2:0]      port_arvalid_i,
  input wire [2:0]      port_arready_i,
  input wire [2:0]      port_rvalid_i,
  input wire [2:0]      port_rready_i,
  // RLAST on smc_axi, 1 on the AXI4-Lite ports.
  input wire [2:0]      port_rlast_i,
  input wire [2:0]      sec_select_i,
  input wire [2:0]      sec_disable_i,
  input wire [2:0]      bridge_requesting_i,
  input wire [2:0]      bridge_aw_hs_i,
  input wire [2:0]      bridge_ar_hs_i,
  input wire [2:0]      bridge_done_i,
  input wire            por_ni,
  input wire            trst_ni,
  input wire [15:0]     tap_state_i,  // one-hot jtag_tap_pkg::tap_state_e
  input wire            test_en_i,
  input wire            scan_rst_ni,
  // Each bridge's resets synchronized to clk_i and to TCK.
  input wire [2:0]      arst_clk_ni,
  input wire [2:0]      arst_tck_ni,
  // Each bridge's DMI state machine is not idle, and its sticky DMI status is
  // not 0.
  input wire [2:0]      fsm_busy_i,
  input wire [2:0]      sticky_i,
  // Each bridge's DTMCS and DMI DR-scan selects.
  input wire [2:0]      dtmcs_select_i,
  input wire [2:0]      dmi_select_i
);

  localparam int unsigned Bridges = 3;
  // sbcs sbversion, sbbusy, sbasize and sbaccess128 to sbaccess8.
  localparam logic [31:0] SbcsReadOnly = 32'hE020_0FFF;
  localparam logic [6:0] AddrSbcs = 7'h38;
  localparam logic [6:0] AddrSbaddress0 = 7'h39;
  localparam logic [6:0] AddrSbaddress1 = 7'h3A;
  localparam logic [6:0] AddrSbdata0 = 7'h3C;
  localparam logic [6:0] AddrSbdata1 = 7'h3D;
  localparam logic [2:0] SberrorBus = 3'd2;
  localparam logic [2:0] SberrorAlign = 3'd3;
  localparam logic [2:0] SberrorSize = 3'd4;
  localparam logic [1:0] DmiOpRead = 2'd1;
  localparam logic [1:0] DmiOpWrite = 2'd2;
  // cg_j2a_axi_timing sample kinds.
  localparam logic [2:0] KindAwStall = 3'd0;
  localparam logic [2:0] KindWStall = 3'd1;
  localparam logic [2:0] KindArStall = 3'd2;
  localparam logic [2:0] KindBDelay = 3'd3;
  localparam logic [2:0] KindRDelay = 3'd4;
  localparam logic [2:0] KindWOrder = 3'd5;
  localparam logic [2:0] KindSbcsRace = 3'd6;
  // cg_j2a_dbg_disable sample kinds.
  localparam logic [2:0] KindDisAccess = 3'd0;
  localparam logic [2:0] KindDisMatrix = 3'd1;
  localparam logic [2:0] KindDisLive = 3'd2;
  localparam logic [2:0] KindDisRefused = 3'd3;
  localparam logic [2:0] KindDisSwitch = 3'd4;
  localparam logic [2:0] KindDisHeld = 3'd5;
  localparam logic [2:0] KindDisReset = 3'd6;
  localparam logic [2:0] KindDisResetSelect = 3'd7;
  // cg_j2a_reset sample kinds, TAP reset sources and access phases.
  localparam logic [2:0] KindRstTap = 3'd0;
  localparam logic [2:0] KindRstBridge = 3'd1;
  localparam logic [2:0] KindRstScan = 3'd2;
  localparam logic [2:0] KindRstTckStopped = 3'd3;
  localparam logic [2:0] KindRstTest = 3'd4;
  localparam logic [2:0] KindRstArmed = 3'd5;
  localparam logic [2:0] KindRstUnreleased = 3'd6;
  localparam logic [1:0] TapSourceTms = 2'd0;
  localparam logic [1:0] TapSourceTrst = 2'd1;
  localparam logic [1:0] TapSourcePor = 2'd2;
  localparam logic [2:0] PhaseLaunched = 3'd1;
  localparam logic [2:0] PhaseRequest = 3'd2;
  localparam logic [2:0] PhaseW = 3'd3;
  localparam logic [2:0] PhaseResponse = 3'd4;
  localparam logic [2:0] PhaseDone = 3'd5;
  // cg_j2a_isolation sample kinds, scan lengths and disturbing scans.
  localparam logic KindIsoLength = 1'b0;
  localparam logic KindIsoDisturb = 1'b1;
  localparam logic [1:0] LengthShort = 2'd0;
  localparam logic [1:0] LengthExact = 2'd1;
  localparam logic [1:0] LengthLonger = 2'd2;
  localparam logic [1:0] SourceOtherDmi = 2'd0;
  localparam logic [1:0] SourceOtherDtmcs = 2'd1;
  localparam logic [1:0] SourceNonBridge = 2'd2;
  localparam logic [1:0] SourceIr = 2'd3;
  localparam int unsigned DtmcsLen = 32;
  localparam int unsigned DmiLen = 41;
  // The synchronizer depth: clk_i cycles of a TCK-side release with TCK
  // stopped from which it counts as one.
  localparam int unsigned TckStoppedCycles = 3;
  // Cycles from which a READY wait or a response latency counts as long, and
  // the latency up to which a response counts as prompt.
  localparam int unsigned LongCycles = 64;
  localparam int unsigned PromptCycles = 2;
  // The sbcs polls a bench wait for sbbusy 0 makes at most.
  localparam int unsigned SbaPolls = 8;

  // The status each bridge's last DMI capture presented, which its next DMI
  // update closes the scan of.
  logic [Bridges-1:0][1:0] scan_status_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      scan_status_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (capture_en_i[b]) scan_status_q[b] <= capture_status_i[b];
      end
    end
  end

  // One sample per DMI update, with the op it carries and the status its own
  // capture presented, and one per dmireset, with the sticky status it
  // clears. The DMI defines no status 1, and this integration's Debug Module
  // never fails an access, so no status reads 2.
  covergroup cg_j2a_dmi_status with function sample (
      logic [1:0] bridge, logic dmireset, logic [1:0] op, logic [1:0] status
  );
    option.per_instance = 1;
    cp_bridge: coverpoint bridge {
      bins smc_axi = {2'd0};
      bins smc_otp = {2'd1};
      bins sep_otp = {2'd2};
      illegal_bins none = {2'd3};
    }
    cp_op: coverpoint op {
      bins nop = {2'd0}; bins read = {2'd1}; bins write = {2'd2}; bins clear = {2'd3};
    }
    cp_status: coverpoint status {
      bins success = {2'd0};
      bins busy = {2'd3};
      illegal_bins reserved = {2'd1};
      illegal_bins failed = {2'd2};
    }
    x_update: cross cp_bridge, cp_op, cp_status iff (!dmireset);
    x_dmireset: cross cp_bridge, cp_status iff (dmireset);
  endgroup

  // One sample per DMI update its bridge accepts, the one whose own capture
  // presented status 0, with the register it addresses, its op and the
  // dmactive it finds.
  covergroup cg_j2a_dm_access with function sample (
      logic [1:0] bridge, logic [6:0] address, logic [1:0] op, logic dmactive, logic ro_set
  );
    option.per_instance = 1;
    cp_bridge: coverpoint bridge {
      bins smc_axi = {2'd0};
      bins smc_otp = {2'd1};
      bins sep_otp = {2'd2};
      illegal_bins none = {2'd3};
    }
    cp_register: coverpoint address {
      bins dmcontrol = {7'h10};
      bins sbcs = {AddrSbcs};
      bins sbaddress0 = {7'h39};
      bins sbdata0 = {7'h3C};
    }
    cp_op: coverpoint op {bins read = {2'd1}; bins write = {2'd2};}
    cp_dmactive: coverpoint dmactive {bins inactive = {1'b0}; bins active = {1'b1};}
    // An active sbcs write that sets no read-only bit, or one that sets some.
    cp_sbcs_ro: coverpoint ro_set iff (address == AddrSbcs && op == 2'd2 && dmactive) {
      bins none = {1'b0}; bins some = {1'b1};
    }
    x_access: cross cp_bridge, cp_register, cp_op, cp_dmactive;
    x_sbcs_ro: cross cp_bridge, cp_sbcs_ro;
  endgroup

  // One sample per granted bus request, with its op, size, byte offset in the
  // beat and sbautoincrement, and one per completion whose autoincrement
  // carries into address bit 32, with the op it completes. A request is
  // aligned to its size and no wider than the bridge's beat, which is 8 bytes
  // on smc_axi and 4 on the OTP bridges; only smc_axi has address bits above
  // bit 31.
  covergroup cg_j2a_sba_access with function sample (
      logic [1:0] bridge,
      logic carry,
      logic write,
      logic [2:0] size,
      logic [2:0] offset,
      logic autoinc
  );
    option.per_instance = 1;
    cp_op: coverpoint write iff (!carry) {bins read = {1'b0}; bins write = {1'b1};}
    // 8 * bridge + size
    cp_size: coverpoint {
      bridge, size
    } iff (!carry) {
      bins smc_axi[] = {[0 : 3]};
      bins smc_otp[] = {[8 : 10]};
      bins sep_otp[] = {[16 : 18]};
      illegal_bins wider = {[4 : 7], [11 : 15], [19 : 31]};
    }
    // 64 * bridge + 8 * size + offset
    cp_lane: coverpoint {
      bridge, size, offset
    } iff (!carry) {
      bins smc_axi_byte1[] = {[0 : 7]};
      bins smc_axi_byte2[] = {8, 10, 12, 14};
      bins smc_axi_byte4[] = {16, 20};
      bins smc_axi_byte8 = {24};
      bins smc_otp_byte1[] = {[64 : 67]};
      bins smc_otp_byte2[] = {72, 74};
      bins smc_otp_byte4 = {80};
      bins sep_otp_byte1[] = {[128 : 131]};
      bins sep_otp_byte2[] = {136, 138};
      bins sep_otp_byte4 = {144};
      illegal_bins other = {
        9, 11, 13, 15, [17 : 19], [21 : 23], [25 : 63],
        [68 : 71], 73, [75 : 79], [81 : 127],
        [132 : 135], 137, [139 : 143], [145 : 255]
      };
    }
    cp_autoinc: coverpoint autoinc iff (!carry) {bins off = {1'b0}; bins on = {1'b1};}
    // {bridge, op} of a completion that carries into address bit 32.
    cp_carry: coverpoint {
      bridge, write
    } iff (carry) {
      bins smc_axi_read = {3'b00_0};
      bins smc_axi_write = {3'b00_1};
      illegal_bins narrow_address = {[3'b01_0 : 3'b11_1]};
    }
    x_lane: cross cp_lane, cp_op;
    x_autoinc: cross cp_size, cp_op, cp_autoinc;
  endgroup

  // One sample per error a bridge's Debug Module records, with the op and
  // response of the access a bus error ends, the op a size error refuses and
  // the sbautoincrement of either, and one per DMI write it acts on while it
  // holds an error, by kind: 0 an
  // sbdata0 write, 1 an sbaddress0 write with sbreadonaddr, 2 an sbcs write
  // whose sberror field is 0, 3 one whose sberror field is not. A bus error
  // follows only a SLVERR or DECERR, and the bus adapters report no other
  // error (7).
  covergroup cg_j2a_sba_error with function sample (
      logic [1:0] bridge,
      logic held,
      logic [2:0] code,
      logic write,
      logic [1:0] resp,
      logic [1:0] kind,
      logic autoinc
  );
    option.per_instance = 1;
    cp_code: coverpoint code iff (!held) {
      bins bus = {SberrorBus};
      bins size = {SberrorSize};
      ignore_bins alignment = {3'd3};
      illegal_bins other = {3'd0, 3'd1, [3'd5 : 3'd7]};
    }
    // 8 * bridge + 4 * op + response
    cp_bus: coverpoint {
      bridge, write, resp
    } iff (!held && code == SberrorBus) {
      bins smc_axi_read[] = {2, 3};
      bins smc_axi_write[] = {6, 7};
      bins smc_otp_read[] = {10, 11};
      bins smc_otp_write[] = {14, 15};
      bins sep_otp_read[] = {18, 19};
      bins sep_otp_write[] = {22, 23};
      illegal_bins okay = {0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20, 21};
      illegal_bins none = {[24 : 31]};
    }
    // 2 * bridge + op
    cp_size: coverpoint {
      bridge, write
    } iff (!held && code == SberrorSize) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    // 4 * bridge + kind
    cp_held: coverpoint {
      bridge, kind
    } iff (held) {
      bins smc_axi[] = {[0 : 3]};
      bins smc_otp[] = {[4 : 7]};
      bins sep_otp[] = {[8 : 11]};
      illegal_bins none = {[12 : 15]};
    }
    // 4 * bridge + 2 * size error + sbautoincrement
    cp_autoinc: coverpoint {
      bridge, code == SberrorSize, autoinc
    } iff (!held && (code == SberrorBus || code == SberrorSize)) {
      bins smc_axi[] = {[0 : 3]};
      bins smc_otp[] = {[4 : 7]};
      bins sep_otp[] = {[8 : 11]};
      illegal_bins none = {[12 : 15]};
    }
  endgroup

  // One sample per DMI request a bridge's Debug Module refuses while sbbusy
  // is 1, by kind (0 an sbcs write, 1 and 2 sbaddress0 and sbaddress1
  // writes, 3 and 4 sbdata0 and sbdata1 writes, 5 and 6 sbdata0 and sbdata1
  // reads), with the op of the outstanding access, whether sbbusyerror is
  // already set, and the sbcs reads since the access's grant. The poll bins
  // lie past SbaPolls.
  covergroup cg_j2a_busy with function sample (
      logic [1:0] bridge, logic [2:0] kind, logic write, logic sbbusyerror, logic [4:0] polls
  );
    option.per_instance = 1;
    // 16 * bridge + 2 * kind + op of the outstanding access
    cp_first: coverpoint {
      bridge, kind, write
    } iff (!sbbusyerror) {
      bins smc_axi[] = {[0 : 13]};
      bins smc_otp[] = {[16 : 29]};
      bins sep_otp[] = {[32 : 45]};
      illegal_bins none = {14, 15, 30, 31, 46, 47, [48 : 63]};
    }
    // 8 * bridge + kind
    cp_under_error: coverpoint {
      bridge, kind
    } iff (sbbusyerror) {
      bins smc_axi[] = {[0 : 6]};
      bins smc_otp[] = {[8 : 14]};
      bins sep_otp[] = {[16 : 22]};
      illegal_bins none = {7, 15, 23, [24 : 31]};
    }
    // 32 * bridge + polls
    cp_polls: coverpoint {
      bridge, polls
    } {
      bins smc_axi_9_to_12 = {[9 : 12]};
      bins smc_axi_13_to_16 = {[13 : 16]};
      bins smc_otp_9_to_12 = {[41 : 44]};
      bins smc_otp_13_to_16 = {[45 : 48]};
      bins sep_otp_9_to_12 = {[73 : 76]};
      bins sep_otp_13_to_16 = {[77 : 80]};
      ignore_bins within_bound = {[0 : 8], [32 : 40], [64 : 72]};
      ignore_bins longer = {[17 : 31], [49 : 63], [81 : 95]};
      illegal_bins none = {[96 : 127]};
    }
  endgroup

  // One sample per AW, W or AR handshake on a bridge port with the cycles
  // VALID waited for READY (0 none, 1 short, 2 long), one per first BVALID or
  // RVALID with the cycles since the request's last handshake (0 prompt, 1
  // short, 2 long), one per write with the order of its AW and W handshakes
  // (0 AW first, 1 W first, 2 the same cycle), and one per sbcs race with
  // the sbbusy the capture returns. The OTP bridges present W after AW, so
  // their AW and W handshakes share a cycle only by chance.
  covergroup cg_j2a_axi_timing with function sample (
      logic [1:0] bridge, logic [2:0] kind, logic [1:0] value
  );
    option.per_instance = 1;
    // 4 * bridge + bucket
    cp_aw_stall: coverpoint {
      bridge, value
    } iff (kind == KindAwStall) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    cp_w_stall: coverpoint {
      bridge, value
    } iff (kind == KindWStall) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    cp_ar_stall: coverpoint {
      bridge, value
    } iff (kind == KindArStall) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    cp_b_delay: coverpoint {
      bridge, value
    } iff (kind == KindBDelay) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    cp_r_delay: coverpoint {
      bridge, value
    } iff (kind == KindRDelay) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    // 4 * bridge + order
    cp_w_order: coverpoint {
      bridge, value
    } iff (kind == KindWOrder) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {4, 5};
      bins sep_otp[] = {8, 9};
      ignore_bins otp_same_cycle = {6, 10};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    // 2 * bridge + sbbusy
    cp_sbcs_race: coverpoint {
      bridge, value[0]
    } iff (kind == KindSbcsRace) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
  endgroup

  // One sample per request handshake between a bridge and its demultiplexer,
  // with the side the select sends it to and its op, and with the three
  // synchronized disables; one per DMI read or write the Debug Module
  // accepts and per alignment or size error it records while the error
  // slave is selected; one per change of a disable, by direction, with the
  // bridge's transfer then open (0 none, 1 at the port, 2 at the error
  // slave); one per cycle a bridge requests while its select differs from
  // its disable, with the disable; one per bridge at each system reset
  // release with its disable; and one per cycle in system reset with the
  // select.
  covergroup cg_j2a_dbg_disable with function sample (
      logic [1:0] bridge, logic [2:0] kind, logic [2:0] value
  );
    option.per_instance = 1;
    // 4 * bridge + 2 * error slave + write
    cp_access: coverpoint {
      bridge, value[1:0]
    } iff (kind == KindDisAccess) {
      bins smc_axi[] = {[0 : 3]};
      bins smc_otp[] = {[4 : 7]};
      bins sep_otp[] = {[8 : 11]};
      illegal_bins none = {[12 : 15]};
    }
    // 8 * bridge + disables (bit 0 smc_axi, 1 smc_otp, 2 sep_otp)
    cp_matrix: coverpoint {
      bridge, value
    } iff (kind == KindDisMatrix) {
      bins smc_axi[] = {[0 : 7]};
      bins smc_otp[] = {[8 : 15]};
      bins sep_otp[] = {[16 : 23]};
      illegal_bins none = {[24 : 31]};
    }
    // 2 * bridge + write
    cp_live: coverpoint {
      bridge, value[0]
    } iff (kind == KindDisLive) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    // 8 * bridge + sberror
    cp_refused: coverpoint {
      bridge, value
    } iff (kind == KindDisRefused) {
      bins smc_axi[] = {3, 4};
      bins smc_otp[] = {11, 12};
      bins sep_otp[] = {19, 20};
      illegal_bins other = {[0 : 2], [5 : 10], [13 : 18], [21 : 31]};
    }
    // 8 * bridge + 4 * set + open transfer
    cp_switch: coverpoint {
      bridge, value
    } iff (kind == KindDisSwitch) {
      bins smc_axi_clear[] = {0, 2};
      bins smc_axi_set[] = {4, 5};
      bins smc_otp_clear[] = {8, 10};
      bins smc_otp_set[] = {12, 13};
      bins sep_otp_clear[] = {16, 18};
      bins sep_otp_set[] = {20, 21};
      // A disable that clears while a port transfer is open, or sets while
      // an error slave transfer is open, changes twice within one transfer.
      ignore_bins changed_twice = {1, 6, 9, 14, 17, 22};
      illegal_bins none = {3, 7, 11, 15, 19, 23, [24 : 31]};
    }
    // 2 * bridge + disable
    cp_held: coverpoint {
      bridge, value[0]
    } iff (kind == KindDisHeld) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    // 2 * bridge + disable
    cp_reset: coverpoint {
      bridge, value[0]
    } iff (kind == KindDisReset) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    cp_reset_select: coverpoint value[0] iff (kind == KindDisResetSelect) {
      bins error_slave = {1'b1}; illegal_bins port = {1'b0};
    }
  endgroup

  // One sample per bridge at each TAP reset, with its source (0 TMS, 1 TRST,
  // 2 power-on reset) and the bridge's state (0 idle, 1 an access open at
  // its port, 2 the sticky status set); one per bridge at each fall of
  // rst_n_i outside test mode, with the op and phase of its access (0 none,
  // 1 started and not at the port, 2 request pending, 3 write data pending,
  // 4 response pending, 5 completed at the port with no DMI operation since
  // the one that started it), and again with its op when the response has
  // been pending through more than SbaPolls sbcs reads with sbbusy 1; one per
  // DMI capture, DMI update and dmireset while the bridge reset is asserted;
  // one per bridge at the release of an rst_n_i that fell outside test mode
  // in the cycle after an AR handshake at its port, with whether a DMI strobe
  // came while it was asserted; one per bridge whose TCK-side reset releases
  // outside test mode after TCK stayed stopped for TckStoppedCycles past its
  // clk_i-side release; and in test mode one per
  // bridge for each request handshake at its port and each fall of rst_n_i
  // and of scan_rst_ni.
  covergroup cg_j2a_reset with function sample (
      logic [1:0] bridge, logic [2:0] kind, logic [3:0] value
  );
    option.per_instance = 1;
    // 16 * bridge + 4 * source + state
    cp_tap: coverpoint {
      bridge, value
    } iff (kind == KindRstTap) {
      bins smc_axi[] = {[0 : 2], [4 : 6], [8 : 10]};
      bins smc_otp[] = {[16 : 18], [20 : 22], [24 : 26]};
      bins sep_otp[] = {[32 : 34], [36 : 38], [40 : 42]};
      illegal_bins none = {3, 7, 11, [12 : 15], 19, 23, 27, [28 : 31], 35, 39, 43, [44 : 63]};
    }
    // 16 * bridge + 8 * write + phase
    cp_bridge: coverpoint {
      bridge, value
    } iff (kind == KindRstBridge) {
      bins smc_axi_read[] = {1, 2, 4, 5};
      bins smc_axi_write[] = {[9 : 13]};
      bins smc_otp_read[] = {17, 18, 20, 21};
      bins smc_otp_write[] = {[25 : 29]};
      bins sep_otp_read[] = {33, 34, 36, 37};
      bins sep_otp_write[] = {[41 : 45]};
      ignore_bins idle = {0, 16, 32};
      illegal_bins none = {
        3, [6 : 8], [14 : 15], 19, [22 : 24], [30 : 31], 35, [38 : 40], [46 : 63]
      };
    }
    // 4 * bridge + strobe (0 DMI capture, 1 DMI update, 2 dmireset)
    cp_scan: coverpoint {
      bridge, value[1:0]
    } iff (kind == KindRstScan) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
    cp_tck_stopped: coverpoint bridge iff (kind == KindRstTckStopped) {
      bins smc_axi = {2'd0};
      bins smc_otp = {2'd1};
      bins sep_otp = {2'd2};
      illegal_bins none = {2'd3};
    }
    // 2 * bridge + a DMI strobe while asserted
    cp_armed: coverpoint {
      bridge, value[0]
    } iff (kind == KindRstArmed) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    // 2 * bridge + op
    cp_unreleased: coverpoint {
      bridge, value[0]
    } iff (kind == KindRstUnreleased) {
      bins smc_axi[] = {0, 1};
      bins smc_otp[] = {2, 3};
      bins sep_otp[] = {4, 5};
      illegal_bins none = {6, 7};
    }
    // 4 * bridge + event (0 request handshake, 1 rst_n_i fall, 2 scan_rst_ni
    // fall)
    cp_test_mode: coverpoint {
      bridge, value[1:0]
    } iff (kind == KindRstTest) {
      bins smc_axi[] = {[0 : 2]};
      bins smc_otp[] = {[4 : 6]};
      bins sep_otp[] = {[8 : 10]};
      illegal_bins none = {3, 7, 11, [12 : 15]};
    }
  endgroup

  covergroup cg_j2a_isolation with function sample (
      logic kind, logic [1:0] bridge, logic [2:0] value
  );
    option.per_instance = 1;
    // 8 * bridge + 4 * DTMCS + length against the register's
    cp_length: coverpoint {
      bridge, value
    } iff (kind == KindIsoLength) {
      bins smc_axi[] = {1, 2, 5, 6};
      bins smc_otp[] = {9, 10, 13, 14};
      bins sep_otp[] = {17, 18, 21, 22};
      ignore_bins shorter = {0, 4, 8, 12, 16, 20};
      illegal_bins none = {3, 7, 11, 15, 19, 23, [24 : 31]};
    }
    // 8 * bridge + 2 * source + sbbusy
    cp_disturb: coverpoint {
      bridge, value
    } iff (kind == KindIsoDisturb) {
      bins smc_axi[] = {[0 : 7]};
      bins smc_otp[] = {[8 : 15]};
      bins sep_otp[] = {[16 : 23]};
      illegal_bins none = {[24 : 31]};
    }
  endgroup

  cg_j2a_dmi_status u_cg_j2a_dmi_status = new();
  cg_j2a_dm_access u_cg_j2a_dm_access = new();
  cg_j2a_sba_access u_cg_j2a_sba_access = new();
  cg_j2a_sba_error u_cg_j2a_sba_error = new();
  cg_j2a_busy u_cg_j2a_busy = new();
  cg_j2a_axi_timing u_cg_j2a_axi_timing = new();
  cg_j2a_dbg_disable u_cg_j2a_dbg_disable = new();
  cg_j2a_reset u_cg_j2a_reset = new();
  cg_j2a_isolation u_cg_j2a_isolation = new();

  always_ff @(posedge tck_i) begin
    if (tap_rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (update_en_i[b]) begin
          u_cg_j2a_dmi_status.sample(2'(b), 1'b0, update_dmi_i[b][1:0], scan_status_q[b]);
          if (scan_status_q[b] == 2'd0)
            u_cg_j2a_dm_access.sample(2'(b), update_dmi_i[b][40:34], update_dmi_i[b][1:0],
                                      dmactive_i[b], |(update_dmi_i[b][33:2] & SbcsReadOnly));
        end
        if (dmireset_i[b]) u_cg_j2a_dmi_status.sample(2'(b), 1'b1, 2'd3, capture_status_i[b]);
      end
    end
  end

  // The op of each bridge's last granted request, which its completion
  // closes.
  logic [Bridges-1:0] sba_write_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      sba_write_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (sba_grant_i[b]) sba_write_q[b] <= sba_write_i[b];
      end
    end
  end

  // A DMI write each bridge's Debug Module acts on while it holds an error,
  // and its kind in cg_j2a_sba_error.
  logic [Bridges-1:0]      held_valid;
  logic [Bridges-1:0][1:0] held_kind;

  always_comb begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      // sbcs bits 14:12 sberror, 20 sbreadonaddr, 22 sbbusyerror.
      held_valid[b] = dm_req_i[b] && dm_req_dmi_i[b][33:32] == 2'd2 && dmactive_i[b] &&
          dm_sbcs_i[b][14:12] != '0 && !dm_sbcs_i[b][22] && !dm_sbbusy_i[b];
      held_kind[b] = 2'd0;
      case (dm_req_dmi_i[b][40:34])
        AddrSbdata0: held_kind[b] = 2'd0;
        AddrSbaddress0: begin
          held_kind[b] = 2'd1;
          held_valid[b] &= dm_sbcs_i[b][20];
        end
        AddrSbcs: held_kind[b] = {1'b1, dm_req_dmi_i[b][14:12] != '0};
        default: held_valid[b] = 1'b0;
      endcase
    end
  end

  // The kind cg_j2a_busy records for a Debug Module request, with bit 3 set
  // for the kinds it refuses while sbbusy is 1.
  function automatic logic [3:0] busy_kind(logic [40:0] dmi);
    logic read;
    logic write;
    read  = dmi[33:32] == DmiOpRead;
    write = dmi[33:32] == DmiOpWrite;
    case (dmi[40:34])
      AddrSbcs: return {write, 3'd0};
      AddrSbaddress0: return {write, 3'd1};
      AddrSbaddress1: return {write, 3'd2};
      AddrSbdata0: return read ? {1'b1, 3'd5} : {write, 3'd3};
      AddrSbdata1: return read ? {1'b1, 3'd6} : {write, 3'd4};
      default: return '0;
    endcase
  endfunction

  // Per bridge: the sbcs reads its Debug Module received with sbbusy 1 since
  // its last grant, saturating.
  logic [Bridges-1:0][4:0] busy_polls_q;

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      busy_polls_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (sba_grant_i[b]) busy_polls_q[b] <= '0;
        else if (dm_req_i[b] && dm_sbbusy_i[b] && dm_req_dmi_i[b][40:34] == AddrSbcs &&
                 dm_req_dmi_i[b][33:32] == DmiOpRead && busy_polls_q[b] != '1)
          busy_polls_q[b] <= busy_polls_q[b] + 5'd1;
      end
    end
  end

  // The request each bridge's Debug Module refuses this cycle for sbbusy, as
  // busy_kind returns it.
  logic [Bridges-1:0][3:0] busy_req;

  always_comb begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      busy_req[b] = dm_req_i[b] && dm_sbbusy_i[b] ? busy_kind(dm_req_dmi_i[b]) : '0;
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (busy_req[b][3])
          u_cg_j2a_busy.sample(2'(b), busy_req[b][2:0], sba_write_q[b], dm_sbcs_i[b][22],
                               busy_polls_q[b]);
        if (sba_grant_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b0, sba_write_i[b], sba_size_i[b], sba_offset_i[b],
                                     sba_autoinc_i[b]);
        if (sba_carry_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b1, sba_write_q[b], sba_size_i[b], '0, 1'b1);
        if (sba_error_valid_i[b])
          u_cg_j2a_sba_error.sample(2'(b), 1'b0, sba_error_i[b],
                                    sba_error_i[b] == SberrorBus ? sba_write_q[b] : sba_write_i[b],
                                    sba_write_q[b] ? sba_bresp_i[b] : sba_rresp_i[b], '0,
                                    sba_autoinc_i[b]);
        if (held_valid[b]) u_cg_j2a_sba_error.sample(2'(b), 1'b1, '0, 1'b0, '0, held_kind[b], 1'b0);
      end
    end
  end

  function automatic logic [1:0] wait_bucket(logic [31:0] cycles, int unsigned prompt);
    if (cycles >= LongCycles) return 2'd2;
    if (cycles > prompt) return 2'd1;
    return 2'd0;
  endfunction

  // Per bridge port: the cycles the pending AW, W and AR VALID has waited,
  // the request handshakes of the transfer in flight and the cycles its
  // response has taken, and the transfers the port completed.
  logic [Bridges-1:0][31:0] aw_wait_q;
  logic [Bridges-1:0][31:0] w_wait_q;
  logic [Bridges-1:0][31:0] ar_wait_q;
  logic [Bridges-1:0][31:0] b_wait_q;
  logic [Bridges-1:0][31:0] r_wait_q;
  logic [Bridges-1:0]       aw_seen_q;
  logic [Bridges-1:0]       w_seen_q;
  logic [Bridges-1:0]       ar_seen_q;
  logic [Bridges-1:0]       b_sampled_q;
  logic [Bridges-1:0]       r_sampled_q;
  logic [Bridges-1:0][31:0] done_count_q;
  logic [Bridges-1:0]       aw_hs;
  logic [Bridges-1:0]       w_hs;
  logic [Bridges-1:0]       ar_hs;
  logic [Bridges-1:0]       b_hs;
  logic [Bridges-1:0]       r_hs;

  always_comb begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      aw_hs[b] = port_awvalid_i[b] && port_awready_i[b];
      w_hs[b]  = port_wvalid_i[b] && port_wready_i[b];
      ar_hs[b] = port_arvalid_i[b] && port_arready_i[b];
      b_hs[b]  = port_bvalid_i[b] && port_bready_i[b];
      r_hs[b]  = port_rvalid_i[b] && port_rready_i[b] && port_rlast_i[b];
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      aw_wait_q    <= '0;
      w_wait_q     <= '0;
      ar_wait_q    <= '0;
      b_wait_q     <= '0;
      r_wait_q     <= '0;
      aw_seen_q    <= '0;
      w_seen_q     <= '0;
      ar_seen_q    <= '0;
      b_sampled_q  <= '0;
      r_sampled_q  <= '0;
      done_count_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        aw_wait_q[b] <= (port_awvalid_i[b] && !aw_hs[b]) ? aw_wait_q[b] + 32'd1 : '0;
        w_wait_q[b]  <= (port_wvalid_i[b] && !w_hs[b]) ? w_wait_q[b] + 32'd1 : '0;
        ar_wait_q[b] <= (port_arvalid_i[b] && !ar_hs[b]) ? ar_wait_q[b] + 32'd1 : '0;
        if (b_hs[b]) begin
          aw_seen_q[b]   <= 1'b0;
          w_seen_q[b]    <= 1'b0;
          b_wait_q[b]    <= '0;
          b_sampled_q[b] <= 1'b0;
        end else begin
          aw_seen_q[b] <= aw_seen_q[b] || aw_hs[b];
          w_seen_q[b]  <= w_seen_q[b] || w_hs[b];
          if (aw_seen_q[b] && w_seen_q[b] && !port_bvalid_i[b]) b_wait_q[b] <= b_wait_q[b] + 32'd1;
          if (aw_seen_q[b] && w_seen_q[b] && port_bvalid_i[b]) b_sampled_q[b] <= 1'b1;
        end
        if (r_hs[b]) begin
          ar_seen_q[b]   <= 1'b0;
          r_wait_q[b]    <= '0;
          r_sampled_q[b] <= 1'b0;
        end else begin
          ar_seen_q[b] <= ar_seen_q[b] || ar_hs[b];
          if (ar_seen_q[b] && !port_rvalid_i[b]) r_wait_q[b] <= r_wait_q[b] + 32'd1;
          if (ar_seen_q[b] && port_rvalid_i[b]) r_sampled_q[b] <= 1'b1;
        end
        if (b_hs[b] || r_hs[b]) done_count_q[b] <= done_count_q[b] + 32'd1;
      end
    end
  end

  always_ff @(posedge clk_i) begin
    if (rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (aw_hs[b]) u_cg_j2a_axi_timing.sample(2'(b), KindAwStall, wait_bucket(aw_wait_q[b], 0));
        if (w_hs[b]) u_cg_j2a_axi_timing.sample(2'(b), KindWStall, wait_bucket(w_wait_q[b], 0));
        if (ar_hs[b]) u_cg_j2a_axi_timing.sample(2'(b), KindArStall, wait_bucket(ar_wait_q[b], 0));
        if (aw_seen_q[b] && w_seen_q[b] && port_bvalid_i[b] && !b_sampled_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindBDelay, wait_bucket(b_wait_q[b], PromptCycles));
        if (ar_seen_q[b] && port_rvalid_i[b] && !r_sampled_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindRDelay, wait_bucket(r_wait_q[b], PromptCycles));
        if (aw_hs[b] && w_hs[b] && !aw_seen_q[b] && !w_seen_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindWOrder, 2'd2);
        else if (aw_hs[b] && w_seen_q[b] && !aw_seen_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindWOrder, 2'd1);
        else if (w_hs[b] && aw_seen_q[b] && !w_seen_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindWOrder, 2'd0);
      end
    end
  end

  // Per bridge: whether the last DMI update was an sbcs read issued while
  // sbbusy is 1, which the next capture returns, and the port's completed
  // transfers at that Update-DR.
  logic [Bridges-1:0]       race_armed_q;
  logic [Bridges-1:0][31:0] race_done_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      race_armed_q <= '0;
      race_done_q  <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (update_en_i[b]) begin
          race_armed_q[b] <= update_dmi_i[b][1:0] == DmiOpRead &&
              update_dmi_i[b][40:34] == AddrSbcs && dm_sbbusy_i[b];
          race_done_q[b] <= done_count_q[b];
        end else if (capture_en_i[b]) begin
          race_armed_q[b] <= 1'b0;
        end
      end
    end
  end

  always_ff @(posedge tck_i) begin
    if (tap_rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (capture_en_i[b] && race_armed_q[b] && done_count_q[b] != race_done_q[b])
          u_cg_j2a_axi_timing.sample(2'(b), KindSbcsRace, {1'b0, capture_sbbusy_i[b]});
      end
    end
  end

  // Per bridge: its disable a cycle ago, and whether a transfer is open and
  // on which side; and whether the last cycle was in system reset.
  logic [Bridges-1:0] sec_disable_q;
  logic [Bridges-1:0] open_q;
  logic [Bridges-1:0] open_err_q;
  logic               in_reset_q;

  always_ff @(posedge clk_i) begin
    sec_disable_q <= sec_disable_i;
    in_reset_q    <= !rst_ni;
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      open_q     <= '0;
      open_err_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (bridge_aw_hs_i[b] || bridge_ar_hs_i[b]) begin
          open_q[b]     <= 1'b1;
          open_err_q[b] <= sec_select_i[b];
        end else if (bridge_done_i[b]) begin
          open_q[b] <= 1'b0;
        end
      end
    end
  end

  logic [Bridges-1:0][1:0] open_phase;

  always_comb begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      open_phase[b] = open_q[b] ? {open_err_q[b], !open_err_q[b]} : 2'd0;
    end
  end

  always_ff @(posedge clk_i) begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (!rst_ni && in_reset_q)
        u_cg_j2a_dbg_disable.sample(2'(b), KindDisResetSelect, {2'b0, sec_select_i[b]});
      if (rst_ni && in_reset_q)
        u_cg_j2a_dbg_disable.sample(2'(b), KindDisReset, {2'b0, sec_disable_i[b]});
      if (rst_ni && !in_reset_q) begin
        if (bridge_aw_hs_i[b] || bridge_ar_hs_i[b]) begin
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisAccess, {
                                      1'b0, sec_select_i[b], bridge_aw_hs_i[b]});
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisMatrix, sec_disable_i);
        end
        if (sec_select_i[b] && dm_req_i[b] && dm_req_dmi_i[b][33:32] inside {2'd1, 2'd2})
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisLive, {2'b0, dm_req_dmi_i[b][33]});
        if (sec_select_i[b] && sba_error_valid_i[b] && sba_error_i[b] inside {SberrorAlign,
                                                                              SberrorSize})
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisRefused, sba_error_i[b]);
        if (sec_disable_i[b] != sec_disable_q[b])
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisSwitch, {sec_disable_i[b], open_phase[b]});
        if (bridge_requesting_i[b] && sec_select_i[b] != sec_disable_i[b])
          u_cg_j2a_dbg_disable.sample(2'(b), KindDisHeld, {2'b0, sec_disable_i[b]});
      end
    end
  end

  // The reset the bridges synchronize: scan_rst_ni in test mode, rst_n_i
  // outside it.
  logic bridge_rst_n;
  assign bridge_rst_n = test_en_i ? scan_rst_ni : rst_ni;

  // Whether the PTAP was in Test-Logic-Reset at the last TCK edge, and a bit
  // that changes on every TCK edge.
  logic tap_tlr_q;
  logic tck_toggle_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      tap_tlr_q    <= 1'b1;
      tck_toggle_q <= 1'b0;
    end else begin
      tap_tlr_q    <= tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET;
      tck_toggle_q <= !tck_toggle_q;
    end
  end

  // 1 for a DMI update that starts a bus read, 2 for one that starts a bus
  // write, 0 otherwise. sbcs bit 20 is sbreadonaddr and bit 15 sbreadondata.
  function automatic logic [1:0] starts_access(logic [40:0] dmi, logic [31:0] sbcs);
    if (dmi[1:0] == DmiOpWrite && dmi[40:34] == AddrSbdata0) return 2'd2;
    if (dmi[1:0] == DmiOpWrite && dmi[40:34] == AddrSbaddress0 && sbcs[20]) return 2'd1;
    if (dmi[1:0] == DmiOpRead && dmi[40:34] == AddrSbdata0 && sbcs[15]) return 2'd1;
    return 2'd0;
  endfunction

  // Per bridge: the bus access the last DMI update other than a NOP starts,
  // as starts_access returns it for an update its own capture presented
  // status 0 to, and a bit that changes with each such update.
  logic [Bridges-1:0][1:0] start_op_q;
  logic [Bridges-1:0]      op_toggle_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      start_op_q  <= '0;
      op_toggle_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (update_en_i[b] && update_dmi_i[b][1:0] != 2'd0) begin
          start_op_q[b] <= scan_status_q[b] == 2'd0 ?
              starts_access(update_dmi_i[b], dm_sbcs_i[b]) : 2'd0;
          op_toggle_q[b] <= !op_toggle_q[b];
        end
      end
    end
  end

  // Per bridge, on clk_i: op_toggle_q and its TCK-side reset a cycle ago;
  // whether its port completed a transfer since the last change of
  // op_toggle_q; and, while its clk_i-side reset is released and its
  // TCK-side reset is not, the cycles before the first TCK edge and whether
  // that edge has come.
  logic [Bridges-1:0]       op_toggle_seen_q;
  logic                     tck_toggle_seen_q;
  logic [Bridges-1:0]       arst_tck_q;
  logic [Bridges-1:0]       done_since_op_q;
  logic [Bridges-1:0]       tck_ran_q;
  logic [Bridges-1:0][31:0] tck_stopped_q;

  always_ff @(posedge clk_i) begin
    op_toggle_seen_q  <= op_toggle_q;
    tck_toggle_seen_q <= tck_toggle_q;
    arst_tck_q        <= arst_tck_ni;
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (!arst_clk_ni[b]) begin
        tck_ran_q[b]     <= 1'b0;
        tck_stopped_q[b] <= '0;
      end else if (!arst_tck_ni[b]) begin
        if (tck_toggle_q != tck_toggle_seen_q) tck_ran_q[b] <= 1'b1;
        else if (!tck_ran_q[b]) tck_stopped_q[b] <= tck_stopped_q[b] + 32'd1;
      end
    end
  end

  always_ff @(posedge clk_i or negedge rst_ni) begin
    if (!rst_ni) begin
      done_since_op_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (op_toggle_q[b] != op_toggle_seen_q[b]) done_since_op_q[b] <= 1'b0;
        else if (b_hs[b] || r_hs[b]) done_since_op_q[b] <= 1'b1;
      end
    end
  end

  // The state cp_tap records for bridge b.
  function automatic logic [1:0] tap_reset_state(int unsigned b);
    if (sticky_i[b]) return 2'd2;
    if (port_awvalid_i[b] || port_wvalid_i[b] || port_arvalid_i[b] || aw_seen_q[b] ||
        w_seen_q[b] || ar_seen_q[b])
      return 2'd1;
    return 2'd0;
  endfunction

  function automatic void sample_tap_reset(logic [1:0] source);
    for (int unsigned b = 0; b < Bridges; b++) begin
      u_cg_j2a_reset.sample(2'(b), KindRstTap, {source, tap_reset_state(b)});
    end
  endfunction

  // The op (bit 3, 1 a write) and phase cp_bridge records for bridge b.
  function automatic logic [3:0] access_phase(int unsigned b);
    if (ar_seen_q[b]) return {1'b0, PhaseResponse};
    if (port_arvalid_i[b]) return {1'b0, PhaseRequest};
    if (aw_seen_q[b] && w_seen_q[b]) return {1'b1, PhaseResponse};
    if (aw_seen_q[b]) return {1'b1, PhaseW};
    if (port_awvalid_i[b] || port_wvalid_i[b] || w_seen_q[b]) return {1'b1, PhaseRequest};
    if (start_op_q[b] == 2'd0) return '0;
    if (done_since_op_q[b]) return {start_op_q[b] == 2'd2, PhaseDone};
    if (fsm_busy_i[b] || dm_sbbusy_i[b]) return {start_op_q[b] == 2'd2, PhaseLaunched};
    return '0;
  endfunction

  // Whether bridge b's access has its response pending at the port.
  function automatic logic response_pending(int unsigned b);
    return ar_seen_q[b] || (aw_seen_q[b] && w_seen_q[b]);
  endfunction

  always_ff @(posedge tck_i) begin
    if (tap_rst_ni && tap_state_i == jtag_tap_pkg::TEST_LOGIC_RESET && !tap_tlr_q)
      sample_tap_reset(TapSourceTms);
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (!bridge_rst_n) begin
        if (capture_en_i[b]) u_cg_j2a_reset.sample(2'(b), KindRstScan, 4'd0);
        if (update_en_i[b]) u_cg_j2a_reset.sample(2'(b), KindRstScan, 4'd1);
        if (dmireset_i[b]) u_cg_j2a_reset.sample(2'(b), KindRstScan, 4'd2);
      end
    end
  end

  always @(negedge trst_ni) begin
    if (por_ni === 1'b1) sample_tap_reset(TapSourceTrst);
  end

  always @(negedge por_ni) begin
    if (trst_ni === 1'b1) sample_tap_reset(TapSourcePor);
  end

  always @(negedge rst_ni) begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (test_en_i) begin
        u_cg_j2a_reset.sample(2'(b), KindRstTest, 4'd1);
      end else begin
        u_cg_j2a_reset.sample(2'(b), KindRstBridge, access_phase(b));
        if (response_pending(b) && busy_polls_q[b] > SbaPolls)
          u_cg_j2a_reset.sample(2'(b), KindRstUnreleased, {3'b0, aw_seen_q[b]});
      end
    end
  end

  always @(negedge scan_rst_ni) begin
    if (test_en_i) begin
      for (int unsigned b = 0; b < Bridges; b++) u_cg_j2a_reset.sample(2'(b), KindRstTest, 4'd2);
    end
  end

  always_ff @(posedge clk_i) begin
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (test_en_i && rst_ni && (aw_hs[b] || ar_hs[b]))
        u_cg_j2a_reset.sample(2'(b), KindRstTest, 4'd0);
      if (!test_en_i && arst_tck_ni[b] && !arst_tck_q[b] && tck_stopped_q[b] >= TckStoppedCycles)
        u_cg_j2a_reset.sample(2'(b), KindRstTckStopped, '0);
    end
  end

  // Per bridge, on TCK: the DMI strobes while the bridge reset is asserted.
  logic [Bridges-1:0][7:0] rst_scan_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      rst_scan_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (!bridge_rst_n && (capture_en_i[b] || update_en_i[b] || dmireset_i[b]))
          rst_scan_q[b] <= rst_scan_q[b] + 8'd1;
      end
    end
  end

  // On clk_i: rst_n_i and each port's AR handshake at the last edge, and per
  // bridge whether the rst_n_i assertion in progress fell outside test mode
  // in the cycle after an AR handshake at its port, with rst_scan_q then.
  logic                    rst_q;
  logic [Bridges-1:0]      ar_hs_q;
  logic [Bridges-1:0]      armed_q;
  logic [Bridges-1:0][7:0] armed_scan_q;

  always_ff @(posedge clk_i) begin
    rst_q   <= rst_ni;
    ar_hs_q <= ar_hs;
    for (int unsigned b = 0; b < Bridges; b++) begin
      if (!test_en_i && !rst_ni && rst_q && ar_hs_q[b]) begin
        armed_q[b]      <= 1'b1;
        armed_scan_q[b] <= rst_scan_q[b];
      end else if (rst_ni) begin
        armed_q[b] <= 1'b0;
      end
      if (rst_ni && !rst_q && armed_q[b])
        u_cg_j2a_reset.sample(2'(b), KindRstArmed, {3'b0, rst_scan_q[b] != armed_scan_q[b]});
    end
  end

  // Per bridge, the Shift-DR edges the scan in progress of its selected
  // register has taken, saturating.
  logic [Bridges-1:0][7:0] shift_count_q;

  always_ff @(posedge tck_i or negedge tap_rst_ni) begin
    if (!tap_rst_ni) begin
      shift_count_q <= '0;
    end else begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (tap_state_i == jtag_tap_pkg::CAPTURE_DR) shift_count_q[b] <= '0;
        else if (tap_state_i == jtag_tap_pkg::SHIFT_DR && (dtmcs_select_i[b] || dmi_select_i[b]) &&
                 shift_count_q[b] != '1)
          shift_count_q[b] <= shift_count_q[b] + 8'd1;
      end
    end
  end

  // The length class cp_length records for bridge b's selected register.
  function automatic logic [1:0] scan_length(int unsigned b);
    int unsigned length = dtmcs_select_i[b] ? DtmcsLen : DmiLen;
    if (shift_count_q[b] < length) return LengthShort;
    return shift_count_q[b] == length ? LengthExact : LengthLonger;
  endfunction

  // The source cp_disturb records for bridge b at a DR update it did not
  // select.
  function automatic logic [1:0] dr_source(int unsigned b);
    logic [Bridges-1:0] others = ~(Bridges'(1) << b);
    if ((dmi_select_i & others) != '0) return SourceOtherDmi;
    if ((dtmcs_select_i & others) != '0) return SourceOtherDtmcs;
    return SourceNonBridge;
  endfunction

  always_ff @(posedge tck_i) begin
    if (tap_rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (tap_state_i == jtag_tap_pkg::UPDATE_DR) begin
          if (dtmcs_select_i[b] || dmi_select_i[b])
            u_cg_j2a_isolation.sample(KindIsoLength, 2'(b), {dtmcs_select_i[b], scan_length(b)});
          else u_cg_j2a_isolation.sample(KindIsoDisturb, 2'(b), {dr_source(b), dm_sbbusy_i[b]});
        end else if (tap_state_i == jtag_tap_pkg::UPDATE_IR) begin
          u_cg_j2a_isolation.sample(KindIsoDisturb, 2'(b), {SourceIr, dm_sbbusy_i[b]});
        end
      end
    end
  end

endmodule : dtp_j2a_fcov
