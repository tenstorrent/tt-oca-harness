// SPDX-License-Identifier: Apache-2.0
// SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
//
// SMC eFuse-control functional coverage: the covergroups smc_state_inject_cg,
// smc_efuse_lock_cg, smc_efuse_jtag_lc_cg and smc_efuse_timeout_cg of
// SMC_FCOV.adoc, on the state-injection hooks, the SEP_IN accesses to the
// eFuse map and to the eFuse interface-control registers, the JTAG eFuse
// AXI-Lite port and the lifecycle input.
//
// Every group counts only inside its owner's graded window (tb_fcov_gate)
// and behind a condition its owner drives there: an injection is the rise of
// a tb_*_state_inject_en hook; a lock cell is a SEP_IN write to LOCKS or a
// 4-byte field access of the eFuse map; a lifecycle cell is a completion on
// the JTAG eFuse port; a timeout cell counts only after a timeout register
// was written with its enable bit set over SEP_IN under the gate and the
// owner's read-back returned the written word. A DUT value the sampler takes
// (the shadow probe, the locks, the lifecycle integrity flag, the SHIM's
// response) is compared with what the bench observes on the bus or at the
// interface's outputs, and a disagreement or an outcome contrary to the
// stated one samples no cell.
//
// Constants: register addresses from smc_top_addrmap_pkg; the LOCKS bit
// positions and the control, status and timeout fields of the
// interface-control registers from smc_reg.svh; the zeroer
// state encodings of zeroer.adoc (State Machine); the lifecycle encodings
// and the blocked-read word of the eFuse architecture document (Lifecycle
// State (LC_STATE) Effects), which no generated symbol carries.
//
// The phase of an injection is read on the falling edge before the hook's
// rise: the force lands on the state register at the rising edge at which
// the hook first reads 1, so the request and busy lines of that edge already
// carry the forced state.
//
// One instance in the shared tb_top. Every port is a smc_tb_signal_list.svh
// signal, a smc_wrapper boundary port or the lifecycle integrity flag
// smc_efuse_fcov takes.
//
// CONVENTION (see dtp_fcov.sv): no declaration initializers on
// always_ff-driven variables; declare wires before use.

module smc_efuse_ctrl_fcov #(
  parameter int unsigned LC_STATE_WIDTH = 8,
  parameter int unsigned SHADOW_BITS = 8192
) (
  input wire clk_smc_i,
  input wire rst_cold_ni,

  // SEP_IN request, write data, write response and read channels.
  input wire sep_awvalid_i,
  input wire sep_awready_i,
  input wire [55:0] sep_awaddr_i,
  input wire [2:0] sep_awsize_i,
  input wire sep_wvalid_i,
  input wire sep_wready_i,
  input wire sep_wlast_i,
  input wire [63:0] sep_wdata_i,
  input wire [7:0] sep_wstrb_i,
  input wire sep_bvalid_i,
  input wire sep_bready_i,
  input wire [1:0] sep_bresp_i,
  input wire sep_arvalid_i,
  input wire sep_arready_i,
  input wire [55:0] sep_araddr_i,
  input wire [2:0] sep_arsize_i,
  input wire sep_rvalid_i,
  input wire sep_rready_i,
  input wire sep_rlast_i,
  input wire [1:0] sep_rresp_i,
  input wire [63:0] sep_rdata_i,

  // JTAG eFuse AXI-Lite port.
  input wire ej_awvalid_i,
  input wire ej_awready_i,
  input wire [31:0] ej_awaddr_i,
  input wire ej_bvalid_i,
  input wire ej_bready_i,
  input wire [1:0] ej_bresp_i,
  input wire ej_arvalid_i,
  input wire ej_arready_i,
  input wire [31:0] ej_araddr_i,
  input wire ej_rvalid_i,
  input wire ej_rready_i,
  input wire [1:0] ej_rresp_i,
  input wire [31:0] ej_rdata_i,

  // Lifecycle input and the integrity flag the DUT derives from it.
  input wire [LC_STATE_WIDTH-1:0] lc_state_i,
  input wire lc_sigint_err_i,

  // Zeroer state-injection hook and taps.
  input wire zeroer_inject_en_i,
  input wire [2:0] zeroer_inject_i,
  input wire [2:0] zeroer_state_i,
  input wire zeroer_busy_i,
  input wire zeroer_intp_i,

  // eFuse program and read interface hooks and taps.
  input wire program_inject_en_i,
  input wire [1:0] program_inject_i,
  input wire program_req_valid_i,
  input wire program_busy_i,
  input wire program_done_i,
  input wire program_error_i,
  input wire read_inject_en_i,
  input wire [1:0] read_inject_i,
  input wire read_req_valid_i,
  input wire read_busy_i,
  input wire read_done_i,
  input wire read_error_i,

  // The SHIM's response to the interface controller's fuse command (the bank
  // model's APB completion; the bank-control AXI-Lite port carries the SHIM's
  // own registers, not the fuse path).
  input wire shim_resp_valid_i,

  // LOCKS and the shadow register output.
  input wire [63:0] locks_i,
  input wire [SHADOW_BITS-1:0] shadow_probe_i,

  // Graded-window gate (tb_fcov_gate), driven by the owning leaf.
  input wire fcov_gate_i
);

  import smc_top_addrmap_pkg::*;
  // The LOCKS bit positions and the eFuse interface-control field masks and
  // reset words. The header's include guard is cleared before and after, so
  // this module and every other unit that includes the same header each get
  // its contents whatever their order in one compilation unit. The generated
  // header sizes its 32-bit reset words as 64-bit localparams, a width the
  // simulator reports per constant.
`ifdef SMC_TOP_REG_SVH
  `undef SMC_TOP_REG_SVH
