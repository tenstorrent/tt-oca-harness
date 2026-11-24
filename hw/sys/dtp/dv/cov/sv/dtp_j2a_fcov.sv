// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// JTAG2AXI functional coverage: the DMI operations each bridge's DTM updates
// with the status their own scan captured, and the dmireset strobes with the
// sticky status they clear (cg_j2a_dmi_status); the Debug Module registers
// each bridge reads and writes with dmactive 0 and 1, and the sbcs writes
// that set a read-only bit (cg_j2a_dm_access); the size, byte offset and
// sbautoincrement of each bus access a bridge's Debug Module starts, and the
// autoincrements that carry into address bit 32 (cg_j2a_sba_access).
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
// address bits above bit 31.
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
  input wire [2:0]      sba_carry_i
);

  localparam int unsigned Bridges = 3;
  // sbcs sbversion, sbbusy, sbasize and sbaccess128 to sbaccess8.
  localparam logic [31:0] SbcsReadOnly = 32'hE020_0FFF;
  localparam logic [6:0] AddrSbcs = 7'h38;

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

  cg_j2a_dmi_status u_cg_j2a_dmi_status = new();
  cg_j2a_dm_access u_cg_j2a_dm_access = new();
  cg_j2a_sba_access u_cg_j2a_sba_access = new();

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

  always_ff @(posedge clk_i) begin
    if (rst_ni) begin
      for (int unsigned b = 0; b < Bridges; b++) begin
        if (sba_grant_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b0, sba_write_i[b], sba_size_i[b], sba_offset_i[b],
                                     sba_autoinc_i[b]);
        if (sba_carry_i[b])
          u_cg_j2a_sba_access.sample(2'(b), 1'b1, sba_write_q[b], sba_size_i[b], '0, 1'b1);
      end
    end
  end

endmodule : dtp_j2a_fcov
