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
// it acts on while it holds one (cg_j2a_sba_error); the READY waits,
// response latencies and AW/W order each bridge port sees, and the sbcs reads
// whose access completes while the read is in flight (cg_j2a_axi_timing).
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
//
// The port timing samples are taken on the same clock from each bridge
// port's handshake signals, between the bridge and its responder. A port
// carries one transfer at a time, so one counter per channel and bridge
// measures it. The sbcs race samples are taken on TCK: the Update-DR of an
// sbcs read while sbbusy is 1 records the port's completed transfers, and the
// next DMI capture, which returns that read, is sampled with the sbbusy it
// returns when the port completed a transfer in between.
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
  input wire [2:0]      port_rlast_i
);

  localparam int unsigned Bridges = 3;
  // sbcs sbversion, sbbusy, sbasize and sbaccess128 to sbaccess8.
  localparam logic [31:0] SbcsReadOnly = 32'hE020_0FFF;
  localparam logic [6:0] AddrSbcs = 7'h38;
  localparam logic [6:0] AddrSbaddress0 = 7'h39;
  localparam logic [6:0] AddrSbdata0 = 7'h3C;
  localparam logic [2:0] SberrorBus = 3'd2;
  localparam logic [2:0] SberrorSize = 3'd4;
  localparam logic [1:0] DmiOpRead = 2'd1;
  // cg_j2a_axi_timing sample kinds.
  localparam logic [2:0] KindAwStall = 3'd0;
  localparam logic [2:0] KindWStall = 3'd1;
  localparam logic [2:0] KindArStall = 3'd2;
  localparam logic [2:0] KindBDelay = 3'd3;
  localparam logic [2:0] KindRDelay = 3'd4;
  localparam logic [2:0] KindWOrder = 3'd5;
  localparam logic [2:0] KindSbcsRace = 3'd6;
  // Cycles from which a READY wait or a response latency counts as long, and
  // the latency up to which a response counts as prompt.
  localparam int unsigned LongCycles = 64;
  localparam int unsigned PromptCycles = 2;

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
  // response of the access a bus error ends and the op a size error refuses,
  // and one per DMI write it acts on while it holds an error, by kind: 0 an
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
      logic [1:0] kind
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

  cg_j2a_dmi_status u_cg_j2a_dmi_status = new();
  cg_j2a_dm_access u_cg_j2a_dm_access = new();
  cg_j2a_sba_access u_cg_j2a_sba_access = new();
  cg_j2a_sba_error u_cg_j2a_sba_error = new();
  cg_j2a_axi_timing u_cg_j2a_axi_timing = new();

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

  always_ff @(posedge clk_i) begin
    if (rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (sba_grant_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b0, sba_write_i[b], sba_size_i[b], sba_offset_i[b],
                                     sba_autoinc_i[b]);
        if (sba_carry_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b1, sba_write_q[b], sba_size_i[b], '0, 1'b1);
        if (sba_error_valid_i[b])
          u_cg_j2a_sba_error.sample(2'(b), 1'b0, sba_error_i[b],
                                    sba_error_i[b] == SberrorBus ? sba_write_q[b] : sba_write_i[b],
                                    sba_write_q[b] ? sba_bresp_i[b] : sba_rresp_i[b], '0);
        if (held_valid[b]) u_cg_j2a_sba_error.sample(2'(b), 1'b1, '0, 1'b0, '0, held_kind[b]);
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

endmodule : dtp_j2a_fcov