`endif
  // verilator lint_off WIDTHEXPAND
  // verilator lint_off SYMRSVDWORD
  `include "smc_reg.svh"
  // verilator lint_on SYMRSVDWORD
  // verilator lint_on WIDTHEXPAND
  `undef SMC_TOP_REG_SVH

  wire in_reset = (rst_cold_ni !== 1'b1);

  wire gate_on = (fcov_gate_i === 1'b1);
  logic gate_q;
  wire gate_rise = gate_on && !gate_q;
  wire gate_fall = !gate_on && gate_q;

  // ------------------------------------------------------------------
  // SEP_IN accesses (the form of smc_map_row_fcov): address and size at the
  // AW or AR accept, data and strobe at the W-last accept, the write at the
  // B accept, the read at the R-last accept; one access is outstanding at a
  // time. A 32-bit register sits in the lane its address selects.
  // ------------------------------------------------------------------
  wire sep_aw_acc = (sep_awvalid_i === 1'b1) && (sep_awready_i === 1'b1);
  wire sep_w_last_acc = (sep_wvalid_i === 1'b1) && (sep_wready_i === 1'b1)
      && (sep_wlast_i === 1'b1);
  wire sep_b_acc = (sep_bvalid_i === 1'b1) && (sep_bready_i === 1'b1);
  wire sep_b_okay = sep_b_acc && (sep_bresp_i === 2'b00);
  wire sep_ar_acc = (sep_arvalid_i === 1'b1) && (sep_arready_i === 1'b1);
  wire sep_r_last_acc = (sep_rvalid_i === 1'b1) && (sep_rready_i === 1'b1)
      && (sep_rlast_i === 1'b1);
  wire sep_r_okay = sep_r_last_acc && (sep_rresp_i === 2'b00);

  logic [55:0] sep_waddr_q, sep_raddr_q;
  logic [2:0] sep_wsize_q, sep_rsize_q;
  logic [63:0] sep_wdata_q;
  logic [7:0] sep_wstrb_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      sep_waddr_q <= '0;
      sep_raddr_q <= '0;
      sep_wsize_q <= '0;
      sep_rsize_q <= '0;
      sep_wdata_q <= '0;
      sep_wstrb_q <= '0;
      gate_q <= 1'b0;
    end else begin
      if (sep_aw_acc) begin
        sep_waddr_q <= sep_awaddr_i;
        sep_wsize_q <= sep_awsize_i;
      end
      if (sep_w_last_acc) begin
        sep_wdata_q <= sep_wdata_i;
        sep_wstrb_q <= sep_wstrb_i;
      end
      if (sep_ar_acc) begin
        sep_raddr_q <= sep_araddr_i;
        sep_rsize_q <= sep_arsize_i;
      end
      gate_q <= gate_on;
    end
  end

  localparam logic [2:0] SizeFour = 3'd2;
  localparam logic [2:0] SizeEight = 3'd3;

  function automatic logic [31:0] lane_word(input logic [63:0] data, input logic hi);
    return hi ? data[63:32] : data[31:0];
  endfunction

  wire sep_w_is4 = (sep_wsize_q == SizeFour);
  wire sep_r_is4 = (sep_rsize_q == SizeFour);
  wire sep_w_lane_full = sep_waddr_q[2] ? (sep_wstrb_q[7:4] === 4'hF)
                                        : (sep_wstrb_q[3:0] === 4'hF);
  wire [31:0] sep_w_word = lane_word(sep_wdata_q, sep_waddr_q[2]);
  wire [31:0] sep_r_word = lane_word(sep_rdata_i, sep_raddr_q[2]);
  wire sep_r_word_known = (^sep_r_word !== 1'bx);

  // ------------------------------------------------------------------
  // smc_state_inject_cg: block x encoding x phase of the injection cycle,
  // and the recovery. The phase is taken on the falling edge before the
  // hook's rise (see the header). An eFuse interface is during its request
  // while its request line is high and busy agrees, waiting while busy
  // without a request, idle while neither (busy is the register field the
  // owner reads clear before an idle injection); the zeroer's phase is its
  // state register, its idle cell with busy clear. A disagreement between
  // the request line and busy, or an idle zeroer state with busy high,
  // samples no cell.
  // ------------------------------------------------------------------
  // zeroer.adoc, State Machine.
  localparam logic [2:0] ZeroerIdle = 3'b001;
  localparam logic [2:0] ZeroerIssueAddr = 3'b010;
  localparam logic [2:0] ZeroerIssueData = 3'b100;
  localparam logic [2:0] ZeroerError = 3'b000;

  localparam logic [1:0] BlkZeroer = 2'd0;
  localparam logic [1:0] BlkRead = 2'd1;
  localparam logic [1:0] BlkProgram = 2'd2;
  localparam logic [1:0] BlkNone = 2'd3;
  localparam logic [1:0] PhIdle = 2'd0;
  localparam logic [1:0] PhRequest = 2'd1;
  localparam logic [1:0] PhWait = 2'd2;
  localparam logic [1:0] PhNone = 2'd3;
  localparam logic [1:0] RecZeroer = 2'd0;
  localparam logic [1:0] RecRead = 2'd1;
  localparam logic [1:0] RecProgram = 2'd2;
  localparam logic [1:0] RecNone = 2'd3;

  logic [2:0] snap_zeroer_state_q;
  logic snap_zeroer_busy_q;
  logic snap_program_req_q, snap_program_busy_q, snap_read_req_q, snap_read_busy_q;
  always_ff @(negedge clk_smc_i) begin
    if (in_reset) begin
      snap_zeroer_state_q <= ZeroerIdle;
      snap_zeroer_busy_q <= 1'b0;
      snap_program_req_q <= 1'b0;
      snap_program_busy_q <= 1'b0;
      snap_read_req_q <= 1'b0;
      snap_read_busy_q <= 1'b0;
    end else begin
      snap_zeroer_state_q <= zeroer_state_i;
      snap_zeroer_busy_q <= zeroer_busy_i;
      snap_program_req_q <= program_req_valid_i;
      snap_program_busy_q <= program_busy_i;
      snap_read_req_q <= read_req_valid_i;
      snap_read_busy_q <= read_busy_i;
    end
  end

  function automatic logic [1:0] efuse_phase(input logic req, input logic busy);
    if ((req === 1'b1) && (busy === 1'b1)) return PhRequest;
    if ((req === 1'b0) && (busy === 1'b1)) return PhWait;
    if ((req === 1'b0) && (busy === 1'b0)) return PhIdle;
    return PhNone;
  endfunction

  function automatic logic [1:0] zeroer_phase(input logic [2:0] state, input logic busy);
    case (state)
      ZeroerIdle: return (busy === 1'b0) ? PhIdle : PhNone;
      ZeroerIssueAddr: return PhRequest;
      ZeroerIssueData: return PhWait;
      default: return PhNone;
    endcase
  endfunction

  // The injected encoding as a bin code: the four unused zeroer encodings
  // and the two unused encodings of an eFuse interface (entry 101 of
  // SMC_VPLAN); a legal encoding has no code.
  function automatic logic [2:0] zeroer_enc(input logic [2:0] v);
    case (v)
      3'b011: return 3'd0;
      3'b101: return 3'd1;
      3'b110: return 3'd2;
      3'b111: return 3'd3;
      default: return 3'd4;
    endcase
  endfunction

  function automatic logic [2:0] efuse_enc(input logic [1:0] v);
    case (v)
      2'b00: return 3'd0;
      2'b11: return 3'd1;
      default: return 3'd4;
    endcase
  endfunction

  logic zeroer_en_q, program_en_q, read_en_q;
  wire zeroer_rise = gate_on && (zeroer_inject_en_i === 1'b1) && !zeroer_en_q;
  wire program_rise = gate_on && (program_inject_en_i === 1'b1) && !program_en_q;
  wire read_rise = gate_on && (read_inject_en_i === 1'b1) && !read_en_q;
  wire [2:0] zeroer_code = zeroer_enc(zeroer_inject_i);
  wire [2:0] program_code = efuse_enc(program_inject_i);
  wire [2:0] read_code = efuse_enc(read_inject_i);
  wire [1:0] zeroer_ph = zeroer_phase(snap_zeroer_state_q, snap_zeroer_busy_q);
  wire [1:0] program_ph = efuse_phase(snap_program_req_q, snap_program_busy_q);
  wire [1:0] read_ph = efuse_phase(snap_read_req_q, snap_read_busy_q);
  wire zeroer_cell_e = zeroer_rise && (zeroer_code != 3'd4) && (zeroer_ph != PhNone);
  wire program_cell_e = program_rise && (program_code != 3'd4) && (program_ph != PhNone);
  wire read_cell_e = read_rise && (read_code != 3'd4) && (read_ph != PhNone);

  // Recovery. The zeroer cell is sampled at the gate fall the owner places
  // before its cold reset: the state register in ST_ERROR, busy high, no
  // interrupt. An eFuse interface's recovery is recorded at the owner's
  // read of its control register after the injection, the word carrying
  // done and status with busy clear, the taps agreeing.
  localparam logic [55:0] ReadCtrlAddr =
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_BASE_ADDR);
  localparam logic [55:0] ProgCtrlAddr =
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_BASE_ADDR);
  localparam logic [31:0] ReadCtrlBusy = 32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_READ_BUSY_MASK);
  localparam logic [31:0] ReadCtrlDone = 32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_READ_DONE_MASK);
  localparam logic [31:0] ReadCtrlStatus =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_CTRL_READ_STATUS_MASK);
  localparam logic [31:0] ProgCtrlBusy =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_PROGRAM_BUSY_MASK);
  localparam logic [31:0] ProgCtrlDone =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_PROGRAM_DONE_MASK);
  localparam logic [31:0] ProgCtrlStatus =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_CTRL_PROGRAM_STATUS_MASK);

  logic zeroer_injected_q, program_injected_q, read_injected_q;
  wire zeroer_rec_e = gate_fall && zeroer_injected_q && (zeroer_state_i === ZeroerError)
      && (zeroer_busy_i === 1'b1) && (zeroer_intp_i === 1'b0);
  wire read_ctrl_r = sep_r_okay && sep_r_is4 && (sep_raddr_q == ReadCtrlAddr);
  wire prog_ctrl_r = sep_r_okay && sep_r_is4 && (sep_raddr_q == ProgCtrlAddr);
  wire read_rec_e = gate_on && read_injected_q && read_ctrl_r && sep_r_word_known
      && ((sep_r_word & ReadCtrlDone) != 32'd0) && ((sep_r_word & ReadCtrlStatus) != 32'd0)
      && ((sep_r_word & ReadCtrlBusy) == 32'd0) && (read_done_i === 1'b1)
      && (read_error_i === 1'b1) && (read_busy_i === 1'b0);
  wire program_rec_e = gate_on && program_injected_q && prog_ctrl_r && sep_r_word_known
      && ((sep_r_word & ProgCtrlDone) != 32'd0) && ((sep_r_word & ProgCtrlStatus) != 32'd0)
      && ((sep_r_word & ProgCtrlBusy) == 32'd0) && (program_done_i === 1'b1)
      && (program_error_i === 1'b1) && (program_busy_i === 1'b0);

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      zeroer_en_q <= 1'b0;
      program_en_q <= 1'b0;
      read_en_q <= 1'b0;
      zeroer_injected_q <= 1'b0;
      program_injected_q <= 1'b0;
      read_injected_q <= 1'b0;
    end else begin
      zeroer_en_q <= (zeroer_inject_en_i === 1'b1);
      program_en_q <= (program_inject_en_i === 1'b1);
      read_en_q <= (read_inject_en_i === 1'b1);
      if (gate_rise || zeroer_rec_e) zeroer_injected_q <= 1'b0;
      else if (zeroer_rise) zeroer_injected_q <= 1'b1;
      if (gate_rise || program_rec_e) program_injected_q <= 1'b0;
      else if (program_rise) program_injected_q <= 1'b1;
      if (gate_rise || read_rec_e) read_injected_q <= 1'b0;
      else if (read_rise) read_injected_q <= 1'b1;
    end
  end

  // ------------------------------------------------------------------
  // smc_efuse_lock_cg: the slot of an eFuse-map word from the generated
  // register addresses (the four named fields and the SPARE array, in
  // address order), the lock bits of a slot from the generated LOCKS field
  // positions, and the field word of the shadow output at bits 32w+31:32w.
  // ------------------------------------------------------------------
  localparam logic [55:0] MapBase = 56'(SMC_TOP_SMC_EFUSE_MAP_BASE_ADDR);
  localparam logic [55:0] MapEnd = MapBase + 56'(SMC_TOP_SMC_EFUSE_MAP_SIZE);
  localparam logic [55:0] LocksAddr = 56'(SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR);
  localparam logic [55:0] Slot0Base = 56'(SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR);
  localparam logic [55:0] Slot1Base = 56'(SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR(0));
  localparam logic [55:0] Slot2Base = 56'(SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR);
  localparam logic [55:0] Slot3Base = 56'(SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR);
  localparam logic [55:0] Spare0Base = 56'(SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(0));
  localparam logic [55:0] SpareStride = 56'(SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(1)) - Spare0Base;
  localparam logic [55:0] SpareNum = 56'(SMC_TOP_SMC_EFUSE_MAP_SPARE_NUM);
  localparam logic [55:0] SpareEnd = Spare0Base + SpareNum * SpareStride;
  localparam int unsigned NumSlots = 32;
  localparam int unsigned NumWords = SHADOW_BITS / 32;

  // {valid, slot} of a map byte address.
  function automatic logic [5:0] slot_of(input logic [55:0] a);
    if ((a >= Spare0Base) && (a < SpareEnd)) begin
      return {1'b1, 5'(56'd4 + (a - Spare0Base) / SpareStride)};
    end
    if ((a >= Slot3Base) && (a < Spare0Base)) return {1'b1, 5'd3};
    if ((a >= Slot2Base) && (a < Slot3Base)) return {1'b1, 5'd2};
    if ((a >= Slot1Base) && (a < Slot2Base)) return {1'b1, 5'd1};
    if ((a >= Slot0Base) && (a < Slot1Base)) return {1'b1, 5'd0};
    return 6'd0;
  endfunction

  function automatic logic [7:0] word_of(input logic [55:0] a);
    return 8'((a - MapBase) >> 2);
  endfunction

  // The LOCKS bit of each slot's write lock and read lock, in slot order.
  localparam int unsigned WriteLockBit[NumSlots] = '{
      SMC_EFUSE_MAP_LOCKS_JTAG_PUBLIC_IDENTITY_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_I2C_I3C_ID_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SMC_CONFIG_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_OCCP_TRANSPORT_TIMEOUT_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE0_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE1_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE2_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE3_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE4_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE5_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE6_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE7_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE8_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE9_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE10_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE11_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE12_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE13_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE14_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE15_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE16_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE17_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE18_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE19_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE20_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE21_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE22_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE23_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE24_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE25_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE26_WRITE_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE27_WRITE_LOCK_SHIFT
  };
  localparam int unsigned ReadLockBit[NumSlots] = '{
      SMC_EFUSE_MAP_LOCKS_JTAG_PUBLIC_IDENTITY_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_I2C_I3C_ID_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SMC_CONFIG_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_OCCP_TRANSPORT_TIMEOUT_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE0_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE1_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE2_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE3_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE4_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE5_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE6_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE7_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE8_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE9_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE10_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE11_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE12_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE13_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE14_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE15_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE16_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE17_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE18_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE19_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE20_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE21_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE22_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE23_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE24_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE25_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE26_READ_LOCK_SHIFT,
      SMC_EFUSE_MAP_LOCKS_SPARE27_READ_LOCK_SHIFT
  };

  // {valid, slot, kind} of a LOCKS bit (kind 0 write lock, 1 read lock).
  function automatic logic [6:0] slot_kind_of_bit(input int unsigned b);
    for (int unsigned n = 0; n < NumSlots; n++) begin
      if (WriteLockBit[n] == b) return {1'b1, 5'(n), 1'b0};
      if (ReadLockBit[n] == b) return {1'b1, 5'(n), 1'b1};
    end
    return 7'd0;
  endfunction

  // A LOCKS write: the whole 64-bit word, or one 32-bit half in its lane.
  // Every bit the write sets is a slot-kind cell once the locks output
  // carries it set (the bit the image presets reads 1 at once).
  wire locks_w64 = (sep_wsize_q == SizeEight) && (sep_wstrb_q === 8'hFF)
      && (sep_waddr_q == LocksAddr);
  wire locks_w32 = sep_w_is4 && sep_w_lane_full && ((sep_waddr_q & ~56'h7) == LocksAddr);
  wire locks_w = gate_on && sep_b_okay && (locks_w64 || locks_w32);
  wire [63:0] locks_w_bits = locks_w64 ? sep_wdata_q
                           : sep_waddr_q[2] ? {sep_wdata_q[63:32], 32'd0}
                           : {32'd0, sep_wdata_q[31:0]};
  logic [63:0] lock_pend_q;
  wire [63:0] lock_pend_set = lock_pend_q | (locks_w ? locks_w_bits : 64'd0);
  logic [63:0] locks_ones;
  logic [6:0] bit_slot_kind[64];
  always_comb begin
    for (int unsigned b = 0; b < 64; b++) begin
      locks_ones[b] = (locks_i[b] === 1'b1);
      bit_slot_kind[b] = slot_kind_of_bit(b);
    end
  end
  wire [63:0] lock_pend_hit = lock_pend_set & locks_ones;

  // Field accesses: a 4-byte write records its word, its data and the write
  // lock at the time; the owner's 4-byte read of that word then grades the
  // write (kept while unlocked, refused while locked) and the read itself
  // (the field returned while read-unlocked, neither the field nor its
  // complement under the read lock), each against the shadow output word.
  localparam logic [1:0] OutWriteKept = 2'd0;
  localparam logic [1:0] OutWriteRefused = 2'd1;
  localparam logic [1:0] OutReadReturned = 2'd2;
  localparam logic [1:0] OutReadHidden = 2'd3;

  wire [5:0] w_slot = slot_of(sep_waddr_q);
  wire [7:0] w_word = word_of(sep_waddr_q);
  wire field_w = gate_on && sep_b_acc && sep_w_is4 && sep_w_lane_full && w_slot[5];
  wire [5:0] r_slot = slot_of(sep_raddr_q);
  wire [7:0] r_word = word_of(sep_raddr_q);
  wire field_r = gate_on && sep_r_last_acc && sep_r_is4 && r_slot[5];

  logic [31:0] wr_data_q[NumWords];
  logic wr_wlock_q[NumWords];
  logic wr_valid_q[NumWords];
  wire [31:0] probe_word = shadow_probe_i[32*r_word+:32];
  wire probe_known = (^probe_word !== 1'bx);
  wire r_rlock = locks_i[ReadLockBit[r_slot[4:0]]];
  wire w_wlock = locks_i[WriteLockBit[w_slot[4:0]]];
  wire rd_open = field_r && (sep_rresp_i === 2'b00) && (r_rlock === 1'b0) && probe_known
      && sep_r_word_known && (sep_r_word == probe_word);
  wire rd_hidden = field_r && (r_rlock === 1'b1) && probe_known && sep_r_word_known
      && (sep_r_word != probe_word) && (sep_r_word != ~probe_word);
  wire wr_kept = rd_open && wr_valid_q[r_word] && (wr_wlock_q[r_word] === 1'b0)
      && (sep_r_word == wr_data_q[r_word]);
  wire wr_refused = rd_open && wr_valid_q[r_word] && (wr_wlock_q[r_word] === 1'b1)
      && (sep_r_word != wr_data_q[r_word]);

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      lock_pend_q <= '0;
      for (int unsigned w = 0; w < NumWords; w++) begin
        wr_data_q[w] <= '0;
        wr_wlock_q[w] <= 1'b0;
        wr_valid_q[w] <= 1'b0;
      end
    end else begin
      lock_pend_q <= gate_rise ? 64'd0 : (lock_pend_set & ~lock_pend_hit);
      if (field_w) begin
        wr_data_q[w_word] <= sep_w_word;
        wr_wlock_q[w_word] <= (w_wlock === 1'b1);
        wr_valid_q[w_word] <= 1'b1;
      end
      if (field_r) wr_valid_q[r_word] <= 1'b0;
    end
  end

  // ------------------------------------------------------------------
  // smc_efuse_jtag_lc_cg: the lifecycle image from lc_state_i ({diff_n,
  // diff_p}; the state is diff_p when diff_n is its complement, the
  // integrity-error fallback otherwise), cross-checked against the DUT's
  // integrity flag; the operation from the JTAG eFuse port; the verdict
  // from the response code and the blocked-read word.
  // ------------------------------------------------------------------
  localparam int unsigned LcHalf = LC_STATE_WIDTH / 2;
  // architecture.adoc, Lifecycle State (LC_STATE) Effects: the encodings the
  // owner drives (TEST_DEV 0x0, PROD 0x1, RMA_SOP 0x2, RMA_CHIPLET 0x6,
  // PROD_END 0x8) and the error slave's read data.
  localparam logic [LcHalf-1:0] LcTestDev = LcHalf'(4'h0);
  localparam logic [LcHalf-1:0] LcProd = LcHalf'(4'h1);
  localparam logic [LcHalf-1:0] LcRmaSop = LcHalf'(4'h2);
  localparam logic [LcHalf-1:0] LcRmaChiplet = LcHalf'(4'h6);
  localparam logic [LcHalf-1:0] LcProdEnd = LcHalf'(4'h8);
  localparam logic [31:0] BlockedWord = 32'hBADCAB1E;
  localparam logic [2:0] ImgTestDev = 3'd0;
  localparam logic [2:0] ImgProd = 3'd1;
  localparam logic [2:0] ImgRmaSop = 3'd2;
  localparam logic [2:0] ImgRmaChiplet = 3'd3;
  localparam logic [2:0] ImgProdEnd = 3'd4;
  localparam logic [2:0] ImgInvalid = 3'd5;
  localparam logic [2:0] ImgNone = 3'd6;
  localparam logic [1:0] OpWrite = 2'd0;
  localparam logic [1:0] OpReadOutside = 2'd1;
  localparam logic [1:0] OpReadIdentity = 2'd2;
  localparam logic [1:0] OpNone = 2'd3;

  wire [LcHalf-1:0] lc_n = lc_state_i[LC_STATE_WIDTH-1:LcHalf];
  wire [LcHalf-1:0] lc_p = lc_state_i[LcHalf-1:0];
  wire lc_known = (^lc_state_i !== 1'bx) && (lc_sigint_err_i !== 1'bx);
  wire lc_valid = lc_known && (lc_n == ~lc_p);
  wire lc_agree = lc_known && (lc_sigint_err_i === (lc_valid ? 1'b0 : 1'b1));

  function automatic logic [2:0] lc_image(input logic valid, input logic [LcHalf-1:0] raw);
    if (!valid) return ImgInvalid;
    case (raw)
      LcTestDev: return ImgTestDev;
      LcProd: return ImgProd;
      LcRmaSop: return ImgRmaSop;
      LcRmaChiplet: return ImgRmaChiplet;
      LcProdEnd: return ImgProdEnd;
      default: return ImgNone;
    endcase
  endfunction

  wire [2:0] lc_img = lc_image(lc_valid, lc_p);
  wire lc_restricted = (lc_img == ImgProd) || (lc_img == ImgRmaSop);

  wire ej_aw_acc = (ej_awvalid_i === 1'b1) && (ej_awready_i === 1'b1);
  wire ej_b_acc = (ej_bvalid_i === 1'b1) && (ej_bready_i === 1'b1);
  wire ej_ar_acc = (ej_arvalid_i === 1'b1) && (ej_arready_i === 1'b1);
  wire ej_r_acc = (ej_rvalid_i === 1'b1) && (ej_rready_i === 1'b1);
  logic [31:0] ej_waddr_q, ej_raddr_q;
  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      ej_waddr_q <= '0;
      ej_raddr_q <= '0;
    end else begin
      if (ej_aw_acc) ej_waddr_q <= ej_awaddr_i;
      if (ej_ar_acc) ej_raddr_q <= ej_araddr_i;
    end
  end

  function automatic logic [1:0] ej_read_op(input logic [31:0] a);
    if ((56'(a) >= Slot0Base) && (56'(a) < Slot1Base)) return OpReadIdentity;
    if ((56'(a) >= MapBase) && (56'(a) < MapEnd)) return OpReadOutside;
    return OpNone;
  endfunction

  wire ej_w_in_map = (56'(ej_waddr_q) >= MapBase) && (56'(ej_waddr_q) < MapEnd);
  wire [1:0] ej_r_op = ej_read_op(ej_raddr_q);
  wire ej_wr_blocked = (ej_bresp_i === 2'b11);
  wire ej_wr_allowed = (ej_bresp_i === 2'b00);
  wire ej_rd_blocked = (ej_rresp_i === 2'b11) && (ej_rdata_i === BlockedWord);
  wire ej_rd_allowed = (ej_rresp_i === 2'b00);

  // The stated verdict: PROD and RMA_SOP block the write and the outside
  // read and allow the identity read; the other encoded images allow all
  // three. The fallback image's cells are recorded whatever the response.
  wire ej_wr_e = gate_on && ej_b_acc && ej_w_in_map && lc_agree && (lc_img != ImgNone);
  wire ej_wr_graded = ej_wr_e && ((lc_img == ImgInvalid)
      || (lc_restricted ? ej_wr_blocked : ej_wr_allowed));
  wire ej_rd_e = gate_on && ej_r_acc && (ej_r_op != OpNone) && lc_agree && (lc_img != ImgNone);
  wire ej_rd_expect_block = lc_restricted && (ej_r_op == OpReadOutside);
  wire ej_rd_graded = ej_rd_e && ((lc_img == ImgInvalid)
      || (ej_rd_expect_block ? ej_rd_blocked : ej_rd_allowed));
  wire ej_err_word_e = gate_on && ej_r_acc && ej_rd_blocked;

  // ------------------------------------------------------------------
  // smc_efuse_timeout_cg: a timeout register written with its enable bit
  // set over SEP_IN under the gate and read back equal opens its interface
  // (count 1 to the reset value); the count class is sampled at that
  // read-back. The stall class of an operation is whether the SHIM's
  // response to it was seen between the interface's request and its done:
  // the interface registers done from that response, so a response the
  // bank delivers before the timeout is seen one edge before done rises,
  // and one it delivers after the timeout is not. The stall cell is
  // sampled at the owner's first OKAY read of the interface's control
  // register that returns done set after that done (a poll issued before
  // the done returns the word captured before it and grades nothing), when
  // the status field of the word it reads (the generated mask) and the
  // error tap both equal the class; a word or tap contrary to the class
  // samples no cell.
  // ------------------------------------------------------------------
  localparam logic IfcRead = 1'b0;
  localparam logic IfcProgram = 1'b1;
  localparam logic [55:0] ReadTmoAddr =
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_BASE_ADDR);
  localparam logic [55:0] ProgTmoAddr =
      56'(SMC_TOP_EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_BASE_ADDR);
  localparam logic [31:0] ReadTmoCycles =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_READ_REQ_TIMEOUT_CYCLES_MASK);
  localparam logic [31:0] ReadTmoEnable =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_READ_REQ_TIMOUT_ENABLE_MASK);
  localparam logic [31:0] ProgTmoCycles =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_PROGRAM_REQ_TIMEOUT_CYCLES_MASK);
  localparam logic [31:0] ProgTmoEnable =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_PROGRAM_REQ_TIMEOUT_ENABLE_MASK);
  localparam logic [31:0] ReadTmoReset =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_READ_REQ_TIMEOUT_REG_DEFAULT) & ReadTmoCycles;
  localparam logic [31:0] ProgTmoReset =
      32'(EFUSE_INTERFACE_CTRL_EFUSE_PROGRAM_REQ_TIMEOUT_REG_DEFAULT) & ProgTmoCycles;
  localparam logic CntInRange = 1'b0;
  localparam logic CntReset = 1'b1;
  localparam logic StallShorter = 1'b0;
  localparam logic StallLonger = 1'b1;

  // {valid, class} of a timeout word: the enable bit set and the count in
  // the row (1 to the reset value less one, or the reset value).
  function automatic logic [1:0] tmo_class(input logic ifc, input logic [31:0] word);
    logic [31:0] count;
    logic enabled;
    count = word & (ifc ? ProgTmoCycles : ReadTmoCycles);
    enabled = ((word & (ifc ? ProgTmoEnable : ReadTmoEnable)) != 32'd0);
    if (!enabled || (count == 32'd0)) return 2'b00;
    if (count == (ifc ? ProgTmoReset : ReadTmoReset)) return {1'b1, CntReset};
    if (count < (ifc ? ProgTmoReset : ReadTmoReset)) return {1'b1, CntInRange};
    return 2'b00;
  endfunction

  logic [31:0] tmo_word_q[2];
  logic tmo_written_q[2];
  logic tmo_live_q[2];
  wire tmo_w[2];
  wire tmo_rb[2];
  wire [1:0] tmo_cls[2];
  assign tmo_w[IfcRead] = gate_on && sep_b_okay && sep_w_is4 && sep_w_lane_full
      && (sep_waddr_q == ReadTmoAddr);
  assign tmo_w[IfcProgram] = gate_on && sep_b_okay && sep_w_is4 && sep_w_lane_full
      && (sep_waddr_q == ProgTmoAddr);
  assign tmo_rb[IfcRead] = gate_on && sep_r_okay && sep_r_is4 && (sep_raddr_q == ReadTmoAddr)
      && tmo_written_q[IfcRead] && sep_r_word_known && (sep_r_word == tmo_word_q[IfcRead]);
  assign tmo_rb[IfcProgram] = gate_on && sep_r_okay && sep_r_is4 && (sep_raddr_q == ProgTmoAddr)
      && tmo_written_q[IfcProgram] && sep_r_word_known
      && (sep_r_word == tmo_word_q[IfcProgram]);
  assign tmo_cls[IfcRead] = tmo_class(IfcRead, sep_r_word);
  assign tmo_cls[IfcProgram] = tmo_class(IfcProgram, sep_r_word);

  // The SHIM's response to an interface's request (one pulse per read or
  // per program, the read-back included); seen-since-request clears at the
  // next request of that interface.
  logic read_req_q, program_req_q, read_done_q, program_done_q;
  logic read_resp_seen_q, program_resp_seen_q;
  wire read_req_rise = (read_req_valid_i === 1'b1) && !read_req_q;
  wire program_req_rise = (program_req_valid_i === 1'b1) && !program_req_q;
  wire read_done_rise = (read_done_i === 1'b1) && !read_done_q;
  wire program_done_rise = (program_done_i === 1'b1) && !program_done_q;
  wire read_stall = read_resp_seen_q ? StallShorter : StallLonger;
  wire program_stall = program_resp_seen_q ? StallShorter : StallLonger;
  wire read_stall_done = gate_on && tmo_live_q[IfcRead] && read_done_rise;
  wire program_stall_done = gate_on && tmo_live_q[IfcProgram] && program_done_rise;
  // The class held from the done to the owner's read of the control word.
  logic read_stall_pend_q, program_stall_pend_q, read_stall_q, program_stall_q;
  wire read_ctrl_done_r = read_ctrl_r && sep_r_word_known && ((sep_r_word & ReadCtrlDone) != 32'd0);
  wire prog_ctrl_done_r = prog_ctrl_r && sep_r_word_known && ((sep_r_word & ProgCtrlDone) != 32'd0);
  wire read_stall_word_ok =
      ((sep_r_word & ReadCtrlStatus) != 32'd0) == (read_stall_q == StallLonger);
  wire program_stall_word_ok =
      ((sep_r_word & ProgCtrlStatus) != 32'd0) == (program_stall_q == StallLonger);
  wire read_stall_e = gate_on && read_stall_pend_q && read_ctrl_done_r && read_stall_word_ok
      && (read_error_i === read_stall_q) && (read_done_i === 1'b1);
  wire program_stall_e = gate_on && program_stall_pend_q && prog_ctrl_done_r
      && program_stall_word_ok && (program_error_i === program_stall_q)
      && (program_done_i === 1'b1);

  always_ff @(posedge clk_smc_i) begin
    if (in_reset) begin
      for (int unsigned i = 0; i < 2; i++) begin
        tmo_word_q[i] <= '0;
        tmo_written_q[i] <= 1'b0;
        tmo_live_q[i] <= 1'b0;
      end
      read_req_q <= 1'b0;
      program_req_q <= 1'b0;
      read_done_q <= 1'b0;
      program_done_q <= 1'b0;
      read_resp_seen_q <= 1'b0;
      program_resp_seen_q <= 1'b0;
      read_stall_pend_q <= 1'b0;
      program_stall_pend_q <= 1'b0;
      read_stall_q <= StallShorter;
      program_stall_q <= StallShorter;
    end else begin
      for (int unsigned i = 0; i < 2; i++) begin
        if (gate_rise) begin
          tmo_written_q[i] <= 1'b0;
          tmo_live_q[i] <= 1'b0;
        end else if (tmo_w[i]) begin
          tmo_word_q[i] <= sep_w_word;
          tmo_written_q[i] <= 1'b1;
          tmo_live_q[i] <= 1'b0;
        end else if (tmo_rb[i]) begin
          tmo_live_q[i] <= tmo_cls[i][1];
        end
      end
      read_req_q <= (read_req_valid_i === 1'b1);
      program_req_q <= (program_req_valid_i === 1'b1);
      read_done_q <= (read_done_i === 1'b1);
      program_done_q <= (program_done_i === 1'b1);
      if (read_req_rise) read_resp_seen_q <= 1'b0;
      else if (shim_resp_valid_i === 1'b1) read_resp_seen_q <= 1'b1;
      if (program_req_rise) program_resp_seen_q <= 1'b0;
      else if (shim_resp_valid_i === 1'b1) program_resp_seen_q <= 1'b1;
      // The pending class drops at the first read that returns done set
      // (the read that grades it), at the next request and on every gate
      // rise.
      if (gate_rise || read_req_rise || read_ctrl_done_r) read_stall_pend_q <= 1'b0;
      else if (read_stall_done) read_stall_pend_q <= 1'b1;
      if (read_stall_done) read_stall_q <= read_stall;
      if (gate_rise || program_req_rise || prog_ctrl_done_r) program_stall_pend_q <= 1'b0;
      else if (program_stall_done) program_stall_pend_q <= 1'b1;
      if (program_stall_done) program_stall_q <= program_stall;
    end
  end

  // ------------------------------------------------------------------
  // The covergroups. Each sample fills the coverpoints of its event and
  // passes the others a value no bin lists; every cell of a row has a bin;
  // no group has an ignore_bins.
  // ------------------------------------------------------------------
  // The three phase bins of one block and encoding.
  `define SMC_SIN_PHASE_BINS(name, blk, enc) \
      bins name``_idle = {{blk, enc, PhIdle}}; \
      bins name``_request = {{blk, enc, PhRequest}}; \
      bins name``_wait = {{blk, enc, PhWait}};

  covergroup smc_state_inject_cg with function sample (
      logic [1:0] blk, logic [1:0] enc, logic [1:0] ph, logic [1:0] rec
  );
    option.per_instance = 1;
    // {block, encoding, phase}: 24 cells.
    cp_block_enc: coverpoint {
      blk, enc, ph
    } {
      `SMC_SIN_PHASE_BINS(zeroer_011, BlkZeroer, 2'd0)
      `SMC_SIN_PHASE_BINS(zeroer_101, BlkZeroer, 2'd1)
      `SMC_SIN_PHASE_BINS(zeroer_110, BlkZeroer, 2'd2)
      `SMC_SIN_PHASE_BINS(zeroer_111, BlkZeroer, 2'd3)
      `SMC_SIN_PHASE_BINS(read_00, BlkRead, 2'd0)
      `SMC_SIN_PHASE_BINS(read_11, BlkRead, 2'd1)
      `SMC_SIN_PHASE_BINS(program_00, BlkProgram, 2'd0)
      `SMC_SIN_PHASE_BINS(program_11, BlkProgram, 2'd1)
    }
    // The zeroer cell and the two recorded eFuse recoveries.
    cp_recovery: coverpoint rec {
      bins zeroer_busy_until_cold_reset = {RecZeroer};
      bins rec_read_idle_done_error = {RecRead};
      bins rec_program_idle_done_error = {RecProgram};
    }
  endgroup
  `undef SMC_SIN_PHASE_BINS

  // The two lock-kind bins of a slot, and its four refusal bins.
  `define SMC_ELK_SLOT_BINS(name, n) \
      bins name``_write_lock = {{1'b1, n, 1'b0}}; \
      bins name``_read_lock = {{1'b1, n, 1'b1}};
  `define SMC_ELK_REFUSAL_BINS(name, n) \
      bins name``_write_kept = {{1'b1, n, OutWriteKept}}; \
      bins name``_write_refused = {{1'b1, n, OutWriteRefused}}; \
      bins name``_read_returned = {{1'b1, n, OutReadReturned}}; \
      bins name``_read_hidden = {{1'b1, n, OutReadHidden}};

  covergroup smc_efuse_lock_cg with function sample (
      logic sk, logic rf, logic [4:0] slot, logic kind, logic [1:0] outcome
  );
    option.per_instance = 1;
    // {graded, slot, lock kind}: 64 cells.
    cp_slot_kind: coverpoint {
      sk, slot, kind
    } {
      `SMC_ELK_SLOT_BINS(jtag_public_identity, 5'd0)
      `SMC_ELK_SLOT_BINS(i2c_i3c_id, 5'd1)
      `SMC_ELK_SLOT_BINS(smc_config, 5'd2)
      `SMC_ELK_SLOT_BINS(occp_transport_timeout, 5'd3)
      `SMC_ELK_SLOT_BINS(spare0, 5'd4)
      `SMC_ELK_SLOT_BINS(spare1, 5'd5)
      `SMC_ELK_SLOT_BINS(spare2, 5'd6)
      `SMC_ELK_SLOT_BINS(spare3, 5'd7)
      `SMC_ELK_SLOT_BINS(spare4, 5'd8)
      `SMC_ELK_SLOT_BINS(spare5, 5'd9)
      `SMC_ELK_SLOT_BINS(spare6, 5'd10)
      `SMC_ELK_SLOT_BINS(spare7, 5'd11)
      `SMC_ELK_SLOT_BINS(spare8, 5'd12)
      `SMC_ELK_SLOT_BINS(spare9, 5'd13)
      `SMC_ELK_SLOT_BINS(spare10, 5'd14)
      `SMC_ELK_SLOT_BINS(spare11, 5'd15)
      `SMC_ELK_SLOT_BINS(spare12, 5'd16)
      `SMC_ELK_SLOT_BINS(spare13, 5'd17)
      `SMC_ELK_SLOT_BINS(spare14, 5'd18)
      `SMC_ELK_SLOT_BINS(spare15, 5'd19)
      `SMC_ELK_SLOT_BINS(spare16, 5'd20)
      `SMC_ELK_SLOT_BINS(spare17, 5'd21)
      `SMC_ELK_SLOT_BINS(spare18, 5'd22)
      `SMC_ELK_SLOT_BINS(spare19, 5'd23)
      `SMC_ELK_SLOT_BINS(spare20, 5'd24)
      `SMC_ELK_SLOT_BINS(spare21, 5'd25)
      `SMC_ELK_SLOT_BINS(spare22, 5'd26)
      `SMC_ELK_SLOT_BINS(spare23, 5'd27)
      `SMC_ELK_SLOT_BINS(spare24, 5'd28)
      `SMC_ELK_SLOT_BINS(spare25, 5'd29)
      `SMC_ELK_SLOT_BINS(spare26, 5'd30)
      `SMC_ELK_SLOT_BINS(spare27, 5'd31)
    }
    // {graded, slot, lock kind and state with its outcome}: 128 cells.
    cp_refusal: coverpoint {
      rf, slot, outcome
    } {
      `SMC_ELK_REFUSAL_BINS(jtag_public_identity, 5'd0)
      `SMC_ELK_REFUSAL_BINS(i2c_i3c_id, 5'd1)
      `SMC_ELK_REFUSAL_BINS(smc_config, 5'd2)
      `SMC_ELK_REFUSAL_BINS(occp_transport_timeout, 5'd3)
      `SMC_ELK_REFUSAL_BINS(spare0, 5'd4)
      `SMC_ELK_REFUSAL_BINS(spare1, 5'd5)
      `SMC_ELK_REFUSAL_BINS(spare2, 5'd6)
      `SMC_ELK_REFUSAL_BINS(spare3, 5'd7)
      `SMC_ELK_REFUSAL_BINS(spare4, 5'd8)
      `SMC_ELK_REFUSAL_BINS(spare5, 5'd9)
      `SMC_ELK_REFUSAL_BINS(spare6, 5'd10)
      `SMC_ELK_REFUSAL_BINS(spare7, 5'd11)
      `SMC_ELK_REFUSAL_BINS(spare8, 5'd12)
      `SMC_ELK_REFUSAL_BINS(spare9, 5'd13)
      `SMC_ELK_REFUSAL_BINS(spare10, 5'd14)
      `SMC_ELK_REFUSAL_BINS(spare11, 5'd15)
      `SMC_ELK_REFUSAL_BINS(spare12, 5'd16)
      `SMC_ELK_REFUSAL_BINS(spare13, 5'd17)
      `SMC_ELK_REFUSAL_BINS(spare14, 5'd18)
      `SMC_ELK_REFUSAL_BINS(spare15, 5'd19)
      `SMC_ELK_REFUSAL_BINS(spare16, 5'd20)
      `SMC_ELK_REFUSAL_BINS(spare17, 5'd21)
      `SMC_ELK_REFUSAL_BINS(spare18, 5'd22)
      `SMC_ELK_REFUSAL_BINS(spare19, 5'd23)
      `SMC_ELK_REFUSAL_BINS(spare20, 5'd24)
      `SMC_ELK_REFUSAL_BINS(spare21, 5'd25)
      `SMC_ELK_REFUSAL_BINS(spare22, 5'd26)
      `SMC_ELK_REFUSAL_BINS(spare23, 5'd27)
      `SMC_ELK_REFUSAL_BINS(spare24, 5'd28)
      `SMC_ELK_REFUSAL_BINS(spare25, 5'd29)
      `SMC_ELK_REFUSAL_BINS(spare26, 5'd30)
      `SMC_ELK_REFUSAL_BINS(spare27, 5'd31)
    }
  endgroup
  `undef SMC_ELK_SLOT_BINS
  `undef SMC_ELK_REFUSAL_BINS

  // The three operation bins of one image.
  `define SMC_EJL_OP_BINS(name, img) \
      bins name``_write = {{img, OpWrite}}; \
      bins name``_read_outside = {{img, OpReadOutside}}; \
      bins name``_read_identity = {{img, OpReadIdentity}};

  covergroup smc_efuse_jtag_lc_cg with function sample (logic [2:0] img, logic [1:0] op, logic err);
    option.per_instance = 1;
    // {image, operation}: 15 cells and the 3 recorded fallback bins.
    cp_image_op: coverpoint {
      img, op
    } {
      `SMC_EJL_OP_BINS(test_dev, ImgTestDev)
      `SMC_EJL_OP_BINS(prod, ImgProd)
      `SMC_EJL_OP_BINS(rma_sop, ImgRmaSop)
      `SMC_EJL_OP_BINS(rma_chiplet, ImgRmaChiplet)
      `SMC_EJL_OP_BINS(prod_end, ImgProdEnd)
      `SMC_EJL_OP_BINS(rec_invalid, ImgInvalid)
    }
    // A blocked read returning the stated word.
    cp_error_data: coverpoint err {
      bins blocked_read_word = {1'b1};
    }
  endgroup
  `undef SMC_EJL_OP_BINS

  covergroup smc_efuse_timeout_cg with function sample (
      logic ss, logic ifc, logic stall, logic cc, logic cls
  );
    option.per_instance = 1;
    // {graded, interface, stall}: 4 cells.
    cp_stall_status: coverpoint {
      ss, ifc, stall
    } {
      bins read_shorter = {{1'b1, IfcRead, StallShorter}};
      bins read_longer = {{1'b1, IfcRead, StallLonger}};
      bins program_shorter = {{1'b1, IfcProgram, StallShorter}};
      bins program_longer = {{1'b1, IfcProgram, StallLonger}};
    }
    // {graded, interface, count class}: 4 cells.
    cp_count: coverpoint {
      cc, ifc, cls
    } {
      bins read_in_range = {{1'b1, IfcRead, CntInRange}};
      bins read_reset = {{1'b1, IfcRead, CntReset}};
      bins program_in_range = {{1'b1, IfcProgram, CntInRange}};
      bins program_reset = {{1'b1, IfcProgram, CntReset}};
    }
  endgroup

  smc_state_inject_cg u_cg_state_inject = new();
  smc_efuse_lock_cg u_cg_efuse_lock = new();
  smc_efuse_jtag_lc_cg u_cg_efuse_jtag_lc = new();
  smc_efuse_timeout_cg u_cg_efuse_timeout = new();

  always_ff @(posedge clk_smc_i) begin
    if (!in_reset) begin
      // State injection: one sample per hook rise, the recovery apart.
      if (zeroer_cell_e) begin
        u_cg_state_inject.sample(BlkZeroer, zeroer_code[1:0], zeroer_ph, RecNone);
      end
      if (read_cell_e) u_cg_state_inject.sample(BlkRead, read_code[1:0], read_ph, RecNone);
      if (program_cell_e) begin
        u_cg_state_inject.sample(BlkProgram, program_code[1:0], program_ph, RecNone);
      end
      if (zeroer_rec_e) u_cg_state_inject.sample(BlkNone, 2'd0, PhNone, RecZeroer);
      if (read_rec_e) u_cg_state_inject.sample(BlkNone, 2'd0, PhNone, RecRead);
      if (program_rec_e) u_cg_state_inject.sample(BlkNone, 2'd0, PhNone, RecProgram);

      // Locks: every bit a LOCKS write sets, once the locks output carries
      // it; the field read that grades a write and the read itself.
      for (int unsigned b = 0; b < 64; b++) begin
        if (lock_pend_hit[b] && bit_slot_kind[b][6]) begin
          u_cg_efuse_lock.sample(1'b1, 1'b0, bit_slot_kind[b][5:1], bit_slot_kind[b][0], 2'd0);
        end
      end
      if (wr_kept) u_cg_efuse_lock.sample(1'b0, 1'b1, r_slot[4:0], 1'b0, OutWriteKept);
      if (wr_refused) u_cg_efuse_lock.sample(1'b0, 1'b1, r_slot[4:0], 1'b0, OutWriteRefused);
      if (rd_open) u_cg_efuse_lock.sample(1'b0, 1'b1, r_slot[4:0], 1'b0, OutReadReturned);
      if (rd_hidden) u_cg_efuse_lock.sample(1'b0, 1'b1, r_slot[4:0], 1'b0, OutReadHidden);

      // Lifecycle: one sample per JTAG eFuse completion.
      if (ej_wr_graded) u_cg_efuse_jtag_lc.sample(lc_img, OpWrite, 1'b0);
      if (ej_rd_graded || ej_err_word_e) begin
        u_cg_efuse_jtag_lc.sample(ej_rd_graded ? lc_img : ImgNone, ej_rd_graded ? ej_r_op : OpNone,
                                  ej_err_word_e);
      end

      // Timeout: the count class at the confirming read-back, the stall
      // class at the owner's control-register read after the done.
      if (tmo_rb[IfcRead] && tmo_cls[IfcRead][1]) begin
        u_cg_efuse_timeout.sample(1'b0, IfcRead, 1'b0, 1'b1, tmo_cls[IfcRead][0]);
      end
      if (tmo_rb[IfcProgram] && tmo_cls[IfcProgram][1]) begin
        u_cg_efuse_timeout.sample(1'b0, IfcProgram, 1'b0, 1'b1, tmo_cls[IfcProgram][0]);
      end
      if (read_stall_e) u_cg_efuse_timeout.sample(1'b1, IfcRead, read_stall_q, 1'b0, 1'b0);
      if (program_stall_e) u_cg_efuse_timeout.sample(1'b1, IfcProgram, program_stall_q, 1'b0, 1'b0);
    end
  end

endmodule : smc_efuse_ctrl_fcov
